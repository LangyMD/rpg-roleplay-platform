"""platform_app.api.federation — 功能 B 路由。

三类鉴权:
  1. cookie(require_user):PAT 管理 / 设备批准 / 本地连接器(都是已登录用户操作)。
  2. Bearer PAT(require_pat):/api/ext/library/* 外部库读写。
  3. 公开(无鉴权):/api/ext/device/code|token 设备码流(令牌靠 device_code/user_code 自证)。
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote as _quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import federation
from ._deps import _client_ip, json_response, require_user, value_error_response

router = APIRouter()


def _rate_limit(key: str, max_calls: int, window_s: float, detail: str = "请求过于频繁,请稍后再试"):
    if not federation.rate_ok(key, max_calls, window_s):
        raise HTTPException(status_code=429, detail=detail)


def _require_provider() -> None:
    """provider 角色闸:本地客户端实例不暴露签发/批准/外部库端点(防无鉴权令牌签发面)。"""
    if not federation.provider_enabled():
        raise HTTPException(status_code=404, detail="本实例不是在线剧本库提供方")


@router.get("/api/ext/provider-info")
async def api_provider_info():
    """公开:供前端判断本实例是否为在线库提供方(决定是否展示 /device、令牌管理等)。"""
    return json_response({"ok": True, "provider_enabled": federation.provider_enabled(),
                          "base_url": federation.official_base()})


def _same_origin_or_403(request: Request) -> None:
    """state-changing cookie POST 的 CSRF 缓解:Origin/Referer 主机须与本服务一致。

    SameSite=lax 默认已挡跨站 fetch POST;但 SameSite 可被配成 none(跨源 landing),
    故对授权这类敏感操作再加一道同源闸,不单靠 cookie 属性。
    """
    host = (request.url.hostname or "").lower()
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        return  # 同源浏览器 fetch 通常带 Origin;无头/同源 server 调用放行
    from urllib.parse import urlparse
    oh = (urlparse(origin).hostname or "").lower()
    if oh and host and oh != host:
        raise HTTPException(status_code=403, detail="跨源请求被拒绝")


# ── Bearer PAT 依赖 ───────────────────────────────────────────────────────
def _bearer_token(request: Request) -> str:
    h = request.headers.get("authorization") or ""
    if not h.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return h[7:].strip()


def require_pat_read(request: Request) -> dict:
    _require_provider()
    try:
        return federation.verify_pat(_bearer_token(request), required_scope="library:read")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def require_pat_publish(request: Request) -> dict:
    _require_provider()
    try:
        return federation.verify_pat(_bearer_token(request), required_scope="library:publish")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# ════════════════════════════════════════════════════════════════════════
#  PROVIDER:PAT 管理(cookie)
# ════════════════════════════════════════════════════════════════════════
@router.get("/api/me/pat")
async def api_list_pat(user=Depends(require_user)):
    _require_provider()
    return json_response(federation.list_pats(user["id"]))


@router.post("/api/me/pat")
async def api_create_pat(request: Request, user=Depends(require_user)):
    _require_provider()
    body = await request.json()
    name = (body.get("name") or "").strip()
    scopes = body.get("scopes") or ["library:read"]
    ttl = int(body.get("ttl_days") or federation.PAT_DEFAULT_TTL_DAYS)
    return json_response(federation.create_pat(user["id"], name, scopes, ttl))


@router.post("/api/me/pat/{pat_id}/revoke")
async def api_revoke_pat(pat_id: int, user=Depends(require_user)):
    _require_provider()
    return json_response(federation.revoke_pat(user["id"], pat_id))


# ── PROVIDER:设备批准页(cookie)─────────────────────────────────────────
@router.get("/api/me/device/lookup")
async def api_device_lookup(user_code: str, user=Depends(require_user)):
    _require_provider()
    info = federation.device_lookup(user_code)
    if not info:
        return json_response({"ok": False, "error": "Authorization code not found or no longer valid"}, status_code=404)
    return json_response({"ok": True, "device": info})


@router.post("/api/me/device/approve")
async def api_device_approve(request: Request, user=Depends(require_user)):
    _require_provider()
    _same_origin_or_403(request)
    _rate_limit(f"devapprove:{user['id']}", 20, 60)
    body = await request.json()
    deny = bool(body.get("deny"))
    try:
        return json_response(federation.device_approve(user["id"], body.get("user_code") or "", deny=deny))
    except ValueError as exc:
        return value_error_response(exc)


# ════════════════════════════════════════════════════════════════════════
#  PROVIDER:设备码流(公开)
# ════════════════════════════════════════════════════════════════════════
@router.post("/api/ext/device/code")
async def api_ext_device_code(request: Request):
    _require_provider()
    _rate_limit(f"devcode:{_client_ip(request)}", 20, 60)
    body = await request.json()
    # verification_uri:GitHub /login/device 式独立授权页。用 official_base() 而非
    # 请求 Host(防 Host 注入 open-redirect)。
    base = federation.official_base()
    verification_uri = f"{base}/device"
    return json_response(federation.device_start(
        body.get("client_name") or "", body.get("scopes") or ["library:read"], verification_uri))


@router.post("/api/ext/device/token")
async def api_ext_device_token(request: Request):
    _require_provider()
    body = await request.json()
    device_code = body.get("device_code") or ""
    # 强制轮询间隔(OAuth slow_down 语义):每 device_code 每 ~3.5s 一次。
    if not federation.rate_ok(f"devpoll:{device_code}", 1, 3.5):
        return json_response({"error": "slow_down"})
    return json_response(federation.device_poll(device_code))


# ════════════════════════════════════════════════════════════════════════
#  PROVIDER:外部库 API(Bearer PAT)
# ════════════════════════════════════════════════════════════════════════
@router.get("/api/ext/library/scripts")
async def api_ext_list(request: Request, q: str | None = None, limit: int = 30, offset: int = 0, pat=Depends(require_pat_read)):
    _rate_limit(f"extlist:{_client_ip(request)}", 120, 60)
    return json_response(federation.ext_list_scripts(q, limit, offset))


@router.get("/api/ext/library/scripts/{script_id}/pack")
async def api_ext_pack(script_id: int, request: Request, pat=Depends(require_pat_read)):
    _rate_limit(f"extpack:{_client_ip(request)}", 30, 60)
    try:
        zip_bytes, filename = federation.ext_export_pack(script_id)
    except PermissionError:
        return json_response({"ok": False, "error": "This script is not public"}, status_code=403)
    except ValueError as exc:
        return value_error_response(exc, status_code=404)
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or f"script-{script_id}.zip"
    quoted = _quote(filename, safe="")
    cd = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"
    return Response(content=zip_bytes, media_type="application/zip",
                    headers={"Content-Disposition": cd, "X-Content-Type-Options": "nosniff"})


@router.post("/api/ext/library/scripts/publish")
async def api_ext_publish(request: Request, pat=Depends(require_pat_publish)):
    _rate_limit(f"extpub:{_client_ip(request)}", 10, 60)
    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "read"):
        raise HTTPException(status_code=400, detail="Missing file field")
    raw = await file.read()
    if raw[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="不是合法的剧本包 zip")
    try:
        return json_response(federation.ext_publish_pack(pat["user"]["id"], raw))
    except ValueError as exc:
        return value_error_response(exc)


# ════════════════════════════════════════════════════════════════════════
#  CLIENT:本地连接器(cookie)
# ════════════════════════════════════════════════════════════════════════
@router.get("/api/me/library-connector")
async def api_connector_get(user=Depends(require_user)):
    return json_response(federation.connector_get(user["id"]))


@router.post("/api/me/library-connector")
async def api_connector_set(request: Request, user=Depends(require_user)):
    body = await request.json()
    try:
        federation.connector_set(user["id"], body.get("base_url") or "", body.get("token") or "")
        return json_response(federation.connector_get(user["id"]))
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/me/library-connector/test")
async def api_connector_test(user=Depends(require_user)):
    try:
        return json_response(await asyncio.to_thread(federation.connector_test, user["id"]))
    except ValueError as exc:
        return value_error_response(exc)


@router.get("/api/me/library-connector/scripts")
async def api_connector_scripts(q: str | None = None, limit: int = 30, offset: int = 0, user=Depends(require_user)):
    try:
        return json_response(await asyncio.to_thread(federation.connector_list, user["id"], q, limit, offset))
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/me/library-connector/import")
async def api_connector_import(request: Request, user=Depends(require_user)):
    body = await request.json()
    rid = body.get("remote_script_id")
    if not rid:
        return json_response({"ok": False, "error": "缺 remote_script_id"}, status_code=400)
    try:
        return json_response(await asyncio.to_thread(federation.connector_import, user["id"], int(rid)))
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/me/library-connector/publish")
async def api_connector_publish(request: Request, user=Depends(require_user)):
    body = await request.json()
    sid = body.get("script_id")
    if not sid:
        return json_response({"ok": False, "error": "缺 script_id"}, status_code=400)
    try:
        return json_response(await asyncio.to_thread(federation.connector_publish, user["id"], int(sid)))
    except (ValueError, PermissionError) as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)


# ── CLIENT:设备码流(cookie,本地引导)────────────────────────────────────
@router.post("/api/me/library-connector/device/start")
async def api_connector_device_start(request: Request, user=Depends(require_user)):
    body = await request.json()
    try:
        return json_response(await asyncio.to_thread(
            federation.connector_device_start, user["id"],
            body.get("base_url") or "", body.get("scopes") or ["library:read"]))
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/me/library-connector/device/poll")
async def api_connector_device_poll(request: Request, user=Depends(require_user)):
    body = await request.json()
    try:
        return json_response(await asyncio.to_thread(
            federation.connector_device_poll, user["id"],
            body.get("base_url") or "", body.get("device_code") or ""))
    except ValueError as exc:
        return value_error_response(exc)
