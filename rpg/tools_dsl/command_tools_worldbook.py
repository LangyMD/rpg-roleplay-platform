"""
command_tools_worldbook.py — task 107H: save 级世界书 overlay 工具。

三个工具:
  worldbook_add(save_id, title, content, keys=[], priority=50)
    scope=save, destructive=false
    插入 save_worldbook_overlays kind='addition'

  worldbook_retire(save_id, base_entry_id, reason)
    scope=save, destructive=true
    验证 base_entry_id 属于 save 的 script_id,
    插入 save_worldbook_overlays kind='retirement'

  worldbook_list_save_overlay(save_id)
    scope=user (只需 save_id,不需要 state),destructive=false
    返回 {additions: [...], retirements: [...]}

设计原则: 剧本 worldbook_entries 只来自导入,运行时永远不修改。
overlay 表仅支持 addition + retirement 两种 kind。
"""
from __future__ import annotations

import json
from typing import Any

from tools_dsl.command_dispatcher import ToolSpec, get_registry

# ────────────────────────────────────────────────────────────
# Origin 集合
# ────────────────────────────────────────────────────────────

# addition: 允许 LLM (llm_chat/llm_chat_json_op/llm_set) 和 UI/console — 非破坏性写入
_ADD_ORIGINS = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat", "llm_chat_json_op", "console_assistant",
})

# retirement: 破坏性 (标记剧本 entry 不再激活)，禁 llm_chat 裸调；
# llm_chat_json_op 是 GM 结构化协议,允许
_RETIRE_ORIGINS = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat_json_op", "console_assistant",
})

# list: 全部 origin 均可读 (含 llm_chat)
_LIST_ORIGINS = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat", "llm_chat_json_op", "console_assistant",
})


# ────────────────────────────────────────────────────────────
# Executors
# ────────────────────────────────────────────────────────────


def _t_worldbook_add(state: Any, args: dict) -> str:
    """向当前 save 的世界书 overlay 新增一条 addition。"""
    title = (args.get("title") or "").strip()
    if not title:
        return "Failed: title must not be empty"
    content = (args.get("content") or "").strip()
    if not content:
        return "Failed: content must not be empty"

    keys = args.get("keys") or []
    if not isinstance(keys, list):
        keys = []
    keys = [str(k).strip() for k in keys if str(k).strip()]

    try:
        priority = int(args.get("priority") or 50)
    except (TypeError, ValueError):
        priority = 50

    # introduced_turn 来自 state.data["turn"]
    turn = int(state.data.get("turn") or 0)

    # save_id: 优先从 args 获取（调用方应传入），回退从 state._save_id 或 state.data
    save_id = args.get("save_id") or getattr(state, "_save_id", None) or state.data.get("save_id")
    if not save_id:
        return "Failed: save_id not provided (pass save_id in args)"
    try:
        save_id = int(save_id)
    except (TypeError, ValueError):
        return "Failed: save_id must be an integer"

    try:
        from psycopg.types.json import Jsonb

        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            row = db.execute(
                """
                insert into save_worldbook_overlays
                  (save_id, kind, title, content, keys, priority, introduced_turn)
                values (%s, 'addition', %s, %s, %s, %s, %s)
                returning id
                """,
                (save_id, title, content, Jsonb(keys), priority, turn),
            ).fetchone()
        new_id = row["id"]
        return f"Added worldbook entry #{new_id}: {title}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_worldbook_retire(state: Any, args: dict) -> str:
    """将剧本 worldbook_entries 中的某条 entry 标记为在本 save 后续 turn 不再激活。"""
    base_entry_id = args.get("base_entry_id")
    reason = (args.get("reason") or "").strip()

    if base_entry_id is None:
        return "Failed: base_entry_id is required"
    try:
        base_entry_id = int(base_entry_id)
    except (TypeError, ValueError):
        return "Failed: base_entry_id must be an integer"
    if not reason:
        return "Failed: reason must not be empty"

    turn = int(state.data.get("turn") or 0)

    save_id = args.get("save_id") or getattr(state, "_save_id", None) or state.data.get("save_id")
    if not save_id:
        return "Failed: save_id not provided (pass save_id in args)"
    try:
        save_id = int(save_id)
    except (TypeError, ValueError):
        return "Failed: save_id must be an integer"

    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            # 1) 验证 base_entry_id 存在且属于 save 的 script_id
            save_row = db.execute(
                "select script_id from game_saves where id = %s",
                (save_id,),
            ).fetchone()
            if not save_row:
                return f"Failed: save_id={save_id} not found"
            script_id = save_row["script_id"]

            entry_row = db.execute(
                "select id from worldbook_entries where id = %s and script_id = %s",
                (base_entry_id, script_id),
            ).fetchone()
            if not entry_row:
                return (
                    f"Failed: worldbook_entries #{base_entry_id} does not exist or does not belong to"
                    f" script_id={script_id}"
                )

            # 2) 检查是否已经有 retirement overlay（避免重复）
            existing = db.execute(
                "select id from save_worldbook_overlays "
                "where save_id = %s and kind = 'retirement' and retired_entry_id = %s",
                (save_id, base_entry_id),
            ).fetchone()
            if existing:
                return (
                    f"Already exists: worldbook_entries #{base_entry_id} already has a retirement overlay"
                    f" in save #{save_id} (id={existing['id']})"
                )

            # 3) 插入 retirement
            db.execute(
                """
                insert into save_worldbook_overlays
                  (save_id, kind, retired_entry_id, retired_reason, introduced_turn)
                values (%s, 'retirement', %s, %s, %s)
                returning id
                """,
                (save_id, base_entry_id, reason, turn),
            ).fetchone()
        return f"Retired script worldbook entry #{base_entry_id}: {reason}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_worldbook_list_save_overlay(user_id: int, args: dict) -> str:
    """列出某 save 的所有 worldbook overlay (additions + retirements)。"""
    save_id = args.get("save_id")
    if save_id is None:
        return "Failed: save_id is required"
    try:
        save_id = int(save_id)
    except (TypeError, ValueError):
        return "Failed: save_id must be an integer"

    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            # 验证 save 属于当前 user（安全检查）
            save_row = db.execute(
                "select id from game_saves where id = %s and user_id = %s",
                (save_id, user_id),
            ).fetchone()
            if not save_row:
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"

            rows = db.execute(
                """
                select id, kind, title, content, keys, priority,
                       retired_entry_id, retired_reason, introduced_turn
                from save_worldbook_overlays
                where save_id = %s
                order by id asc
                """,
                (save_id,),
            ).fetchall() or []

        additions = []
        retirements = []
        for r in rows:
            r = dict(r)  # type: ignore[assignment]
            if r["kind"] == "addition":
                additions.append({
                    "id": r["id"],
                    "title": r["title"],
                    "content": (r["content"] or "")[:80],
                    "keys": r["keys"] or [],
                    "priority": r["priority"],
                    "introduced_turn": r["introduced_turn"],
                })
            elif r["kind"] == "retirement":
                retirements.append({
                    "id": r["id"],
                    "retired_entry_id": r["retired_entry_id"],
                    "retired_reason": r["retired_reason"],
                    "introduced_turn": r["introduced_turn"],
                })

        return json.dumps(
            {"additions": additions, "retirements": retirements},
            ensure_ascii=False,
            default=str,
            indent=2,
        )
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────
# 注册
# ────────────────────────────────────────────────────────────


def register_worldbook_tools() -> None:
    """注册三个 worldbook overlay 工具到全局 registry。幂等。"""
    registry = get_registry()

    # 1) worldbook_add — save 级, non-destructive
    if not registry.has("worldbook_add"):
        registry.register(ToolSpec(
            name="worldbook_add",
            description=(
                "Add an addition entry to the current save's worldbook overlay.\n"
                "Only for new lore the player/GM discovered during the story (content the script's worldbook_entries do not have).\n"
                "Does not modify the script's original data; applies only to this save.\n"
                "keys is the list of trigger keywords; priority defaults to 50."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Save id"},
                    "title": {"type": "string", "description": "Entry title; must not be empty"},
                    "content": {"type": "string", "description": "Entry body"},
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of trigger keywords (may be empty)",
                        "default": [],
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Priority, default 50; >= 90 is treated as forced insertion",
                        "default": 50,
                    },
                },
                "required": ["save_id", "title", "content"],
            },
            executor=_t_worldbook_add,
            scope="save",
            origins=_ADD_ORIGINS,
            destructive=False,
        ))

    # 2) worldbook_retire — save 级, destructive
    if not registry.has("worldbook_retire"):
        registry.register(ToolSpec(
            name="worldbook_retire",
            description=(
                "Mark an entry of the script's worldbook_entries as no longer active in later turns of this save.\n"
                "Typical uses: an NPC dies, a location is destroyed, a piece of lore is overturned.\n"
                "base_entry_id must be a worldbook_entries.id belonging to the script this save is bound to.\n"
                "reason briefly explains why it is retired (e.g. 'character died turn 12').\n"
                "Irreversible (restorable only by deleting the DB row manually); llm_chat may not call it directly."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Save id"},
                    "base_entry_id": {
                        "type": "integer",
                        "description": "The worldbook_entries.id to retire",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for retiring it (e.g. 'NPC died turn 47')",
                    },
                },
                "required": ["save_id", "base_entry_id", "reason"],
            },
            executor=_t_worldbook_retire,
            scope="save",
            origins=_RETIRE_ORIGINS,
            destructive=True,
        ))

    # 3) worldbook_list_save_overlay — user 级 (只需 save_id), read-only
    if not registry.has("worldbook_list_save_overlay"):
        registry.register(ToolSpec(
            name="worldbook_list_save_overlay",
            description=(
                "List all worldbook overlay entries of the given save.\n"
                "Returns {additions: [...], retirements: [...]}.\n"
                "Each addition has id/title/content (first 80 characters)/keys/priority/introduced_turn;\n"
                "each retirement has id/retired_entry_id/retired_reason/introduced_turn."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Save id"},
                },
                "required": ["save_id"],
            },
            executor=_t_worldbook_list_save_overlay,
            scope="user",
            origins=_LIST_ORIGINS,
            destructive=False,
        ))


__all__ = ["register_worldbook_tools"]
