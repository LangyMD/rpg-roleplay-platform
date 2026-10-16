"""skills.py — Skill 导入与运行路由 (/api/skills/*)。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from platform_app.api._deps import json_response
from routes._deps_fastapi import get_current_admin_strict
from schemas._common import COMMON_ERROR_RESPONSES, ErrorResponse, GenericOkResponse
from schemas.skills import SkillRunRequest, SkillsImportRequest

router = APIRouter()


@router.post("/api/skills/import", response_model=GenericOkResponse, responses=COMMON_ERROR_RESPONSES)
async def api_skills_import(
    body: SkillsImportRequest,
    api_user: dict[str, Any] | None = Depends(get_current_admin_strict),
) -> JSONResponse:
    from app import import_skill_bundle, tool_payload
    body_dict = body.model_dump(exclude_none=True)
    try:
        skill = import_skill_bundle(body_dict.get("file", {}))
        return json_response({"ok": True, "skill": skill, "tools": tool_payload()})
    except (PermissionError, ValueError) as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/api/skills/{skill_id}/run", response_model=GenericOkResponse, responses={**COMMON_ERROR_RESPONSES, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def api_skill_run(
    body: SkillRunRequest,
    skill_id: str,
    api_user: dict[str, Any] = Depends(get_current_admin_strict),
) -> JSONResponse:
    """在沙箱里跑某个 imported skill。

    Body: {"cmd": ["bash", "script.sh", "arg1"], "stdin": "...", "timeout_sec": 30}

    安全：admin only。local 模式下也强制要求 admin —— 不再做匿名豁免，避免
    "本地未鉴权 + cmd 可任意" 的 RCE 链。必须用 get_current_admin_strict:普通
    get_current_admin 在 local 模式会短路放行(含 user=None),等于没有鉴权。
    import 同理(导入 = 落盘可执行脚本)。与 routes/mcp.py 同一闸。
    """
    body_dict = body.model_dump(exclude_none=True)
    cmd = body_dict.get("cmd") or body_dict.get("command")
    if not isinstance(cmd, list) or not cmd:
        return json_response({"ok": False, "error": "cmd must be a non-empty list"}, status_code=400)
    if not all(isinstance(x, str) for x in cmd):
        return json_response({"ok": False, "error": "All cmd elements must be strings"}, status_code=400)
    if len(cmd) > 64 or any(len(x) > 4096 for x in cmd):
        return json_response({"ok": False, "error": "cmd element or length exceeds the limit"}, status_code=400)

    # P0-1 SEC: cmd[0] 白名单 + 路径穿越防御
    _CMD_WHITELIST = {"bash", "sh", "python3", "python", "node", "ruby"}
    cmd0 = cmd[0]
    if "/" in cmd0:
        return json_response({"ok": False, "error": "cmd[0] cannot contain /; it must be a bare file name"}, status_code=400)
    if cmd0 not in _CMD_WHITELIST:
        return json_response({"ok": False, "error": f"cmd[0] must be in the allowlist: {sorted(_CMD_WHITELIST)}"}, status_code=400)
    if any(".." in part for part in cmd):
        return json_response({"ok": False, "error": "cmd elements cannot contain .."}, status_code=400)

    # 找 skill_id 对应的目录
    from tools_dsl.tool_registry import list_imported_skills
    skill = next((s for s in list_imported_skills() if s.get("id") == skill_id), None)
    if not skill:
        return json_response({"ok": False, "error": f"Skill not found: {skill_id}"}, status_code=404)
    skill_path = skill.get("path") or ""
    if not skill_path:
        return json_response({"ok": False, "error": "Skill path is missing"}, status_code=500)

    # 找 skill 根目录（SKILL.md 的父目录）
    from pathlib import Path as _Path
    skill_root = _Path(skill_path).parent

    import skill_executor
    result = skill_executor.run_skill_command(
        cmd=cmd,
        skill_root=skill_root,
        timeout_sec=int(body_dict.get("timeout_sec") or skill_executor.DEFAULT_TIMEOUT_SEC),
        stdin_text=body_dict.get("stdin"),
    )
    return json_response({"ok": True, **result})
