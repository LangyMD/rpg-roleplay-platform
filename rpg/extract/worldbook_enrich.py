"""extract/worldbook_enrich.py — 世界书核心设定条目充实(拆书审计 R5 存量侧)。

背景:concepts.gloss 曾被 schema 封顶 ≤30 字 + first-gloss-wins,核心设定(战姬/魔导装甲…)
在世界书里只剩一句话,而原文机制质感(护盾档位/血统分级/型号/建制)零反映 → GM「无米下锅」,
演出来的世界没有原著味(用户观感实锤)。

本模块按需(admin CLI)对指定条目做 LLM 充实:从 document_chunks 捞含关键词的原文段落做材料,
重写条目 content(200-400字,只用材料内信息,写清机制),UPDATE 回 worldbook_entries。
默认 dry-run;--apply 才写。烧档主 BYOK。

CLI: python -m extract.worldbook_enrich <script_id> --pattern '战姬|神姬|魔导' [--apply]
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

MAX_MATERIAL_CHARS = 10000
MIN_CONTENT = 120
MAX_CONTENT = 500

_SYSTEM = """You are a setting-guide compiler. Using the [Source material], rewrite one worldbook entry and output strict JSON (no fences):
{"content": "About 130-200 words. Explain the setting element: what it is, how it works, its limits / costs / tiers / organization. Use only information found in the material; never invent mechanics beyond it. Third-person setting-guide voice; do not narrate plot."}
Output only this one JSON object."""


def gather_material(db, script_id: int, keyword: str, *, max_chapters: int = 6) -> str:
    """按关键词捞最早+最密的原文段落做材料(设定通常在首次登场与集中说明章)。"""
    rows = db.execute(
        """select chapter_index, count(*) hits from document_chunks
           where script_id=%s and content like %s
           group by chapter_index order by chapter_index asc limit %s""",
        (int(script_id), f"%{keyword}%", int(max_chapters)),
    ).fetchall()
    parts: list[str] = []
    used = 0
    for r in rows or []:
        chunks = db.execute(
            "select content from document_chunks where script_id=%s and chapter_index=%s "
            "and content like %s order by chunk_index limit 3",
            (int(script_id), int(r["chapter_index"]), f"%{keyword}%"),
        ).fetchall()
        for c in chunks or []:
            t = (c.get("content") or "").strip()
            if not t:
                continue
            take = t[: max(0, MAX_MATERIAL_CHARS - used)]
            parts.append(f"[Chapter {r['chapter_index']}] {take}")
            used += len(take)
            if used >= MAX_MATERIAL_CHARS:
                return "\n\n".join(parts)
    return "\n\n".join(parts)


def validate_enriched(raw_text: str) -> str | None:
    if not raw_text:
        return None
    text = raw_text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        data = json.loads(text[s:e + 1])
    except Exception:
        return None
    content = re.sub(r"\s+", " ", str((data or {}).get("content") or "").strip())
    # 字数口径按语种换算:MIN/MAX 按中文字符定,英文同等 token 预算约 2.5x 字符
    from core.token_estimate import cjk_chars_to_budget
    lo = cjk_chars_to_budget(content, MIN_CONTENT)
    hi = cjk_chars_to_budget(content, MAX_CONTENT)
    if not (lo <= len(content) <= hi + 100):
        return None
    return content[:hi]


def enrich_script_worldbook(script_id: int, user_id: int, *, pattern: str,
                            api_id: str | None = None, model: str | None = None,
                            apply: bool = False,
                            should_cancel=None, progress_cb=None) -> dict[str, Any]:
    """命中 pattern 的世界书条目逐条 LLM 重写 content。

    should_cancel: 可选无参回调,返回真值表示用户已请求取消 —— 每条开头检查一次,
      命中即停在条目边界并返回 {"cancelled": True} + 已充实的条目(已 apply 的保留)。
    progress_cb: 可选 (done, total) 回调,每条一次,给 job 进度条用。
    """
    from platform_app.db import connect, init_db
    init_db()
    from agents._harness import call_agent_json_guarded
    from agents.recorder import _resolve_recorder_api_and_model
    rapi, rmodel = _resolve_recorder_api_and_model(user_id, api_id, model)
    if not rapi or not rmodel:
        return {"ok": False, "error": "No usable API/model configured"}
    with connect() as db:
        entries = db.execute(
            "select id, title, content from worldbook_entries "
            "where script_id=%s and title ~ %s order by id",
            (int(script_id), pattern),
        ).fetchall()
    out: list[dict] = []
    cancelled = False
    all_entries = list(entries or [])
    for _i, ent in enumerate(all_entries):
        # 取消检查点:放在每条 LLM 调用之前(每条最多 3 次重试 × 60s,不检查就得干等整批)。
        if should_cancel is not None:
            try:
                if should_cancel():
                    cancelled = True
                    log.info("[worldbook_enrich] script=%s 用户取消,已处理 %d/%d 条",
                             script_id, _i, len(all_entries))
                    break
            except Exception:
                pass  # 取消信号查询失败不该中断正在跑的任务
        # 进度回传放在循环体最前面(done=_i):后面几条分支都有 continue,放末尾会被跳过。
        if progress_cb is not None:
            try:
                progress_cb(_i, len(all_entries))
            except Exception:
                pass
        title = str(ent.get("title") or "")
        # 关键词=标题去分类前缀(「力量·战姬」→「战姬」)
        keyword = (title.split("·")[-1].strip() if "·" in title else title.split(" ")[-1].strip()) or title
        try:
            with connect() as db:
                material = gather_material(db, script_id, keyword)
            if len(material) < 200:
                out.append({"id": ent["id"], "title": title, "status": "skip(not enough material)"})
                continue
            user_p = (f"[Entry name] {title}\n[Current content (too brief, needs fleshing out)] {ent.get('content') or '(empty)'}\n"
                      f"[Source material]\n{material}")
            content = None
            for _attempt in range(3):  # flash 随机性:验收拒最多重试两次
                # 结构化微任务禁深思(268 实锤族)+空正文护栏
                text, _u = call_agent_json_guarded(rapi, rmodel, _SYSTEM, user_p, user_id,
                                                   tool_schema=None, max_tokens=700, timeout_sec=60,
                                                   no_think=True, log_tag="worldbook_enrich")
                content = validate_enriched(text or "")
                if content:
                    break
            if not content:
                out.append({"id": ent["id"], "title": title, "status": "reject(failed validation)"})
                continue
            if apply:
                with connect() as db:
                    db.execute(
                        "update worldbook_entries set content=%s, "
                        "metadata = coalesce(metadata,'{}'::jsonb) || %s::jsonb "
                        "where id=%s and script_id=%s",
                        (content, json.dumps({"enriched": "llm_r5"}, ensure_ascii=False),
                         int(ent["id"]), int(script_id)),
                    )
                    if hasattr(db, "commit"):
                        db.commit()
            out.append({"id": ent["id"], "title": title, "status": "ok",
                        "chars": len(content), "preview": content[:80]})
        except Exception as exc:
            out.append({"id": ent["id"], "title": title, "status": f"fail:{exc}"})
    return {"ok": True, "applied": bool(apply), "entries": out, "cancelled": cancelled}


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("script_id", type=int)
    ap.add_argument("--pattern", required=True, help="标题正则,如 '战姬|神姬|魔导|骑士团|血统'")
    ap.add_argument("--user-id", type=int, default=1)
    ap.add_argument("--api-id", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    print(json.dumps(
        enrich_script_worldbook(a.script_id, a.user_id, pattern=a.pattern,
                                api_id=a.api_id, model=a.model, apply=a.apply),
        ensure_ascii=False, indent=2))
