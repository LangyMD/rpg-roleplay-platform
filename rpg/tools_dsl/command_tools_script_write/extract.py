"""command_tools_script_write §提取/委派族(拆包 2026-07-14,纯机械搬家零行为变化)。

extract_from_selection:对选中正文跑结构化提取(只产提议不写库,调一次提取 LLM/BYOK)。
delegate_writing_task:派用户自己配置的(BYOK)子模型做写作任务(绝不平台兜底)。
"""
from __future__ import annotations

import json
from typing import Any

from ._helpers import _resolve_sid, _user_can_read_script


def _t_extract_from_selection(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """对用户选中的一段正文跑结构化提取(复用 extract/per_chapter.extract_chapter 的提取器,含其
    反史实/反编造/中文别名归并铁律),返回提议的人物/势力/地点/概念/事件/摘要 —— 供 agent 按用户意愿
    用 upsert_canon_entity / update_npc_card / upsert_worldbook_entry / create_anchor 落库(经写入权限闸)。
    本工具只产提议、不写库;会调一次提取 LLM(BYOK)。这是「把提取器拆成选区工具」的核心(作者优先)。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "Failed: script_id is required"
    text = str(args.get("text") or "").strip()
    if not text:
        return "Failed: text is required (the selected prose to extract information from)"
    text = text[:8000]
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if not _user_can_read_script(db, sid, user_id):
                return "Failed (permission): the script does not belong to the current user or is not subscribed"
            known = [r["name"] for r in (db.execute(
                "select name from kb_canon_entities where script_id=%s and coalesce(name,'')<>'' "
                "order by importance desc, id asc limit 200", (sid,)).fetchall() or [])]
        from agents._harness import resolve_api_and_model
        api_id, model_real = resolve_api_and_model(
            user_id, api_pref_key="extractor.api_id", model_pref_key="extractor.model_real_name")
        if not api_id or not model_real:
            return "Failed: no usable extraction model found. Configure an extractor (or editor/GM) model under 'Settings -> Module models' and try again."
        from extract.llm import ExtractLLM
        from extract.per_chapter import UNUSABLE_OUTPUT_REASON, extract_chapter
        llm = ExtractLLM(model=str(model_real), api_id=str(api_id), user_id=user_id,
                         script_id=sid, algorithm="editor_selection")
        ex = extract_chapter(llm, 0, text, era="", known_entities=known)
        if not getattr(ex, "raw_ok", False):
            # extract_chapter 把调用异常吞成 raw_ok=False,原因在 ex.error(已按 provider_errors 分类):
            # 模型下线 / 欠费时再说「没返回有效结构」会把人支去换选区。
            # 输出解析不出 JSON 时仍给原来那句(编辑器里「缩短选区」是有用的建议)。
            _why = str(getattr(ex, "error", "") or "")
            if _why and _why != UNUSABLE_OUTPUT_REASON:
                return f"Extraction failed: {_why}"
            return "Extraction failed: the model did not return a valid structure. Try a stronger extraction model or a shorter selection."
        proposal = {
            "summary": getattr(ex, "chapter_summary", ""),
            "entities": getattr(ex, "entities", []),       # type=character/faction/location/...,含 full_name/aliases/identity/background/subtype/parent
            "concepts": getattr(ex, "concepts", []),
            "events": getattr(ex, "events", []),
            "relationships": getattr(ex, "relationships", []),
        }
        body = json.dumps(proposal, ensure_ascii=False, indent=2)[:6000]
        return ("[Proposals extracted from the selection (not yet saved)] First tell the user in one sentence what you will create/change, then persist it (writes go through the three-level permission gate): "
                "entities with type=character -> upsert_canon_entity, or generate_character_card_draft and then create an NPC card; "
                "faction/location/concept -> upsert_canon_entity or upsert_worldbook_entry; events -> create_anchor.\n"
                + body)
    except Exception as exc:
        try:
            from agents.provider_errors import classify_provider_error
            k = classify_provider_error(exc)
            if k:
                return f"Extraction failed: {k[1]}"
        except Exception:
            pass
        return f"Extraction failed: {type(exc).__name__}: {str(exc)[:120]}"


def _t_delegate_writing_task(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    task = str(args.get("task") or "").strip()
    if not task:
        return "Failed: task is required (the writing task to delegate to the sub-model, e.g. 'write the first 200 words of chapter 5 in a terse, cold style')"
    api_id_in = str(args.get("api_id") or "").strip()
    model_in = str(args.get("model") or args.get("model_real_name") or "").strip()
    # 1) 解析模型:显式优先 → 用户 writer/gm 偏好。
    api_id = model = ""
    try:
        from agents._harness import resolve_api_and_model
        api_id, model = resolve_api_and_model(
            user_id, api_pref_key="writer.api_id", model_pref_key="writer.model_real_name",
            api_id_override=(api_id_in or None), model_override=(model_in or None),
        )
    except Exception:
        api_id = model = ""
    if not (api_id and model):
        try:
            from core.llm_backend import first_user_model
            fu = first_user_model(user_id)
            if fu:
                api_id, model = fu
        except Exception:
            pass
    if not (api_id and model):
        return ("Delegation failed: no usable model found. This tool only uses [models you configured yourself] (no platform fallback); "
                "configure and test a model of your own under 'Settings -> APIs & models' and try again.")
    # 2) 强制 BYOK:用户必须持有该 provider 的 key —— 不走 env/平台兜底(用户铁律)。
    try:
        from platform_app.user_credentials import resolve_api_key
        if not resolve_api_key(user_id, api_id, env_fallback="").get("key"):
            return (f"Delegation failed: model {api_id}/{model} has no API key of your own. This tool only uses models you configured yourself; "
                    "configure that provider's key under 'Settings -> APIs & models', or switch to a model that is already configured.")
    except Exception as exc:  # noqa: BLE001
        return f"Delegation failed (credential check error): {type(exc).__name__}: {exc}"
    # 3) 构造后端 + 纯文本生成;任何失败都明确回报(让主 agent 转述/换模型重试)。
    try:
        from agents.gm import GameMaster
        backend = GameMaster(api_id=str(api_id), model=str(model), user_id=user_id)._backend
    except Exception as exc:  # noqa: BLE001
        from agents.provider_errors import classify_provider_error
        known = classify_provider_error(exc)
        return f"Delegation failed (backend initialization {api_id}/{model}): {known[1] if known else f'{type(exc).__name__}: {exc}'}"
    try:
        max_tokens = min(6000, max(400, int(args.get("max_tokens") or 2500)))
    except (TypeError, ValueError):
        max_tokens = 2500
    ctx = str(args.get("context") or "")[:8000]
    sys_p = ("You are a fiction-writing assistant. Produce the [finished prose/content] directly, exactly as the user asks; "
             "do not explain, do not add any preamble or closing notes, and do not restate the task.")
    # 直连 backend(未经 _harness),输出语言在此确定性补上
    try:
        from core.language import language_directive
        sys_p += language_directive(user_id)
    except Exception:
        pass
    user_p = (f"[Reference context]\n{ctx}\n\n" if ctx else "") + f"[Writing task]\n{task}"
    try:
        parts: list[str] = []
        for chunk in backend.stream(sys_p, [{"role": "user", "content": user_p}], max_tokens=max_tokens):
            if chunk:
                parts.append(chunk)
        out = "".join(parts).strip()
    except Exception as exc:  # noqa: BLE001
        from agents.provider_errors import classify_provider_error
        known = classify_provider_error(exc)
        return (f"Delegation failed (model {api_id}/{model} call error): "
                f"{known[1] if known else f'{type(exc).__name__}: {exc}'}. Try again with another model you have configured.")
    if not out:
        return (f"Delegation failed: model {api_id}/{model} returned empty content (a reasoning model may need a larger max_tokens, "
                "or the relay refused). Raise max_tokens, switch models or retry.")
    return (f"[Output of sub-model {api_id}/{model} · for reference only; confirm with the user before saving]\n{out}")


