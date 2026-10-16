"""platform_app.api.scripts.library —— 剧本生命周期 + 在线公开库端点。

取消订阅、删除、重命名 + 公开分享(visibility)、公开库浏览/详情/订阅(clone)/物理复制(fork)。
纯机械搬家,行为零变化。
"""
from __future__ import annotations

from fastapi import Depends, Request

from ... import script_import
from ...db import connect
from .._deps import json_response, require_user, value_error_response
from ._shared import router


@router.post("/api/scripts/{script_id}/unsubscribe")
async def api_script_unsubscribe(script_id: int, user=Depends(require_user)):
    """取消订阅来自公开库的剧本:只删 user_script_subscriptions 指针,不碰原剧本数据。"""
    with connect() as db:
        result = db.execute(
            "DELETE FROM user_script_subscriptions WHERE user_id = %s AND script_id = %s",
            (user["id"], script_id),
        )
        if result.rowcount == 0:
            return json_response({"ok": False, "error": "You are not subscribed to this script"}, status_code=404)
        db.commit()
    return json_response({"ok": True, "unsubscribed": True, "script_id": script_id})


@router.post("/api/scripts/{script_id}/delete")
async def api_script_delete(request: Request, script_id: int, user=Depends(require_user)):
    """删除剧本。force=True 时连带删除其下所有存档。"""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    try:
        return json_response(script_import.delete_script(user["id"], script_id, force=bool(body.get("force"))))
    except ValueError as exc:
        return value_error_response(exc, status_code=403)


@router.post("/api/scripts/{script_id}/rename")
async def api_script_rename(request: Request, script_id: int, user=Depends(require_user)):
    """重命名剧本(改 scripts.title)。严格 owner;订阅剧本只读(403)。"""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    title = str(body.get("title") or "").strip()
    if not title:
        return json_response({"ok": False, "error": "Title cannot be empty"}, status_code=400)
    from ...db import connect as _connect
    with _connect() as db:
        row = db.execute(
            "update scripts set title=%s, updated_at=now() where id=%s and owner_id=%s returning id, title",
            (title[:200], script_id, user["id"]),
        ).fetchone()
        if not row:
            return json_response({"ok": False, "error": "Only the original author can rename this script (subscribed scripts are read-only; fork it first to make changes)"}, status_code=403)
        db.commit()
    return json_response({"ok": True, "id": row["id"], "title": row["title"]})


# ── 在线剧本库(公开分享 / 浏览 / 导入)─────────────────────────────────────────

@router.post("/api/scripts/{script_id}/visibility")
async def api_script_visibility(request: Request, script_id: int, user=Depends(require_user)):
    """owner 设置剧本是否公开分享。Body: {is_public: bool}。

    公开后内容(章节/角色卡/世界书)对所有用户可浏览并导入到自己账户。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    is_public = bool(body.get("is_public"))
    with connect() as db:
        from ...perms import script_owned
        owned = script_owned(db, script_id, user["id"])
        if not owned:
            return json_response({"ok": False, "error": "Not allowed to modify this script"}, status_code=403)
        if is_public:
            # 护栏:0 章空剧本(注册默认档 / 未导入正文)不允许公开,避免污染公开库。
            # 以 script_chapters 实际行数为准(chapter_count 列可能陈旧)。
            real_ch = db.execute(
                "SELECT count(*) AS n FROM script_chapters WHERE script_id = %s",
                (script_id,),
            ).fetchone()
            if not (dict(real_ch) or {}).get("n", 0):
                return json_response(
                    {"ok": False, "error": "An empty script (0 chapters) cannot be shared publicly; import its text first."},
                    status_code=400,
                )
            # KB 复核闸:未通过复核的剧本不允许分享到公开库(与新建存档闸一致),
            # 防止未审实体/未消歧别名/错章节污染公开剧本库。前端也会预拦并引导,
            # 此处是确定性后端兜底(不依赖前端)。重切(resplit)后会自动回 unreviewed。
            if (dict(owned) or {}).get("review_status", "unreviewed") != "reviewed":
                return json_response(
                    {"ok": False, "error": "REVIEW_REQUIRED",
                     "message": "Before sharing to the public library, the script must pass KB review: check its entities / world line / time anchors under \"KB check\" and click \"Mark as reviewed\"."},
                    status_code=409,
                )
        db.execute(
            "UPDATE scripts SET is_public = %s, "
            "published_at = COALESCE(published_at, CASE WHEN %s THEN now() ELSE NULL END) "
            "WHERE id = %s",
            (is_public, is_public, script_id),
        )
        db.commit()
    return json_response({"ok": True, "is_public": is_public})


@router.get("/api/scripts/public")
async def api_public_scripts(q: str | None = None, limit: int = 30, offset: int = 0,
                             user=Depends(require_user)):
    """浏览公开剧本库。支持标题/简介搜索,按发布时间倒序。"""
    limit = max(1, min(int(limit or 30), 60))
    offset = max(0, int(offset or 0))
    where = "s.is_public"
    params: list = []
    if q:
        where += " AND (s.title ILIKE %s OR s.description ILIKE %s)"
        like = f"%{q}%"
        params += [like, like]
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT s.id, s.title, s.description, s.chapter_count, s.word_count,
                   s.clone_count, s.published_at, s.cover_image_url, s.owner_id,
                   u.display_name AS author, u.username AS author_username
            FROM scripts s JOIN users u ON u.id = s.owner_id
            WHERE {where}
            ORDER BY s.published_at DESC NULLS LAST, s.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit + 1, offset),
        ).fetchall()
        rows = [dict(r) for r in rows]
    has_more = len(rows) > limit
    items = rows[:limit]
    for it in items:
        it["mine"] = (it.pop("owner_id") == user["id"])
    return json_response({"ok": True, "items": items, "has_more": has_more,
                          "limit": limit, "offset": offset})


@router.get("/api/scripts/public/{script_id}")
async def api_public_script_detail(script_id: int, user=Depends(require_user)):
    """公开剧本详情:元信息 + 前若干章标题 + 角色卡/世界书条目数。"""
    with connect() as db:
        row = db.execute(
            """
            SELECT s.id, s.title, s.description, s.chapter_count, s.word_count,
                   s.clone_count, s.published_at, s.content_fingerprint, s.cover_image_url,
                   s.owner_id,
                   u.display_name AS author, u.username AS author_username
            FROM scripts s JOIN users u ON u.id = s.owner_id
            WHERE s.id = %s AND s.is_public
            """,
            (script_id,),
        ).fetchone()
        if not row:
            return json_response({"ok": False, "error": "Script not found or not public"}, status_code=404)
        d = dict(row)
        chapter_titles = db.execute(
            "SELECT title FROM script_chapters WHERE script_id = %s ORDER BY chapter_index LIMIT 12",
            (script_id,),
        ).fetchall()
        card_count = db.execute(
            "SELECT count(*) AS n FROM character_cards WHERE script_id = %s", (script_id,),
        ).fetchone()
        wb_count = db.execute(
            "SELECT count(*) AS n FROM worldbook_entries WHERE script_id = %s", (script_id,),
        ).fetchone()
        fp = d.get("content_fingerprint") or ""
        already = False
        if fp:
            already = bool(db.execute(
                "SELECT 1 FROM scripts WHERE owner_id = %s AND content_fingerprint = %s LIMIT 1",
                (user["id"], fp),
            ).fetchone())
    mine = d.pop("owner_id") == user["id"]
    d.pop("content_fingerprint", None)
    d["mine"] = mine
    d["already_imported"] = already or mine
    d["chapter_titles"] = [r["title"] for r in chapter_titles]
    d["card_count"] = (dict(card_count) or {}).get("n", 0)
    d["worldbook_count"] = (dict(wb_count) or {}).get("n", 0)
    return json_response({"ok": True, "script": d})


@router.post("/api/scripts/public/{script_id}/clone")
async def api_clone_public_script(script_id: int, user=Depends(require_user)):
    """task: 公开剧本「导入」= O(1) subscribe(指针挂载),不再物理复制。

    剧本是 immutable knowledge,只有原 owner 能编辑;普通用户挂载即可,几毫秒 INSERT
    替代原来 30-60s 的全表 clone(scripts + chapters + cards + worldbook + canon +
    timeline_anchors + phase_digests + worldlines + nodes 跨 9 张表)。

    如需「另存为可编辑副本」(真复制),走 /api/scripts/public/{id}/fork。
    """
    with connect() as db:
        # 1. 校验剧本存在 + 公开
        row = db.execute(
            "select id, owner_id, is_public, title from scripts where id = %s",
            (script_id,),
        ).fetchone()
        if not row:
            return json_response({"ok": False, "error": "Script not found"}, status_code=404)
        if not row.get("is_public"):
            return json_response({"ok": False, "error": "This script is not public and cannot be imported"}, status_code=403)
        if int(row["owner_id"]) == int(user["id"]):
            return json_response({"ok": False, "error": "This is your own script; no need to subscribe"}, status_code=400)
        # 2. O(1) INSERT subscription(主键冲突即已订阅)。RETURNING 1 只在【真正插入】
        #    时返回一行 → 据此判断是否首次订阅,避免重复订阅也把 clone_count +1(指标虚高)。
        inserted = db.execute(
            """
            insert into user_script_subscriptions (user_id, script_id)
            values (%s, %s)
            on conflict (user_id, script_id) do nothing
            returning 1
            """,
            (user["id"], script_id),
        ).fetchone()
        # 3. 热度计数 +1(仅首次订阅)
        if inserted:
            try:
                db.execute("update scripts set clone_count = clone_count + 1 where id = %s", (script_id,))
            except Exception:
                pass
    return json_response({
        "ok": True,
        "script_id": script_id,
        "subscribed": True,
        "title": row.get("title"),
    })


@router.post("/api/scripts/public/{script_id}/fork")
async def api_fork_public_script(script_id: int, user=Depends(require_user)):
    """task: 「另存为可编辑副本」= 旧 clone 行为(全表物理复制)。

    谨慎使用 — 慢(30-60s),会失去与原剧本的同步。
    """
    from platform_app.knowledge.script_pack import clone_public_script
    try:
        result = clone_public_script(script_id, user["id"])
    except PermissionError as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=403)
    except ValueError as exc:
        return value_error_response(exc)
    return json_response({"ok": True, **result})
