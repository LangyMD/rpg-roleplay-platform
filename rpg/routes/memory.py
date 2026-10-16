"""memory.py — 记忆管理路由。

包含：
  POST /api/memory/add    — 添加记忆条目
  POST /api/memory/remove — 删除记忆条目
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from platform_app.api._deps import json_response
from routes._deps_fastapi import get_current_user
from schemas._common import COMMON_ERROR_RESPONSES, StateResponse
from schemas.memory import (
    MemoryAddRequest,
    MemoryRemoveRequest,
    MemoryUpdateRequest,
)

router = APIRouter()


@router.post("/api/memory/add", response_model=StateResponse, responses=COMMON_ERROR_RESPONSES)
async def api_memory_add(
    body: MemoryAddRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """task 87 Phase 6: 走 dispatcher 的 add_memory_* 工具系列。"""
    from app import (
        _ensure_loaded,
        _payload,
        _persist_runtime_checkpoint,
        _resolve_persist_target,
    )
    body_dict = body.model_dump(exclude_none=True)
    state = _ensure_loaded(api_user)
    bucket = body_dict.get("bucket", "notes")
    text = body_dict.get("text", "")

    # A6: pinned_max 校验 — 添加 pinned 条目时检查上限
    if bucket == "pinned" and api_user:
        from platform_app.settings import get_memory_settings
        ms = get_memory_settings(int(api_user.get("id", 0)))
        current_pinned = state.data.get("memory", {}).get("pinned", [])
        if len(current_pinned) >= ms.pinned_max:
            return json_response(
                {
                    "ok": False,
                    "error": f"Pinned memory limit reached ({ms.pinned_max} entries); delete old entries before adding new ones",
                },
                status_code=400,
            )

    # bucket → 对应工具名
    bucket_tool = {
        "facts": "add_memory_fact",
        "resources": "add_memory_resource",
        "abilities": "add_memory_ability",
        "pinned": "pin_memory",
        "notes": "add_memory_note",
    }.get(bucket, "add_memory_note")
    from tools_dsl.ui_dispatch_helper import dispatch_ui_tool
    result = dispatch_ui_tool(
        tool_name=bucket_tool,
        args={"text": text},
        user_id=int(api_user.get("id")) if api_user else 0,
        save_id=_resolve_persist_target(api_user)[1] or 0,
        state=state,
    )
    if not result.ok:
        return json_response({"ok": False, "error": result.error}, status_code=400)
    state.save()
    _persist_runtime_checkpoint(state, api_user)
    return json_response({"ok": True, "state": _payload(api_user)})


@router.post("/api/memory/update", response_model=StateResponse, responses=COMMON_ERROR_RESPONSES)
async def api_memory_update(
    body: MemoryUpdateRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """就地编辑一条玩家记忆/笔记(原来只能删了重加 —— 群反馈 行者无疆「玩家日记直接编辑」)。
    只动玩家可手编的桶(notes/pinned/facts/resources/abilities),按 index 替换该条文本。"""
    from app import _ensure_loaded, _payload, _persist_runtime_checkpoint
    body_dict = body.model_dump(exclude_none=True)
    bucket = body_dict.get("bucket", "notes")
    index = body_dict.get("index")
    text = (body_dict.get("text") or "").strip()
    if index is None or not isinstance(index, int) or index < 0:
        return json_response({"ok": False, "error": "index must be a non-negative integer"}, status_code=400)
    if not text:
        return json_response({"ok": False, "error": "Content cannot be empty"}, status_code=400)
    if bucket not in {"notes", "pinned", "facts", "resources", "abilities"}:
        return json_response({"ok": False, "error": "This memory bucket cannot be edited"}, status_code=400)
    state = _ensure_loaded(api_user)
    items = state.data.setdefault("memory", {}).setdefault(bucket, [])
    if index >= len(items):
        return json_response({"ok": False, "error": "Entry not found (it may have been changed; please refresh)"}, status_code=400)
    if not isinstance(items[index], str):
        return json_response({"ok": False, "error": "This entry is not editable text"}, status_code=400)
    # 同步 legacy bucket + 结构化 items(否则 GM 上下文只读 items、看到旧文本)。
    if not state.edit_memory(bucket, index, text):
        return json_response({"ok": False, "error": "Edit failed"}, status_code=400)
    state.save()
    _persist_runtime_checkpoint(state, api_user)
    return json_response({"ok": True, "state": _payload(api_user)})


@router.post("/api/memory/remove", response_model=StateResponse, responses=COMMON_ERROR_RESPONSES)
async def api_memory_remove(
    body: MemoryRemoveRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """task 87 Phase 6: destructive 走 dispatcher remove_memory_item 工具。"""
    from app import (
        _ensure_loaded,
        _payload,
        _persist_runtime_checkpoint,
        _resolve_persist_target,
    )
    body_dict = body.model_dump(exclude_none=True)
    index = body_dict.get("index")
    if index is None or (isinstance(index, int) and index < 0):
        return json_response({"ok": False, "error": "index must be a non-negative integer"}, status_code=400)
    state = _ensure_loaded(api_user)
    from tools_dsl.ui_dispatch_helper import dispatch_ui_tool
    result = dispatch_ui_tool(
        tool_name="remove_memory_item",
        args={
            "bucket": body_dict.get("bucket", "notes"),
            "index": int(index),
        },
        user_id=int(api_user.get("id")) if api_user else 0,
        save_id=_resolve_persist_target(api_user)[1] or 0,
        state=state,
    )
    if not result.ok:
        return json_response({"ok": False, "error": result.error}, status_code=400)
    state.save()
    _persist_runtime_checkpoint(state, api_user)
    return json_response({"ok": True, "state": _payload(api_user)})
