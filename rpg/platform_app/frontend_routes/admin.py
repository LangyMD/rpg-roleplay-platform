"""platform_app.frontend_routes.admin —— Admin 补充路由(SMTP 测试 + 部署配置)。

原单文件「Admin: SMTP test」段与「Admin: Deployment config」段逐端点搬运,零行为变化:
/api/admin/smtp/test / /api/admin/deployment-config(GET/POST,patch 合并语义)。
"""
from __future__ import annotations

from fastapi import Request

from ..api import json_response, require_user
from ..api._deps import is_admin
from ..db import connect, init_db
from ._shared import _bad, router


# ------------------------------------------------------------
#  Admin: SMTP test (button in DeploySection)
# ------------------------------------------------------------
@router.post("/api/admin/smtp/test")
async def api_admin_smtp_test(request: Request):
    """task 51：FE DeploySection 有「发送测试邮件」按钮但后端从未实现。
    返回明确的"未配置"错误，让 UI 显示真实失败而不是 404 黑洞。

    真正实现需要：读 user_preferences (SMTP host/port/user/pass/from) →
    smtplib.SMTP(host, port).login(user, pass).sendmail(from, to, msg)。
    现在 SMTP 配置还存在 user_preferences 待规范化阶段，先给清晰的占位错误。
    """
    user = require_user(request)
    if not is_admin(user):
        return json_response({"ok": False, "error": "Administrator privileges required"}, status_code=403)
    return json_response({
        "ok": False,
        "error": "SMTP 尚未在 user_preferences 中规范化存储 · 请先在「部署 → 邮件 SMTP」配置并保存",
        "configured": False,
    }, status_code=503)


# ------------------------------------------------------------
#  Admin: Deployment config (SMTP, CORS, listen addr, CAPTCHA…)
# ------------------------------------------------------------
_DEPLOY_CFG_KEY = "admin.deployment_config"


@router.get("/api/admin/deployment-config")
async def api_admin_deployment_config_get(request: Request):
    """读取管理员部署配置（存于 app_config 表）。需要重启才能生效。"""
    user = require_user(request)
    if not is_admin(user):
        return json_response({"ok": False, "error": "Administrator privileges required"}, status_code=403)
    init_db()
    with connect() as db:
        row = db.execute(
            "select value from app_config where key = %s", (_DEPLOY_CFG_KEY,)
        ).fetchone()
    cfg = dict(row["value"]) if row else {}
    return json_response({"ok": True, "config": cfg})


@router.post("/api/admin/deployment-config")
async def api_admin_deployment_config_set(request: Request):
    """保存管理员部署配置（SMTP / CORS / 监听地址 / CAPTCHA）到 app_config。

    采用 patch 合并语义：只更新 body 中出现的键，不影响其他键。
    注意：listen_address / cors_origins 等网络级配置需要重启服务才能生效。
    """
    from psycopg.types.json import Jsonb

    user = require_user(request)
    if not is_admin(user):
        return json_response({"ok": False, "error": "Administrator privileges required"}, status_code=403)
    body = await request.json() or {}
    if not isinstance(body, dict):
        return _bad("请求体必须是对象")
    init_db()
    with connect() as db:
        row = db.execute(
            "select value from app_config where key = %s", (_DEPLOY_CFG_KEY,)
        ).fetchone()
        existing = dict(row["value"]) if row else {}
        merged = {**existing, **body}
        db.execute(
            """
            insert into app_config(key, value)
            values (%s, %s)
            on conflict(key) do update set value = excluded.value, updated_at = now()
            """,
            (_DEPLOY_CFG_KEY, Jsonb(merged)),
        )
    return json_response({"ok": True, "config": merged,
                          "note": "listen_address / cors_origins 等网络配置需重启服务才能生效"})
