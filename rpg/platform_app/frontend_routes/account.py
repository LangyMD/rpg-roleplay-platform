"""platform_app.frontend_routes.account —— ACCOUNT lifecycle 路由(/api/account/*)。

原单文件「ACCOUNT lifecycle」段逐端点搬运,零行为变化:
LC-05 数据导出(GET/POST)/ LC-01 软停用 / 硬删申请(30 天宽限)/ 撤销硬删 /
删除状态查询 / 旧 delete 兼容端点。
"""
from __future__ import annotations

import io
import json

from fastapi import Request
from fastapi.responses import StreamingResponse

from ..api import _client_ip, _delete_session_cookie, json_response, require_user
from ..db import connect, init_db
from ._shared import _bad, router

# ------------------------------------------------------------
#  ACCOUNT lifecycle
# ------------------------------------------------------------

# LC-05: /api/account/export — 同步返回完整用户数据 JSON.
# 若 B12 邮件 util 落地后可改为异步任务+邮件发链接；当前同步 stream 返回 zip。
@router.get("/api/account/export")
async def api_account_export(request: Request):
    """返回当前用户全量数据，JSON 格式，作为可下载文件（LC-05）."""
    import zipfile

    user = require_user(request)
    uid = user["id"]
    init_db()

    with connect() as db:
        # 用户基本信息
        u_row = db.execute(
            "select id, username, email, created_at, updated_at, deactivated_at, public_id from users where id = %s",
            (uid,),
        ).fetchone()
        pe_row = db.execute("select * from profile_extras where user_id = %s", (uid,)).fetchone()
        prefs_row = db.execute("select preferences from user_preferences where user_id = %s", (uid,)).fetchone()

        # 存档 / 角色卡
        saves = db.execute(
            "select id, title, created_at, updated_at, last_played_at from game_saves where user_id = %s order by updated_at desc",
            (uid,),
        ).fetchall()
        save_ids = [s["id"] for s in saves]

        # branch_commits（属于用户存档）
        commits: list = []
        for sid in save_ids:
            rows = db.execute(
                "select id, save_id, turn_index, kind, title, message, created_at from branch_commits where save_id = %s order by turn_index",
                (sid,),
            ).fetchall()
            commits.extend(rows)

        cards = db.execute(
            "select id, name, card_type, source, created_at from character_cards where user_id = %s",
            (uid,),
        ).fetchall()

        # 用量 / 审计
        usage = db.execute(
            "select id, api_id, model_real_name, total_tokens, cost_usd, created_at from token_usage where user_id = %s order by created_at desc limit 1000",
            (uid,),
        ).fetchall()
        audit = db.execute(
            "select id, event, ip, created_at from login_audit where username = %s order by created_at desc limit 500",
            (user.get("username", ""),),
        ).fetchall()

        # 记忆
        memories = db.execute(
            "select id, bucket, content, importance, created_at from memories where user_id = %s order by created_at desc",
            (uid,),
        ).fetchall()

    def _to_list(rows) -> list:
        if rows is None:
            return []
        return [dict(r) for r in rows]

    def _to_dict(row) -> dict:
        return dict(row) if row else {}

    payload = {
        "export_version": "1",
        "user": _to_dict(u_row),
        "profile_extras": _to_dict(pe_row),
        "preferences": _to_dict(prefs_row),
        "game_saves": _to_list(saves),
        "branch_commits": _to_list(commits),
        "character_cards": _to_list(cards),
        "token_usage": _to_list(usage),
        "login_audit": _to_list(audit),
        "memories": _to_list(memories),
    }

    # 序列化 datetime/uuid 对象
    import datetime as _dt
    import uuid as _uuid

    def _default(obj):
        if isinstance(obj, (_dt.datetime, _dt.date)):
            return obj.isoformat()
        if isinstance(obj, _uuid.UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    raw_json = json.dumps(payload, default=_default, ensure_ascii=False, indent=2).encode("utf-8")

    # 打成 zip，方便扩展多文件
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("account_data.json", raw_json)
    buf.seek(0)

    username = user.get("username", str(uid))
    filename = f"account_export_{username}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# LC-05: 兼容 POST（旧版客户端）— 重定向到同步 GET 导出
@router.post("/api/account/export")
async def api_account_export_post(request: Request):
    """POST 兼容层：直接调同步导出逻辑（LC-05）."""
    return await api_account_export(request)


# LC-01: 软停用（可恢复）
@router.post("/api/account/deactivate")
async def api_account_deactivate(request: Request):
    """软停用账号（可恢复）。立刻置 deactivated_at，注销所有 session。"""
    user = require_user(request)
    init_db()
    with connect() as db:
        db.execute(
            "update users set deactivated_at = now(), updated_at = now() where id = %s",
            (user["id"],),
        )
        db.execute("delete from sessions where user_id = %s", (user["id"],))
    return json_response({"ok": True})


# LC-01: 硬删请求（30 天宽限期）
@router.post("/api/account/request-delete")
async def api_account_request_delete(request: Request):
    """申请硬删账号，写入 account_delete_queue，30 天后由 cron 物理删除（LC-01）."""
    user = require_user(request)
    body: dict = {}
    try:
        body = await request.json() or {}
    except Exception:
        pass
    reason = body.get("reason", "user-requested")
    ip = _client_ip(request)
    init_db()
    with connect() as db:
        # 幂等：若已有未完成的队列行，直接返回现有计划时间
        existing = db.execute(
            "select scheduled_hard_delete_at from account_delete_queue where user_id = %s and completed_at is null",
            (user["id"],),
        ).fetchone()
        if existing:
            return json_response({
                "ok": True,
                "scheduled_hard_delete_at": existing["scheduled_hard_delete_at"].isoformat()
                if hasattr(existing["scheduled_hard_delete_at"], "isoformat")
                else str(existing["scheduled_hard_delete_at"]),
                "message": "A deletion request already exists; it can be cancelled within the 30-day grace period",
            })

        db.execute(
            """
            insert into account_delete_queue
              (user_id, requested_at, scheduled_hard_delete_at, requested_by_ip, reason)
            values
              (%s, now(), now() + interval '30 days', %s, %s)
            on conflict (user_id) do update
              set requested_at = now(),
                  scheduled_hard_delete_at = now() + interval '30 days',
                  requested_by_ip = excluded.requested_by_ip,
                  reason = excluded.reason,
                  completed_at = null
            """,
            (user["id"], ip, reason),
        )
        # 立刻停用，用户不能再登录
        db.execute(
            "update users set deactivated_at = now(), updated_at = now() where id = %s",
            (user["id"],),
        )
        db.execute("delete from sessions where user_id = %s", (user["id"],))
        row = db.execute(
            "select scheduled_hard_delete_at from account_delete_queue where user_id = %s",
            (user["id"],),
        ).fetchone()

    sched = row["scheduled_hard_delete_at"] if row else None
    sched_str = sched.isoformat() if hasattr(sched, "isoformat") else str(sched)

    # TODO(B12): 发邮件确认 + 30 天倒计时链接（B12 邮件 util 落地后接入）

    resp = json_response({
        "ok": True,
        "scheduled_hard_delete_at": sched_str,
        "message": "Deletion request submitted; it can be cancelled within 30 days. To cancel, call /api/account/cancel-delete.",
    })
    _delete_session_cookie(resp, request)
    return resp


# LC-01: 撤销硬删（宽限期内）
@router.post("/api/account/cancel-delete")
async def api_account_cancel_delete(request: Request):
    """在 30 天宽限期内撤销硬删请求（LC-01）。需要用户仍能通过 session 鉴权。"""
    user = require_user(request)
    init_db()
    with connect() as db:
        queue_row = db.execute(
            "select user_id from account_delete_queue where user_id = %s and completed_at is null",
            (user["id"],),
        ).fetchone()
        if not queue_row:
            return _bad("No deletion request in progress, or the grace period has passed", 404)
        # 撤销：删队列行 + 清 deactivated_at
        db.execute("delete from account_delete_queue where user_id = %s", (user["id"],))
        db.execute(
            "update users set deactivated_at = null, updated_at = now() where id = %s",
            (user["id"],),
        )
    return json_response({"ok": True, "message": "Deletion request cancelled; the account is back to normal."})


# LC-01: 查询删除状态
@router.get("/api/account/delete-status")
async def api_account_delete_status(request: Request):
    """查询当前账号删除状态（none / soft-deactivated / hard-pending）（LC-01）."""
    user = require_user(request)
    init_db()
    with connect() as db:
        u_row = db.execute(
            "select deactivated_at from users where id = %s",
            (user["id"],),
        ).fetchone()
        queue_row = db.execute(
            "select scheduled_hard_delete_at, requested_at from account_delete_queue where user_id = %s and completed_at is null",
            (user["id"],),
        ).fetchone()

    deactivated_at = u_row["deactivated_at"] if u_row else None

    if queue_row:
        sched = queue_row["scheduled_hard_delete_at"]
        return json_response({
            "status": "hard-pending",
            "scheduled_hard_delete_at": sched.isoformat() if hasattr(sched, "isoformat") else str(sched),
            "requested_at": queue_row["requested_at"].isoformat() if hasattr(queue_row["requested_at"], "isoformat") else str(queue_row["requested_at"]),
        })
    if deactivated_at:
        return json_response({
            "status": "soft-deactivated",
            "deactivated_at": deactivated_at.isoformat() if hasattr(deactivated_at, "isoformat") else str(deactivated_at),
        })
    return json_response({"status": "none"})


# 保留旧 /api/account/delete 端点（向后兼容），行为等同 request-delete
@router.post("/api/account/delete")
async def api_account_delete(request: Request):
    """已废弃，保留向后兼容。等同于 /api/account/request-delete（30 天宽限期）."""
    return await api_account_request_delete(request)
