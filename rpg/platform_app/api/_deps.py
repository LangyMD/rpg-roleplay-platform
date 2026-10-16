"""platform_app.api._deps — 跨 router 共享的 dependency / helper。"""

from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as BaseJSONResponse

from tools_dsl.tool_registry import tool_payload

from .. import auth, library, workspace
from ..db import connect, init_db

SESSION_COOKIE = "rpg_session"
API_VERSION = "1"

COMMANDS = [
    ("GET", "/", "Backend root (service info JSON)"),
    ("GET", "/api/state", "Read the current playable save state"),
    ("POST", "/api/new", "Start a new game and keep a backup of the old save"),
    ("POST", "/api/opening", "Generate the opening"),
    ("POST", "/api/chat", "Send a player action/dialogue; supports streaming GM output and structured state write-back"),
    ("POST", "/api/stop", "Interrupt the current generation"),
    ("POST", "/api/save", "Manually save the current game"),
    ("POST", "/api/memory/add", "Add long-term memory"),
    ("POST", "/api/memory/remove", "Remove long-term memory"),
    ("POST", "/api/permissions", "Set LLM state write permission"),
    ("GET", "/api/models", "Read the API/model tree and the displayed model"),
    ("POST", "/api/models/select", "Select the current model"),
    ("POST", "/api/models/api", "Add or update an API provider"),
    ("POST", "/api/models/model", "Add or update a model under an API"),
    ("GET", "/api/tools", "Plugin/MCP/Skill capability status"),
    ("POST", "/api/mcp/server", "Add or update an MCP server config"),
    ("POST", "/api/mcp/server/enabled", "Enable or disable an MCP server"),
    ("POST", "/api/mcp/server/delete", "Delete an MCP server config"),
    ("POST", "/api/mcp/server/validate", "Validate that an MCP stdio command is available"),
    ("POST", "/api/skills/import", "Import a Skill package (local deployments)"),
    ("POST", "/api/worldline/variable", "Add or lock a user world line variable"),
    ("POST", "/api/worldline/variable/remove", "Remove a user world line variable"),
    ("POST", "/api/auth/register", "Register an account"),
    ("POST", "/api/auth/login", "Log in and set the session cookie"),
    ("POST", "/api/auth/logout", "Log out"),
    ("GET", "/api/platform", "Platform overview: home, scripts, saves, library, tools"),
    ("GET", "/api/scripts", "Script list"),
    ("POST", "/api/scripts/import", "Import a TXT/MD script and detect chapters automatically"),
    ("GET", "/api/scripts/{script_id}/chapters", "Read a script's chapter list and previews"),
    (
        "POST",
        "/api/scripts/{script_id}/knowledge/sync",
        "Rebuild a script's ChapterFacts, worldbook, character cards and retrieval chunks",
    ),
    ("GET", "/api/scripts/{script_id}/chapter-facts", "Read a script's ChapterFact timeline"),
    (
        "GET",
        "/api/scripts/{script_id}/birthpoints",
        "Pick a starting point: grouped by phase, with anchors sampled evenly per phase",
    ),
    ("GET", "/api/scripts/{script_id}/character-cards", "Read a script's character cards"),
    ("GET", "/api/scripts/{script_id}/worldbook", "Read a script's worldbook entries"),
    ("GET", "/api/saves", "Game save list"),
    ("POST", "/api/saves", "Create a new save from a script"),
    ("GET", "/api/branches/{save_id}", "Read a save's branch tree"),
    ("POST", "/api/branches/continue", "Fork/activate the current game runtime from any conversation node"),
    ("POST", "/api/branches/activate", "Activate a branch node directly as the current game runtime"),
    ("POST", "/api/branches/delete", "Delete the whole branch under a link"),
    ("GET", "/api/saves/{save_id}/context-runs", "Read a save's context sub-agent run records"),
    ("GET", "/api/saves/{save_id}/anchors", "Read the status of a save's world line convergence anchors"),
    ("POST", "/api/saves/{save_id}/anchors/reseed", "Re-seed anchors (debug)"),
    ("GET", "/api/settings", "Read settings"),
    ("POST", "/api/settings", "Write settings"),
    ("GET", "/api/library", "File library list"),
    ("POST", "/api/library/upload", "Upload to the file library"),
    ("POST", "/api/library/mkdir", "Create a folder in the file library"),
    ("GET", "/api/platform/commands", "Read the full command list"),
]


# 建档/存档列表偶发 "Invalid control character"(浏览器 JSON.parse / Python json.loads
# 均拒收裸 \x00-\x1f):存量存档的自由文本字段(title / player_name / world_time /
# 角色卡 background 等,来自玩家手填、LLM 生成、或 SillyTavern PNG 卡片导入)可能已经
# 带着裸控制字符落库多年。标准 json.dumps 会正确转义这些字符——但那依赖【每一个】响应
# 都严格走 jsonable_encoder → json.dumps 这条路径，属于隐式契约，一旦某处改用别的序列化
# （手写 Response、换 orjson、日志/缓存里转手拼接……）就会无声破功，而脏数据已经在库里，
# 只修写入侧救不了老档。这里在读出→响应这一层做兜底：递归清洗所有 str 叶子值，把 C0 控制
# 字符（\x00-\x1f，保留 \t\n\r 这三个合法空白）和 DEL（\x7f）替换成一个空格，不改变其余内容、
# 不改变字符串长度以外的语义。
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_control_chars(value):
    """递归清洗 dict/list/str 中的裸控制字符（保留 \\t \\n \\r）。非 str 原样返回。"""
    if isinstance(value, str):
        if not _CONTROL_CHAR_RE.search(value):
            return value  # 快路径：绝大多数字符串无脏字符，不分配新对象
        return _CONTROL_CHAR_RE.sub(" ", value)
    if isinstance(value, dict):
        return {k: _strip_control_chars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_control_chars(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_strip_control_chars(v) for v in value)
    return value


def json_response(content, status_code: int = 200, **kwargs):
    if isinstance(content, dict) and "meta" not in content:
        content = {
            **content,
            "meta": {
                "api_version": API_VERSION,
                "stable": True,
            },
        }
    encoded = jsonable_encoder(content)
    encoded = _strip_control_chars(encoded)
    return BaseJSONResponse(encoded, status_code=status_code, **kwargs)


def value_error_response(exc: ValueError, status_code: int = 400):
    """`except ValueError as exc: return json_response({"ok": False, "error": str(exc)}, status_code=N)`
    的样板收敛。仅用于响应体恰为该形状的调用点,别用于带额外字段的响应。"""
    return json_response({"ok": False, "error": str(exc)}, status_code=status_code)


def _request_is_https(request: Request) -> bool:
    """浏览器面向的连接是否 HTTPS。
    容器内 uvicorn 不带 --proxy-headers 时 request.url.scheme 恒为 http(哪怕前面挂了
    TLS 反代),所以必须读 X-Forwarded-Proto 才能识别 nginx/CF 终止的 HTTPS。
    XFP 只用于决定 cookie 的 Secure 标志,伪造它顶多废掉伪造者自己的 cookie。
    """
    if request.url.scheme == "https":
        return True
    xfp = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return xfp == "https"


def _cookie_security_kwargs(request: Request) -> dict:
    """统一的 cookie 安全参数,set 和 delete 必须用同一组,否则浏览器会把
    delete 当成"另一个 cookie",导致原 cookie 残留。

    samesite 固定 lax(同源部署)。secure 跟随【有效协议】:HTTPS(含反代 X-Forwarded-Proto)
    才带 Secure;明文 HTTP 自托管不带(浏览器会【静默丢弃】明文 HTTP 上的 Secure cookie →
    会话存不下 → 登录后弹回登录页)。反代 HTTPS 终止时容器内 scheme 恒 http,必须靠 XFP
    才能正确带上 Secure。
    """
    return {
        "httponly": True,
        "secure": _request_is_https(request),
        "samesite": "lax",
        "path": "/",
    }


def _set_session_cookie(response: BaseJSONResponse, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 24 * 60 * 60,
        **_cookie_security_kwargs(request),
    )


def _delete_session_cookie(response: BaseJSONResponse, request: Request) -> None:
    """删 cookie 必须传跟 set 一致的 samesite/secure,否则浏览器收到的 Set-Cookie
    属性不匹配,会被当成"另一个 cookie"残留,反而留下原 cookie。"""
    response.delete_cookie(SESSION_COOKIE, **_cookie_security_kwargs(request))


def _auth_required() -> bool:
    """与 ui.py:_api_auth_required 同义，避免循环导入；服务器模式禁止匿名访问。"""
    from core.config import effective_auth_required as _eff
    return _eff()


# ensure_default 是「遗留存档 backfill」(补分支树 + runtime 指针),不是每请求都要做的事:
# 新存档在 workspace.create_save() 创建时已自行 seed_tree,所以 ensure_default 只为存量旧
# 存档兜底。原实现每个认证请求都跑一个 game_saves⋈scripts JOIN(+有存档时还 seed_tree +
# 读 runtime 文件),是热路径浪费。用进程内幂等守卫:每用户每进程只 backfill 一次。
# best-effort(GIL 下 set in/add 原子;多 worker 各跑一次、backfill 幂等,无害,故不上锁)。
_ENSURED_DEFAULT_USERS: set[int] = set()


def _local_default_user() -> dict | None:
    """本地/自部署免登录模式:取库中第一个用户(按 id)作为隐式登录用户。无则 None。"""
    try:
        with connect() as db:
            row = db.execute("select * from users order by id asc limit 1").fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def _is_loopback(request: Request) -> bool:
    """请求是否来自本机回环(127.0.0.1 / ::1 / localhost)。LAN 设备走真实 IP → False。"""
    host = (request.client.host if request.client else "") or ""
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


def current_user(request: Request) -> dict | None:
    try:
        init_db()
        user = auth.user_from_token(request.cookies.get(SESSION_COOKIE))
        # 本地/自部署免登录模式(_auth_required()=False)且无 cookie 时,回退到库里第一个用户,
        # 让单用户本地部署开箱即用。**安全收紧**:仅「本机回环 + 默认账户未设密码」时才免登录回退;
        # LAN 设备(非回环)或默认账户已设密码 → 必须有真实会话(cookie / 魔法链接),
        # 否则同网任意设备都能越权拿到默认账户(做好本地部署鉴权)。服务器模式绝不走这条路。
        if user is None and not _auth_required():
            if _is_loopback(request) and not auth.local_account_has_password():
                user = _local_default_user()
        if user:
            uid = int(user["id"])
            if uid not in _ENSURED_DEFAULT_USERS:
                workspace.ensure_default(uid)
                _ENSURED_DEFAULT_USERS.add(uid)
        return user
    except Exception:
        return None


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def is_admin(user: dict | None) -> bool:
    """纯 admin 管理权谓词(role == 'admin')。

    注意:这与「平台兜底资格」(role ∈ {admin, vip_user},见
    knowledge.embedding.has_platform_fallback_role)是不同职责,资格集合不同,绝不跨用。
    """
    return bool(user and user.get("role") == "admin")


def require_admin(user=Depends(require_user)) -> dict:
    """FastAPI Depends:要求当前用户是 admin,否则 403。"""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Administrator privileges required")
    return user


def _resolve_save_id(user_id: int, body: dict) -> int:
    raw = body.get("save_id")
    if raw:
        sid = int(raw)
        # P1 fix: 显式校验 save 属于本人，不依赖下游兜底
        from ..perms import owns_save
        with connect() as db:
            if not owns_save(db, sid, user_id):
                raise HTTPException(status_code=403, detail="No access to this save")
        return sid
    with connect() as db:
        row = db.execute(
            "select id from game_saves where user_id = %s order by updated_at desc, id desc limit 1",
            (user_id,),
        ).fetchone()
    if not row:
        raise ValueError("There is no writable save yet")
    return int(row["id"])


def platform_for(user: dict | None) -> dict:
    """构建 /api/platform 和注册/登录响应的 payload。

    安全：MCP server 的 command/args/env 含 secret，普通用户必须脱敏。
    与 ui.py:_redact_tools 共用同一份逻辑，避免再次出现"漏脱敏入口"。
    """
    payload = workspace.overview(user)
    is_admin = bool(user and user.get("role") == "admin")
    payload["tools"] = _redact_mcp_in_tools(tool_payload(), is_admin)
    payload["commands"] = command_payload()
    if user:
        payload["library"] = library.list_dir(user["id"], "")
    return payload


_MCP_SECRET_FIELDS = ("command", "args", "env", "url", "headers", "credential", "secret", "token")


def _redact_mcp_in_tools(tools: dict, is_admin: bool) -> dict:
    """递归脱敏 tools 里的 mcp.servers[].command/args/env。"""
    if is_admin:
        return tools
    import copy

    out = copy.deepcopy(tools)
    for srv in (out.get("mcp") or {}).get("servers") or []:
        for field in _MCP_SECRET_FIELDS:
            srv.pop(field, None)
    for srv in out.get("mcp_servers") or []:
        for field in _MCP_SECRET_FIELDS:
            srv.pop(field, None)
    return out


def command_payload() -> list[dict]:
    return [
        {"method": method, "path": path, "name": path.rsplit("/", 1)[-1] or path, "desc": desc}
        for method, path, desc in COMMANDS
    ]


def _client_ip(request: Request) -> str:
    """获取客户端 IP。

    安全：默认只用 TCP 层的 request.client.host，不信任 X-Forwarded-For
    （否则攻击者直接换头就能绕过按 IP 的速率限制）。
    仅当 TCP 对端 IP 在 RPG_TRUSTED_PROXIES 白名单里（如 nginx/cloudflare 后端），
    才信 XFF 的第一段。
    """
    tcp_ip = request.client.host if request.client else ""
    from core.config import trusted_proxies_raw as _trusted_proxies_raw

    trusted = {ip.strip() for ip in _trusted_proxies_raw().split(",") if ip.strip()}
    if tcp_ip and tcp_ip in trusted:
        xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if xff:
            return xff
    return tcp_ip
