"""
command_tools_phase.py — task 107C

Phase management command tools:
  phase_list    — list all phase digests for a save
  phase_advance — manually open a new phase
  phase_rebuild — mark a phase as needing re-digest (107D placeholder)

Registered in command_tools_register.ensure_registered().
"""
from __future__ import annotations

import json

from tools_dsl._arg_guards import require_int_arg
from tools_dsl.command_dispatcher import ToolSpec, get_registry

# Origins: console_assistant + ui_button + api_direct
# (LLM free-chat should not spontaneously advance phases)
_PHASE_READ_ORIGINS = frozenset({"ui_button", "api_direct", "console_assistant", "llm_chat", "llm_set"})
_PHASE_MUTATE_ORIGINS = frozenset({"ui_button", "api_direct", "console_assistant"})


# ────────────────────────────────────────────────────────────
# Tool executors
# ────────────────────────────────────────────────────────────


def _t_phase_list(user_id: int, args: dict) -> str:
    """List all save_phase_digests for the given save_id."""
    save_id = args.get("save_id")
    _chk = require_int_arg(save_id, "save_id")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id)
    try:
        from platform_app.db import connect, init_db

        init_db()
        with connect() as db:
            # Verify ownership
            own = db.execute(
                "select 1 from game_saves where id = %s and user_id = %s",
                (save_id, user_id),
            ).fetchone()
            if not own:
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
            rows = db.execute(
                """
                select phase_index, phase_label, turn_start, turn_end,
                       story_time_label, status, summary
                  from save_phase_digests
                 where save_id = %s
                 order by phase_index asc
                """,
                (save_id,),
            ).fetchall() or []
        result = []
        for r in rows:
            summary = (r.get("summary") or "")[:80]
            result.append({
                "phase_index": r["phase_index"],
                "phase_label": r.get("phase_label") or "",
                "turn_start": r.get("turn_start"),
                "turn_end": r.get("turn_end"),
                "story_time_label": r.get("story_time_label") or "",
                "status": r.get("status") or "open",
                "summary": summary + ("..." if len(r.get("summary") or "") > 80 else ""),
            })
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_phase_advance(user_id: int, args: dict) -> str:
    """Manually open a new phase for the given save_id."""
    save_id = args.get("save_id")
    _chk = require_int_arg(save_id, "save_id")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id)
    label = (args.get("label") or "").strip()
    try:
        from platform_app.db import connect, init_db

        init_db()
        with connect() as db:
            own = db.execute(
                "select 1 from game_saves where id = %s and user_id = %s",
                (save_id, user_id),
            ).fetchone()
            if not own:
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
            # Get current turn from the latest branch_commit for this save
            row = db.execute(
                "select turn_index from branch_commits where save_id = %s order by id desc limit 1",
                (save_id,),
            ).fetchone()
        turn_index = int((row or {}).get("turn_index") or 0)

        from save_phase_manager import open_new_phase

        new_phase = open_new_phase(
            save_id=save_id,
            turn_index=turn_index,
            phase_label=label,
            story_time_label="",
        )
        new_index = new_phase.get("phase_index", "?")
        return f"phase_advance: new phase {new_index} opened (turn={turn_index}, label={label or '(not set)'})"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_phase_rebuild(user_id: int, args: dict) -> str:
    """Mark a phase as needing re-digest (metadata.needs_rebuild=true).

    Real LLM re-digest is implemented in 107D. This tool only flags the row
    so 107D can pick it up.
    """
    save_id = args.get("save_id")
    phase_index = args.get("phase_index")
    _chk = require_int_arg(save_id, "save_id")
    if isinstance(_chk, str):
        return _chk
    _chk = require_int_arg(phase_index, "phase_index")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id)
    phase_index = int(phase_index)
    try:
        from psycopg.types.json import Jsonb

        from platform_app.db import connect, init_db

        init_db()
        with connect() as db:
            own = db.execute(
                "select 1 from game_saves where id = %s and user_id = %s",
                (save_id, user_id),
            ).fetchone()
            if not own:
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
            row = db.execute(
                "select id, metadata from save_phase_digests where save_id = %s and phase_index = %s",
                (save_id, phase_index),
            ).fetchone()
            if not row:
                return f"Failed: phase_index={phase_index} does not exist (save_id={save_id})"
            meta = dict(row.get("metadata") or {})
            meta["needs_rebuild"] = True
            db.execute(
                "update save_phase_digests set metadata = %s, updated_at = now() "
                "where save_id = %s and phase_index = %s",
                (Jsonb(meta), save_id, phase_index),
            )
        return f"phase_rebuild: phase {phase_index} marked needs_rebuild=true (save_id={save_id})"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────
# Registration
# ────────────────────────────────────────────────────────────


def register_phase_tools() -> None:
    """Register phase management tools into the global registry."""
    registry = get_registry()

    specs = [
        ToolSpec(
            name="phase_list",
            description=(
                "List all phase summary segments of the given save (save_id), "
                "with phase_index / phase_label / turn range / status / the first 80 characters of the summary. "
                "Use it to review the story's segment history."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                },
                "required": ["save_id"],
            },
            executor=_t_phase_list,
            scope="user",
            origins=_PHASE_READ_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="phase_advance",
            description=(
                "Manually open a new phase for the given save (without waiting for the automatic 30-turn detection). "
                "label is optional and becomes the new phase's title."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                    "label": {"type": "string", "description": "New phase label (optional)"},
                },
                "required": ["save_id"],
            },
            executor=_t_phase_advance,
            scope="user",
            origins=_PHASE_MUTATE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="phase_rebuild",
            description=(
                "Mark the given phase as needing its LLM summary regenerated (metadata.needs_rebuild=true). "
                "The actual re-summarization is handled by the 107D background task."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                    "phase_index": {"type": "integer", "description": "Target phase index (0-based)"},
                },
                "required": ["save_id", "phase_index"],
            },
            executor=_t_phase_rebuild,
            scope="user",
            origins=_PHASE_MUTATE_ORIGINS,
            destructive=False,
        ),
    ]

    for spec in specs:
        if not registry.has(spec.name):
            registry.register(spec)


__all__ = ["register_phase_tools"]
