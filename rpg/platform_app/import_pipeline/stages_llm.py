"""import_pipeline.stages_llm — 提取模型解析/凭证预检 + LLM 微任务阶段

来源: 原 rpg/platform_app/import_pipeline.py _resolve_extractor_llm 族 / _stage_story_phase_llm / _stage_cards / _stage_worldbook / _stage_npc_voices / _parse_json(原 L917-1125, 1264-1597, 1735-1875, 2141-2151) 区段,纯机械搬家(函数体逐字未动),零行为变化。
"""
from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb

from agents.provider_errors import (
    classify_provider_error,
    http_status,
    plain_error_summary,
    provider_error_summary,
)
from core.llm_backend import DEFAULT_FALLBACK_API, DEFAULT_FALLBACK_MODEL
from core.token_estimate import cjk_chars_to_budget
from model_aliases import credential_storage_api_id, normalize_api_id

from ..db import connect
from .errors import MissingUserCredentialError


def _resolve_extractor_llm(user_id: int) -> tuple[str, str]:
    """解析拆书流水线 LLM 配置。

    优先级:
      1. user_preferences["extractor.api_id"] / ["extractor.model_real_name"]
      2. user_preferences["agent.api_id"] / ["agent.model_real_name"]
      3. 默认: vertex_ai / gemini-3.5-flash

    返回 (api_id, model)。
    """
    from agents._harness import resolve_api_and_model
    api_id, model = resolve_api_and_model(
        user_id,
        api_pref_key="extractor.api_id",
        model_pref_key="extractor.model_real_name",
        default_api=DEFAULT_FALLBACK_API,
        default_model=DEFAULT_FALLBACK_MODEL,
    )
    # 别名→canonical 统一走全量别名表(原 _normalize_llm_api_id 只覆盖 vertex 残缺子集)。
    return normalize_api_id(api_id), model


def _credential_api_id_for(api_id: str) -> str:
    # 薄委托:canonical→凭证寻址(Vertex 存 "AgentPlatform" 行)。与 normalize_api_id 方向相反。
    return credential_storage_api_id(api_id)


def require_user_llm_credential(user_id: int) -> dict[str, str]:
    """Preflight paid LLM work before any import writes user-visible data."""
    api_id, model = _resolve_extractor_llm(user_id)
    _require_user_llm_credential(user_id, api_id, model)
    return {
        "api_id": api_id,
        "model": model,
        "credential_api_id": _credential_api_id_for(api_id),
    }


def _has_user_llm_credential(user_id: int | None, api_id: str) -> bool:
    # 薄委托 → core.llm_backend.user_can_use_provider(单一真源:vertex→BYOK SA / 其它→用户 key)。
    from core.llm_backend import user_can_use_provider
    return user_can_use_provider(user_id, api_id)


def _require_user_llm_credential(user_id: int, api_id: str, model: str) -> None:
    """Production import pipeline must use user-scoped credentials only."""
    if not _has_user_llm_credential(user_id, api_id):
        raise MissingUserCredentialError(api_id, model, _credential_api_id_for(api_id))


# 提取模型对**每个**候选都会同样失败的类别:遇到一次就别再对剩下的候选挨个打一遍
# (模型下线时以前要连撞 40 次,结果卡上还只写「N 个候选 LLM 调用报错」)。
# 403 不在内:它常是单条请求的内容被拦,换个候选可能就过了;401 按状态码单独判。
_FATAL_FOR_ALL_CANDIDATES = frozenset({
    "model_unavailable", "balance", "bad_request", "feature_unsupported",
})


def _provider_error_hint(exc: Exception, *, api_id: str, model: str) -> tuple[str, bool]:
    """LLM 阶段失败 → (给用户看的一句话原因, 是否对后续请求同样致命)。

    原因走 provider_errors 的分类(与对话里的报错同一口径),带上是哪个提取模型出的错 ——
    导入用的是「提取模型」不是对话模型,只说「换个模型」用户会去改错地方。
    """
    known = classify_provider_error(exc)
    text = known[1] if known else provider_error_summary(exc)
    who = f" (extraction model {api_id}/{model})" if (api_id or model) else ""
    fatal = bool(known) and (
        known[0] in _FATAL_FOR_ALL_CANDIDATES
        or (known[0] == "auth" and http_status(exc) == 401)
    )
    return f"{text}{who}", fatal


def _note_stage_error(ctl: Any, stage: str, hint: str) -> None:
    """把阶段失败原因记到 job 级对象上(runner / rebuild worker 从同一个 ctl 读)。"""
    note = getattr(ctl, "note_stage_error", None)
    if callable(note):
        try:
            note(stage, hint)
        except Exception:
            pass


def _note_stage_aborted(ctl: Any, stage: str, n: int) -> None:
    """记下某阶段提前停下后没再尝试的数量(job 级,runner 据此把阶段标 error)。"""
    box = getattr(ctl, "stage_aborted", None)
    if isinstance(box, dict):
        box[stage] = int(n)


def _stage_story_phase_llm(ctl: JobController, user_id: int, script_id: int) -> None:
    """facts 完成后，一次 LLM call 把章节范围分到 开端/发展/高潮/结局/番外。
    成功 → 按范围批量 update chapter_facts.story_phase；
    失败/解析不出 → 全部回退 "未明"。
    """
    api_id, model = _resolve_extractor_llm(user_id)

    with connect() as db:
        rows = db.execute(
            "select chapter, summary, title from chapter_facts "
            "where script_id = %s and (story_phase = '' or story_phase is null) "
            "order by chapter",
            (script_id,),
        ).fetchall()

    if not rows:
        return

    total = len(rows)
    # 均匀采样 ≤30 章喂给 LLM (成本控)；保留每章的 chapter 号让模型按号给区间
    if total <= 30:
        sample = rows
    else:
        step = max(1, total // 30)
        sample = rows[::step][:30]
    lines = "\n".join(
        f"Chapter {r['chapter']} \"{r['title']}\": {(r['summary'] or '')[:cjk_chars_to_budget(r['summary'] or '', 120)]}"
        for r in sample
    )
    prompt = (
        f"This book has {total} chapters (chapter 1 - chapter {total}); below are evenly sampled chapter summaries. "
        "Divide the chapter ranges into these 5 phases: 开端 (opening) / 发展前期 (early development) / "
        "发展中期 (middle development) / 发展后期 (late development) / 结局 (ending). "
        "Not every phase has to appear -- list only those that actually exist. These 5 phase labels are a fixed "
        "enum of the platform (the save spawn-point wizard and the GM's lookups depend on them), so use them "
        "**exactly as written, in Chinese**, and **never use any other label (such as climax / side story / prologue)**.\n\n"
        "Return a strict JSON array, one item per phase, with no text before or after:\n"
        '[{"phase":"开端","start":1,"end":N},{"phase":"发展前期","start":N+1,"end":M},...]\n\n'
        f"Chapter summaries:\n{lines}"
    )
    try:
        # 结构化微任务禁深思(268 实锤族)+空正文护栏
        from agents._harness import call_agent_json_guarded
        raw, last = call_agent_json_guarded(
            api_id, model,
            "You are a novel plot analyzer. Output a JSON array only.",
            prompt,
            user_id,
            log_tag="story_phase",
            max_tokens=400,
            no_think=True,
            agent_kind="import_pipeline",
        )
        from ..usage import compute_cost
        cost = float(compute_cost(api_id, model, last))
        ctl.add_usage(int(last.get("input_tokens", 0)), int(last.get("output_tokens", 0)), cost)

        # 5 段固定枚举,与 saves wizard birthpoints fallback 完全一致 —
        # phase_label 是跨层共享 key (chapter_facts.story_phase / phase_digests.phase_label
        # / state.world.timeline.current_phase / worldbook_agent._resolve_anchor)。
        valid = {"开端", "发展前期", "发展中期", "发展后期", "结局"}
        ranges = _parse_json(raw)
        # LLM 返非 array (dict / None / 解析失败) 时退化为**5 段均分**,
        # 而不是塞全书单一 "发展" — 单 phase 会让 worldbook_agent.consult 在任何
        # current_phase 输入下都 fallback 到那同一段,phase_digests 索引等于失效。
        # 5 段均分至少保证 birthpoints / phase_digests / GM 翻阅各层 phase 一致。
        if not isinstance(ranges, list) or not ranges:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "[story_phase] LLM returned non-array %r, falling back to 5-bucket even split",
                type(ranges).__name__,
            )
            try:
                ctl.update(warnings={
                    "stage": "story_phase_llm",
                    "exception": "InvalidResponse",
                    "message": f"The LLM did not return an array (type={type(ranges).__name__}); fell back to an even 5-way split",
                })
            except Exception:
                pass
            ranges = _even_split_phases(total)

        with connect() as db:
            for item in ranges:
                if not isinstance(item, dict):
                    continue
                phase = str(item.get("phase", "")).strip()
                if phase not in valid:
                    continue
                try:
                    start = int(item.get("start") or 1)
                    end = int(item.get("end") or total)
                except (TypeError, ValueError):
                    continue
                db.execute(
                    "update chapter_facts set story_phase = %s "
                    "where script_id = %s and chapter between %s and %s "
                    "and (story_phase = '' or story_phase is null)",
                    (phase, script_id, start, end),
                )
            # 剩余没匹配到的章 → 走 5 段均分兜底而不是塞 "未明"
            # ("未明" 标签不在 valid 集合里,会让 phase_digests 聚合出无意义的
            # "未明" phase entry,worldbook_agent 命中后给 GM 注入空摘要)
            _backfill_unphased_with_even_split(db, script_id, total)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[story_phase] LLM call failed, falling back to 5-bucket even split: %s",
            exc, exc_info=True,
        )
        try:
            with connect() as db:
                _backfill_unphased_with_even_split(db, script_id, total)
        except Exception as exc2:
            _logging.getLogger(__name__).warning(
                "[story_phase] fallback update failed: %s", exc2, exc_info=True,
            )
        try:
            ctl.update(warnings={
                "stage": "story_phase_llm",
                "exception": type(exc).__name__,
                "message": str(exc)[:300],
            })
        except Exception:
            pass


def _backfill_unphased_with_even_split(db, script_id: int, total: int) -> None:
    """LLM 推断失败/部分缺失时,把 story_phase 仍为空的章节按 5 段均分填回。
    避免 "未明" 标签污染 phase_digests。"""
    if total <= 0:
        return
    for item in _even_split_phases(total):
        db.execute(
            "update chapter_facts set story_phase = %s "
            "where script_id = %s and chapter between %s and %s "
            "and (story_phase = '' or story_phase is null)",
            (item["phase"], script_id, item["start"], item["end"]),
        )


def _even_split_phases(total: int) -> list[dict[str, Any]]:
    """把 total 章按 5 段均分:开端 / 发展前期 / 发展中期 / 发展后期 / 结局。

    与 saves wizard birthpoints fallback 用同一组 phase 标签,避免存档侧
    current_phase 和剧本侧 phase_digests 对不上号(常见症状:存档 timeline
    显示『开端』但 worldbook_agent 永远 fallback 到第一个 phase)。
    """
    if total <= 0:
        return []
    labels = ["开端", "发展前期", "发展中期", "发展后期", "结局"]
    # 章节 ≤ 5 时直接一一对应 + 截短
    if total <= 5:
        return [{"phase": labels[i], "start": i + 1, "end": i + 1} for i in range(total)]
    bucket = total // 5
    out = []
    for i, lab in enumerate(labels):
        s = i * bucket + 1
        e = (i + 1) * bucket if i < 4 else total  # 末段吃余数
        out.append({"phase": lab, "start": s, "end": e})
    return out

def _stage_cards(ctl: JobController, user_id: int, script_id: int, entities: list[dict[str, Any]]) -> int:
    """LLM 给 top N 人物生成人设卡。

    简化：调 call_agent_json 让模型按 JSON schema 输出。
    超时/失败的角色跳过，不阻断整个流水线。
    """
    from .. import knowledge
    api_id, model = _resolve_extractor_llm(user_id)

    # 候选定型后(_stage_entities 把截断名长回真名、折掉影子、滤掉虚词碎片),
    # 名额的含金量高了,但泛词仍会占掉一部分 —— 实测 script 143 的「詹岚」「楚轩」
    # 恰好卡在第 31、32 名。30 → 40 让这类刚出线的角色有机会,代价是每本书至多
    # 多 10 次 LLM 调用(单次 ~1.2k token,相对整个拆书流程可忽略)。
    top_n = 40
    targets = [e for e in entities[:top_n] if e["count"] >= 5]
    ctl.update(stage_progress=0, stage_total=len(targets))

    # 取每个角色的最相关文本片段（出现该名字的前 3 章节）
    with connect() as db:
        chapters_idx = db.execute(
            "select chapter_index, content from script_chapters where script_id = %s order by chapter_index",
            (script_id,),
        ).fetchall()
        book_row = db.execute(
            "select id from books where script_id = %s", (script_id,),
        ).fetchone()
        int(book_row["id"]) if book_row else None

    # 拉该 script 的 chapter_facts（用摘要做二次 pass 输入）
    with connect() as db:
        fact_rows = db.execute(
            "select chapter, summary, characters from chapter_facts "
            "where script_id = %s order by chapter",
            (script_id,),
        ).fetchall()

    # #5 角色卡去重: 预载该 script 现有 NPC 卡的 name/full_name/aliases(归一化)。
    # extract 时若候选角色(名或别名)已存在 → 跳过,避免"短名/全名"等变体产生重复卡。
    # 只跳过不覆盖 → 不会 clobber 用户手编卡;不改唯一索引/不迁移,零数据风险。
    def _norm_name(s: Any) -> str:
        return str(s or "").strip().casefold().replace(" ", "").replace("·", "").replace("・", "")
    existing_keys: set[str] = set()
    try:
        with connect() as db:
            for cr in db.execute(
                "select name, full_name, aliases from character_cards "
                "where script_id=%s and card_type='npc'",
                (script_id,),
            ).fetchall():
                existing_keys.add(_norm_name(cr.get("name")))
                if cr.get("full_name"):
                    existing_keys.add(_norm_name(cr.get("full_name")))
                for _a in (cr.get("aliases") or []):
                    existing_keys.add(_norm_name(_a))
        existing_keys.discard("")
    except Exception:
        existing_keys = set()

    generated = 0
    llm_failures = 0  # phase_backend: 累计 LLM 调用失败次数(抛异常),>50% 标 partial
    # 反馈 #99:调用「成功」但输出没法用(JSON 解不出 / 自称人名却给不出 identity)以前
    # 静默 continue —— 弱模型(本地 ollama / 中转小模型)整批解不出时,阶段照报 done、
    # 卡只出寥寥几张,用户只看到「人物做不出来」而无任何线索。分开计数 + 留日志 + 进 warnings。
    unusable = 0   # 输出不可用(解不出 JSON / 空正文 / identity 空)
    rejected = 0   # 模型明确判「不是人名」—— 正常筛掉,不算失败
    skipped_dup = 0  # 已有同名/别名卡,跳过不重复建
    no_context = 0   # 摘要/正文里都找不到该名字的上下文,没法喂 LLM
    aborted = 0      # 提取模型对所有候选都会同样失败(下线/欠费/参数不认…)后,没再尝试的候选数
    first_hint = ""  # 第一条调用失败的可读原因(分类后),写进 warnings 与阶段条目
    for i, entity in enumerate(targets):
        if ctl.is_cancelled():
            raise RuntimeError("cancelled")
        name = entity["name"]

        # #5 去重(pre-LLM): 候选名已等于某现有卡的 name/别名 → 跳过,省 LLM 调用 + 不重复建卡。
        if _norm_name(name) in existing_keys:
            skipped_dup += 1
            ctl.update(stage_progress=i + 1)
            continue

        # 优先用 chapter_facts 摘要（信噪比高），fallback 到原始章节文本片段
        relevant_summaries = []
        for fr in fact_rows:
            chars = fr.get("characters") or []
            if isinstance(chars, list) and any(
                isinstance(c, dict) and c.get("name") == name for c in chars
            ):
                relevant_summaries.append(f"Chapter {fr['chapter']}: {(fr['summary'] or '')[:cjk_chars_to_budget(fr['summary'] or '', 200)]}")
            if len(relevant_summaries) >= 8:
                break

        if relevant_summaries:
            context = "Chapter summaries (relevant to this character):\n" + "\n".join(relevant_summaries)
        else:
            snippets = []
            for ch in chapters_idx:
                _pos = ch["content"].find(name)
                if _pos >= 0:
                    # 取名字首次出现附近的窗口(按 token 预算,英文 ~3750 字符)
                    _win = cjk_chars_to_budget(ch["content"], 1500)
                    _st = max(0, _pos - _win // 3)
                    snippets.append(ch["content"][_st:_st + _win])
                    if len(snippets) >= 3:
                        break
            if not snippets:
                no_context += 1
                ctl.update(stage_progress=i + 1)
                continue
            context = "Text excerpts:\n" + "\n---\n".join(snippets)

        # task 47: 显式让 LLM 判断"这是真人名吗",false 时直接跳过不写卡。
        # 2-3 字中文 ngram 候选有大量副词/连词/动词性短语(为什么/的声音/紧接着/有德的)
        # 维护硬编码 blacklist 永远跟不上内容,LLM 一个布尔判断成本极低且精度高。
        prompt = (
            f"Decide whether \"{name}\" is the name of an actual character (not an adverb / conjunction / verb / place / object / fragment) and return strict JSON:\n"
            "If it is not a character's name, return {\"is_character\": false}\n"
            "If it is a character's name, return {\n"
            "  \"is_character\": true,\n"
            "  \"identity\": \"identity / occupation / allegiance\",\n"
            "  \"appearance\": \"appearance\",\n"
            "  \"personality\": \"personality traits\",\n"
            "  \"speech_style\": \"way of speaking\",\n"
            "  \"secrets\": \"secrets or important foreshadowing (empty string if none)\",\n"
            "  \"aliases\": [\"alias 1\"]\n"
            "}\n\n"
            + context
        )
        # 模型调用本身返回了没有:之后(解析/记账/写卡)抛的异常不是服务商的问题,不能拿去
        # provider_errors 分类 —— psycopg 的「relation … does not exist」会被说成「模型不可用」,
        # 还会触发下面的提前停。
        llm_answered = False
        try:
            # 结构化微任务禁深思(268 实锤族)+空正文护栏
            from agents._harness import call_agent_json_guarded
            raw, last = call_agent_json_guarded(
                api_id, model,
                "You are a character-card extractor. Judge strictly whether the name is an actual character's name. Output JSON only. "
                "[Fiction hard rule] This work is a fictional novel. Even if a character shares a name with a real historical "
                "figure, every field **may only be based on the given chapter excerpts / summaries**; never bring in real "
                "historical facts, biographies or encyclopedic knowledge you know (anything the excerpts do not contain). "
                "If the excerpts give no basis for a field, leave it empty.",
                prompt,
                user_id,
                log_tag="card_extract",
                # 思考型模型(ds-v4-pro 一类)会先花掉几百 token 推理,700 常常正文没写完
                # 就被打断 → 半份 JSON。no_think 那套 thinking.disabled 是厂商方言,
                # 中转站/自托管端点未必认,不能指望它,预算要留够。
                max_tokens=1200,
                no_think=True,
                require_json=True,   # 解析不出 → 扩预算重试一次(见 _harness 护栏)
                agent_kind="import_pipeline",
            )
            llm_answered = True
            data = _parse_json(raw)
            # 累 usage(无论是否写卡,LLM 都跑了)
            from ..usage import compute_cost
            cost = float(compute_cost(api_id, model, last))
            ctl.add_usage(int(last.get("input_tokens", 0)), int(last.get("output_tokens", 0)), cost)
            # task 47: LLM 明确说不是人名 → 跳过;identity 为空也判定为假名(双保险)
            # 三种「没写卡」必须分清:不可用输出 ≠ 模型正常否决(反馈 #99)。
            if not isinstance(data, dict):
                unusable += 1
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "[cards] %r: 模型输出不是可解析 JSON,跳过(前 120 字: %s)",
                    name, (raw or "")[:120].replace("\n", " ") or "<空正文>",
                )
            elif data.get("is_character") is False:
                rejected += 1
            elif not (data.get("identity") or "").strip():
                unusable += 1
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "[cards] %r: 模型判为人名但 identity 为空,跳过", name,
                )
            else:
                # #5 去重(post-LLM): 候选名或其别名已存在 → 跳过,不创建短名/全名变体重复卡。
                _cand_keys = {_norm_name(name)} | {_norm_name(a) for a in (data.get("aliases") or [])}
                _cand_keys.discard("")
                if _cand_keys & existing_keys:
                    skipped_dup += 1
                    ctl.update(stage_progress=i + 1)
                    continue
                # 写入 character_cards(含 secrets 字段)
                knowledge.upsert_character_card(user_id, script_id, {
                    "name": name,
                    "aliases": data.get("aliases") or [],
                    "identity": data.get("identity") or "",
                    "appearance": data.get("appearance") or "",
                    "personality": data.get("personality") or "",
                    "speech_style": data.get("speech_style") or "",
                    "secrets": data.get("secrets") or "",
                    "metadata": {"source": "llm_pipeline", "freq": entity["count"]},
                })
                generated += 1
                existing_keys |= _cand_keys  # 防同一次 run 内后续变体重复建卡
        except Exception as exc:
            # phase_backend: 不再 silent swallow,记 warning(exc_info=True)
            # 同时累计 LLM 失败,>50% targets 全失败时主 worker 标 partial
            llm_failures += 1
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "[cards] LLM card for %r failed: %s", name, exc, exc_info=True,
            )
            if llm_answered:
                _hint, _fatal = f"Error while writing the character card: {plain_error_summary(exc)}", False
            else:
                _hint, _fatal = _provider_error_hint(exc, api_id=api_id, model=model)
            if not first_hint:
                first_hint = _hint
                _note_stage_error(ctl, "cards", _hint)
            if _fatal:
                aborted = len(targets) - (i + 1)
                _logging.getLogger(__name__).warning(
                    "[cards] script=%s: 提取模型 %s/%s 对所有候选都会失败(%s),剩余 %d 个候选不再尝试",
                    script_id, api_id, model, type(exc).__name__, aborted,
                )
                ctl.update(stage_progress=len(targets))
                break
        ctl.update(stage_progress=i + 1)
    # 「没答上来」= 调用抛异常 + 输出不可用。两者都该让用户看见,不能只数异常
    # (反馈 #99:弱模型不抛异常,只是吐不出 JSON —— 老口径下 100% 静默)。
    # 提前停下的候选同样算「没答上来」:它们不是被筛掉,而是模型已经不可用。
    answer_failures = llm_failures + unusable + aborted
    if targets and (
        answer_failures > len(targets) // 2
        or (generated == 0 and answer_failures > 0)
        or aborted
    ):
        try:
            ctl.update(
                warnings={
                    "stage": "cards",
                    "llm_failures": llm_failures,
                    "unusable": unusable,
                    "rejected": rejected,
                    "skipped_dup": skipped_dup,
                    "no_context": no_context,
                    "targets": len(targets),
                    "generated": generated,
                    "aborted": aborted,
                    "reason": first_hint,
                },
            )
        except Exception:
            pass
    if unusable:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[cards] script=%s: %s/%s 个候选的模型输出不可用(解不出 JSON 或 identity 空),"
            "生成 %s 张卡 —— 提取模型多半不适配结构化输出,建议在设置里换提取模型",
            script_id, unusable, len(targets), generated,
        )
    # 返给 _run_pipeline 决定是否标 partial(口径 = 异常 + 不可用输出)
    _stage_cards._last_llm_failures = answer_failures
    _stage_cards._last_exceptions = llm_failures
    _stage_cards._last_unusable = unusable
    _stage_cards._last_rejected = rejected
    _stage_cards._last_skipped_dup = skipped_dup
    _stage_cards._last_no_context = no_context
    _stage_cards._last_targets = len(targets)
    _note_stage_aborted(ctl, "cards", aborted)  # job 级,不挂函数属性(并发导入会串到别的 job)
    return generated


def _stage_worldbook(ctl: JobController, user_id: int, script_id: int) -> int:
    """LLM 从 chapter_facts 摘要 + facts 提取世界观条目入 worldbook_entries。"""
    api_id, model = _resolve_extractor_llm(user_id)

    with connect() as db:
        book_row = db.execute(
            "select id from books where script_id = %s", (script_id,),
        ).fetchone()
        if not book_row:
            return 0
        book_id = int(book_row["id"])

        # 用 chapter_facts 摘要 + locations/factions/concepts 作为输入（比原始文本信噪比高）
        fact_rows = db.execute(
            "select chapter, summary, locations, factions, concepts "
            "from chapter_facts where script_id = %s order by chapter limit 40",
            (script_id,),
        ).fetchall()

    ctl.update(stage_progress=0, stage_total=1)

    if fact_rows:
        summaries_block = "\n".join(
            f"Chapter {r['chapter']}: {(r['summary'] or '')[:cjk_chars_to_budget(r['summary'] or '', 100)]}"
            for r in fact_rows[:30]
        )
        # 聚合高频地点/势力/概念作为提示
        from collections import Counter as _Counter
        loc_cnt: _Counter = _Counter()
        fac_cnt: _Counter = _Counter()
        con_cnt: _Counter = _Counter()
        for r in fact_rows:
            for item in (r.get("locations") or []):
                if isinstance(item, dict):
                    loc_cnt[item.get("name", "")] += item.get("count", 1)
            for item in (r.get("factions") or []):
                if isinstance(item, dict):
                    fac_cnt[item.get("name", "")] += item.get("count", 1)
            for item in (r.get("concepts") or []):
                if isinstance(item, dict):
                    con_cnt[item.get("name", "")] += item.get("count", 1)
        top_locs = [n for n, _ in loc_cnt.most_common(10) if n]
        top_facs = [n for n, _ in fac_cnt.most_common(10) if n]
        top_cons = [n for n, _ in con_cnt.most_common(10) if n]
        hints = (
            f"Frequent locations: {', '.join(top_locs)}\n"
            f"Frequent factions: {', '.join(top_facs)}\n"
            f"Frequent concepts: {', '.join(top_cons)}\n"
        )
        seed = hints + "\nChapter summaries:\n" + summaries_block
    else:
        with connect() as db:
            chapters = db.execute(
                "select content from script_chapters where script_id = %s order by chapter_index",
                (script_id,),
            ).fetchall()
        seed = "\n".join(c["content"] for c in chapters)
        seed = seed[:cjk_chars_to_budget(seed, 8000)]

    # 读取新提取管线已落库的纪元(若存在),作为铁律塞进 prompt,治 _stage_worldbook 独立 LLM
    # 凭空编"哥本哈根研究所 2927年创立"这种带具体年份的 hallucination
    era_lock = ""
    with connect() as db:
        era_row = db.execute(
            "select content from worldbook_entries where script_id=%s and title in ('Era', '纪元') limit 1",
            (script_id,),
        ).fetchone()
        if era_row and era_row.get("content"):
            era_lock = str(era_row["content"])[:200]
    era_iron_rule = (
        f"[Era hard rule] {era_lock}\nNever invent specific founding years / event years in content; "
        "if a date must be mentioned, refer only to the era above and **never write real historical years** (1927 / 1935 / 1940 etc.).\n"
        if era_lock else
        "[Era constraint] Do not invent specific years in content (avoid hallucination); describe only background / characters / geography / faction relations.\n"
    )
    prompt = (
        era_iron_rule +
        "From the chapter summaries and frequent entities below, extract the important world-building entries (locations / factions / concepts) and return a strict JSON array:\n"
        "[{\"name\":\"...\",\"keys\":[\"keyword 1\",\"keyword 2\"],\"content\":\"<= 130-word explanation\",\"priority\":80}]\n"
        "At most 20 entries.\n\n" + seed
    )
    llm_answered = False  # 同 _stage_cards:模型答完之后(写库)出的错不进服务商分类
    try:
        # 结构化微任务禁深思(268 实锤族)+空正文护栏
        from agents._harness import call_agent_json_guarded
        raw, last = call_agent_json_guarded(
            api_id, model,
            "You are a worldbook editor. Output a JSON array only.",
            prompt,
            user_id,
            log_tag="worldbook_extract",
            max_tokens=2000,
            no_think=True,
            agent_kind="import_pipeline",
        )
        llm_answered = True
        from ..usage import compute_cost
        cost = float(compute_cost(api_id, model, last))
        ctl.add_usage(int(last.get("input_tokens", 0)), int(last.get("output_tokens", 0)), cost)
        entries = _parse_json(raw) or []
        if not isinstance(entries, list):
            entries = []
        if not entries:
            # 调用成功但拿不到条目:以前阶段条目只剩「未知错误」。
            _note_stage_error(
                ctl, "worldbook",
                "The model returned no usable worldbook entries (no JSON array could be parsed, or it was empty). "
                "The extraction model probably does not handle structured output well; try a different extraction model in Settings "
                f"(extraction model {api_id}/{model})",
            )
        count = 0
        with connect() as db:
            for entry in entries[:20]:
                if not isinstance(entry, dict) or not entry.get("name"):
                    continue
                _cur = db.execute(
                    """
                    insert into worldbook_entries(
                      book_id, script_id, title, keys, content, priority, enabled, metadata
                    ) values (%s, %s, %s, %s, %s, %s, true, %s)
                    on conflict (script_id, title) do update set
                      content   = excluded.content,
                      keys      = excluded.keys,
                      priority  = excluded.priority,
                      metadata  = excluded.metadata,
                      updated_at = now()
                    where coalesce(worldbook_entries.metadata->>'source','') <> 'editor'
                    """,
                    (
                        book_id, script_id,
                        str(entry["name"])[:120],
                        Jsonb(entry.get("keys") or [entry["name"]]),
                        str(entry.get("content") or "")[:2000],
                        int(entry.get("priority") or 80),
                        Jsonb({"source": "llm_pipeline"}),
                    ),
                )
                # rowcount=1 表示插入或更新成功;冲突且 where 不满足(editor 条目)时 rowcount=0。
                # psycopg3:rowcount 在 execute() 返回的 cursor 上,不在 Connection 上
                # (旧代码 `db.rowcount` → AttributeError,整个 worldbook LLM 抽取阶段崩、条目没入库)。
                count += (getattr(_cur, "rowcount", 0) or 0)
        if entries and count <= 0:
            # 模型给了条目却一条没写进去:以前阶段条目同样只剩「未知错误」。
            _note_stage_error(
                ctl, "worldbook",
                f"The model returned {len(entries)} worldbook entries, but none were written: "
                "entries were missing a name, or an entry with the same name was written by hand in the editor (import never overwrites hand-written entries)",
            )
        ctl.update(stage_progress=1)
        # phase_backend: 标记 worldbook 阶段写了多少条 — 0 当作 partial 让上层标 done_with_errors
        _stage_worldbook._last_count = count
        return count
    except Exception as exc:
        # phase_backend: 不 silent swallow,把 LLM 失败写到 import_jobs.error + warnings
        import logging as _logging
        import traceback as _tb
        _logging.getLogger(__name__).warning(
            "[worldbook] LLM extract failed: %s", exc, exc_info=True,
        )
        # 原因经分类写进阶段条目(runner / rebuild worker 从 ctl 读);job.error 只留一句短话,
        # 不然导入结果卡上 job.error 和阶段明细会把同一段原因显示两遍。
        # 以前 job.error 是「_stage_worldbook: HTTPError: HTTP Error 410: Gone」,阶段条目显示「未知错误」。
        if llm_answered:
            _hint = f"Error while writing worldbook entries: {plain_error_summary(exc)}"
        else:
            _hint, _ = _provider_error_hint(exc, api_id=api_id, model=model)
        _note_stage_error(ctl, "worldbook", _hint)
        try:
            ctl.update(
                stage_progress=1,
                error="Worldbook stage failed; see the stage details for the reason",
                warnings={
                    "stage": "worldbook",
                    "exception": type(exc).__name__,
                    "message": str(exc)[:500],
                    "reason": _hint,
                    "traceback": _tb.format_exc()[:800],
                },
            )
        except Exception:
            pass
        _stage_worldbook._last_count = 0
        return 0

def _stage_npc_voices(user_id: int, script_id: int, *, max_npc: int = 20, only_empty: bool = True) -> int:
    """LLM 抽 NPC 的 personality / speech_style / sample_dialogue 结构化字段,写回 character_cards。

    设计原则(harness):
      · 数据底座产出**结构化字段**,而不是注入原文片段让 GM 自学
      · GM 看 character_card 直接拿到 "性格: 平静、镇定、戏谑信息密度高"
        + "说话风格: 称玩家'被选中者',尾音常用'呢/呐'" + "台词示例: [...]"
      · 不依赖 GM 遵守 "学风格不复述" 这种 prompt 指令
      · LLM 抽的是高密度结构化数据,代价合理(每 NPC 一次 LLM,典型 30-100 NPC)

    数据源(给 LLM 的上下文):
      · character_card.identity + background + aliases (已抽过的结构化)
      · documents 反查 name + aliases 命中段 ×3,每段 ±400 字符(上下文足够丰富)

    LLM 输出 schema:
      {
        "personality": "≤80字性格特点,具体形容词+行为倾向",
        "speech_style": "≤80字说话风格,语气+常用词+句式特征",
        "sample_dialogue": ["原文里此人最有代表性的 2-3 句台词,逐字摘"]
      }

    args:
      script_id: 目标剧本
      max_npc: 单次最多处理几个 NPC (按 importance desc),避免一次跑爆
      only_empty: True 时只补 personality/speech_style 全空的卡,False 时全部覆盖重抽

    返回 backfilled count。
    """
    api_id, model = _resolve_extractor_llm(user_id)
    import logging as _log
    log = _log.getLogger(__name__)
    with connect() as db:
        where = "script_id=%s and card_type='npc'"
        params: list = [script_id]
        if only_empty:
            where += " and (coalesce(personality,'')='' or coalesce(speech_style,'')='')"
        rows = db.execute(
            f"select id, name, aliases, identity, background, "
            f"       first_revealed_chapter, importance "
            f"from character_cards where {where} "
            f"order by importance desc nulls last, priority desc nulls last "
            f"limit %s",
            (*params, int(max_npc)),
        ).fetchall() or []
    if not rows:
        return 0

    backfilled = 0
    for r in rows:
        name = r["name"]
        first_ch = int(r["first_revealed_chapter"] or 1)
        # 拉原文片段(用 lookup_entity 的 helper 逻辑,这里就地实现)
        try:
            with connect() as db:
                doc_rows = db.execute(
                    "select sc.chapter_index, d.content from documents d "
                    "join script_chapters sc on sc.id = d.chapter_id "
                    "where d.script_id=%s and sc.chapter_index between %s and %s "
                    "order by sc.chapter_index asc",
                    (script_id, first_ch, first_ch + 2),
                ).fetchall() or []
            aliases = r["aliases"] or []
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(",") if a.strip()]
            terms = [name] + [a for a in aliases if isinstance(a, str) and a]
            excerpts: list[str] = []
            for dr in doc_rows:
                content = dr["content"] or ""
                for term in terms:
                    idx = content.find(term)
                    if idx < 0:
                        continue
                    start = max(0, idx - 400)
                    end = min(len(content), idx + len(term) + 400)
                    excerpts.append(content[start:end].strip())
                    break
                if len(excerpts) >= 3:
                    break
            if not excerpts:
                log.info(f"[npc_voice] skip {name}: no source excerpts found")
                continue
        except Exception as exc:
            log.warning(f"[npc_voice] skip {name}: excerpt fetch failed: {exc}")
            continue

        prompt = (
            f"Analyze how the NPC \"{name}\" is portrayed in the source text and produce a **structured** personality and speaking style, "
            f"which the RPG engine hands to the GM so it can play the character accurately. **No lengthy interpretation.**\n\n"
            f"Known identity: {r['identity'] or '(empty)'}\n"
            f"Known background: {r['background'] or '(empty)'}\n\n"
            f"Source excerpts (scenes where this NPC appears; may be incomplete):\n"
            + "\n---\n".join(excerpts) + "\n\n"
            "Output strict JSON (no text before or after); all fields are required:\n"
            "{\n"
            '  "personality": "<= 50 words: personality, using concrete adjectives + behavioral tendencies (e.g. calm, teasing, information-dense, rarely shows emotion)",\n'
            '  "speech_style": "<= 50 words: way of speaking -- tone + favorite words + sentence patterns (e.g. calls the other person \\"the chosen one\\", '
            'ends lines with a soft drawl, cold statements laced with teasing rhetorical questions)",\n'
            '  "sample_dialogue": ["2-3 of the most representative lines quoted VERBATIM from the source, keeping the quotation marks"]\n'
            "}"
        )
        try:
            # 结构化微任务禁深思(268 实锤族)+空正文护栏
            from agents._harness import call_agent_json_guarded
            raw, last = call_agent_json_guarded(
                api_id, model,
                "You are an RPG character-profile extractor. Output structured JSON only, no explanation. "
                "[Fiction hard rule] This work is a fictional novel. Even if a character shares a name with a real historical "
                "figure, summarize their personality / speaking style **only from the source excerpts given above**; never mix "
                "in real history, biographies or encyclopedic knowledge you know. If the excerpts are thin, write a general "
                "short phrase; do not make things up.",
                prompt, user_id, log_tag="npc_voice", max_tokens=500, no_think=True,
                agent_kind="import_pipeline",
            )
            data = _parse_json(raw)
            if not isinstance(data, dict):
                log.warning(f"[npc_voice] {name}: LLM returned non-dict {type(data).__name__}")
                continue
            personality = str(data.get("personality") or "").strip()[:400]
            speech_style = str(data.get("speech_style") or "").strip()[:400]
            sample = data.get("sample_dialogue") or []
            if not isinstance(sample, list):
                sample = []
            sample = [str(x)[:400] for x in sample[:5] if x]
            if not personality and not speech_style:
                log.info(f"[npc_voice] {name}: LLM 返回空 personality+speech_style, skip update")
                continue
            with connect() as db:
                db.execute(
                    "update character_cards set "
                    "  personality = case when length(%s) > 0 then %s else personality end, "
                    "  speech_style = case when length(%s) > 0 then %s else speech_style end, "
                    "  sample_dialogue = case when array_length(%s::text[], 1) > 0 then %s::jsonb else sample_dialogue end, "
                    "  updated_at = now() "
                    "where id = %s",
                    (personality, personality, speech_style, speech_style,
                     sample, json.dumps(sample, ensure_ascii=False), r["id"]),
                )
            backfilled += 1
            log.info(f"[npc_voice] {name}: 写回 personality={personality[:30]}... speech_style={speech_style[:30]}...")
        except Exception as exc:
            log.warning(f"[npc_voice] {name}: LLM call failed: {exc}")
            continue
    return backfilled

def _parse_json(text: str) -> Any:
    """收口到 core.json_parse.parse_llm_json(全站单一鲁棒实现)。

    2026-08-24(反馈 #99):本文件此前留着最原始的贪婪正则版 —— 全站其它调用点
    (extract/llm.py、phase_digest_agent、character_card_generator)早就收口过去了,
    唯独拆书流水线漏了。实测三种形态它接不住,而拆书恰恰全撞上:
      · 思考型模型(deepseek-v4-pro 一类)的 <think> 块里自带花括号 → 抓到推理里的假括号;
      · max_tokens 打断在半路 → 没有收尾括号,整份丢弃;
      · `{"a":1,}` 尾逗号。
    另外贪婪的「首括号吃到尾括号」正则在示例+答案两块并存时会拼出非法 JSON。

    allow_truncated=True:拆书是「能捞多少是多少」的场景 —— 截断响应里已完整的字段
    (identity/appearance…)照样能写出一张有用的卡,整份丢掉才是浪费。
    """
    from core.json_parse import parse_llm_json
    return parse_llm_json(text, allow_truncated=True)
