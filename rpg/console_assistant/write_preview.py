"""console_assistant.write_preview — 写库工具确认弹窗的「改动预览」。

写作搭档 agent 对剧本知识资产(章节正文 / 世界书 / 人物卡 / 锚点 / canon)落库前要二次确认。
此前确认弹窗只显示原始 args(JSON),作者看不清「到底改了什么」。本模块在确认前计算一份
before→after 预览:章节正文给真·前后全文(供前端做 diff / 对照),其余结构化写给「将写入的字段」。

只读;失败一律返回 None(预览缺失绝不阻断确认流程)。供 llm_loop 在 needs_confirm 时调用。
"""
from __future__ import annotations

import json
from typing import Any

# 单字段最大预览长度(章节正文可达上万字;截断只为载荷护栏,diff 仍以截断文本为准并标注)。
_MAX_FIELD = 16000


def _clip(text: str) -> tuple[str, bool]:
    s = str(text or "")
    if len(s) <= _MAX_FIELD:
        return s, False
    return s[:_MAX_FIELD], True


def build_write_preview(
    tool_name: str, args: dict[str, Any] | None, user_id: int | None, script_id: int | None
) -> dict[str, Any] | None:
    """返回 {kind,label,before?,after,truncated?,is_new?} 或 None(无预览,退回原始 args 展示)。"""
    args = dict(args or {})
    try:
        if tool_name == "update_script_chapter":
            return _preview_chapter(args, script_id)
        if tool_name in ("upsert_worldbook_entry", "upsert_worldbook_entries",
                         "update_npc_card", "upsert_canon_entity",
                         "update_anchor", "create_anchor"):
            return _preview_structured(tool_name, args)
    except Exception:
        return None
    return None


def _preview_chapter(args: dict[str, Any], script_id: int | None) -> dict[str, Any] | None:
    try:
        ci = int(args.get("chapter_index"))
    except (TypeError, ValueError):
        return None
    new_content = args.get("content")
    if new_content is None:
        return None  # 只改标题等非正文改动 → 不做正文 diff(退回原始 args 展示)
    cur_title, cur_content, is_new = "", "", True
    if script_id:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            row = db.execute(
                "select title, content from script_chapters where script_id=%s and chapter_index=%s",
                (int(script_id), ci),
            ).fetchone()
        if row:
            is_new = False
            cur_title = str(row.get("title") or "")
            cur_content = str(row.get("content") or "")
    before, b_trunc = _clip(cur_content)
    after, a_trunc = _clip(str(new_content))
    new_title = str(args.get("title") or "").strip()
    label = f"Chapter {ci} {new_title or cur_title}".strip()
    return {
        "kind": "chapter",
        "label": label,
        "before": before,
        "after": after,
        "before_chars": len(cur_content),
        "after_chars": len(str(new_content)),
        "truncated": b_trunc or a_trunc,
        "is_new": is_new,
    }


_STRUCT_KIND = {
    "upsert_worldbook_entry": "worldbook",
    "upsert_worldbook_entries": "worldbook",
    "update_npc_card": "npc",
    "upsert_canon_entity": "canon",
    "update_anchor": "anchor",
    "create_anchor": "anchor",
}

_STRUCT_LABEL_KEYS = ("title", "name", "keyword", "logical_key", "story_time_label", "full_name")


def _preview_structured(tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """结构化写:展示「将写入的字段」(after),供作者落库前核对。不读当前值(字段语义各异、
    key 解析复杂),只把 agent 提议的字段整理成可读 after —— 前端无 before 时按「将写入」渲染。"""
    fields = {k: v for k, v in args.items() if v not in (None, "", [], {})}
    if not fields:
        return None
    label_val = next((str(args.get(k)) for k in _STRUCT_LABEL_KEYS if args.get(k)), "")
    after, trunc = _clip(json.dumps(fields, ensure_ascii=False, indent=2))
    return {
        "kind": _STRUCT_KIND.get(tool_name, "structured"),
        "label": label_val,
        "after": after,
        "truncated": trunc,
        "is_new": tool_name == "create_anchor",
    }
