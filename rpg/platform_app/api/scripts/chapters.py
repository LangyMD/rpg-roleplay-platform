"""platform_app.api.scripts.chapters —— 章节 CRUD + 结构操作端点。

章节列表/详情/编辑、新建空白剧本、追加/合并/删除/拆分章、整本重切。
纯机械搬家,行为零变化。
"""
from __future__ import annotations

from fastapi import Depends, Request

from ... import script_import
from ...db import connect
from .._deps import json_response, require_user, value_error_response
from ._shared import router


@router.get("/api/scripts/{script_id}/chapters")
async def api_script_chapters(
    script_id: int,
    limit: int | None = None, cursor: str | None = None, q: str | None = None,
    user=Depends(require_user),
):
    """章节列表，支持 ?q=... 标题/内容全文 ILIKE 搜索。"""
    try:
        if q:
            # 全文搜索分支 — 权限与非搜索路径一致:owner ∪ subscriber
            with connect() as db:
                owned = db.execute(
                    """select 1 from scripts s where s.id = %s and (
                         s.owner_id = %s
                         or s.id in (select script_id from user_script_subscriptions where user_id = %s)
                       )""",
                    (script_id, user["id"], user["id"]),
                ).fetchone()
                if not owned:
                    return json_response({"ok": False, "error": "No access to this script"}, status_code=403)
                rows = db.execute(
                    """
                    select id, chapter_index, title, volume_title, word_count,
                           substring(content for 200) as preview
                    from script_chapters
                    where script_id = %s and (title ilike %s or content ilike %s)
                    order by chapter_index limit %s
                    """,
                    (script_id, f"%{q}%", f"%{q}%", int(limit or 50)),
                ).fetchall()
            from ...db import expose as _expose
            return json_response({"ok": True, "items": [_expose(r) for r in rows], "query": q})
        return json_response({"ok": True, **script_import.list_chapters(user["id"], script_id, limit, cursor)})
    except ValueError as exc:
        return value_error_response(exc)


@router.get("/api/scripts/{script_id}/chapters/{chapter_index:int}")
async def api_chapter_detail(script_id: int, chapter_index: int, user=Depends(require_user)):
    """单章节完整 content(列表 API 只返 180 字符 preview,这里是 lazy fetch 真章节正文)。"""
    with connect() as db:
        owned = db.execute(
            """select 1 from scripts s
            where s.id = %s and (
              s.owner_id = %s
              or s.id in (select script_id from user_script_subscriptions where user_id = %s)
            )""",
            (script_id, user["id"], user["id"]),
        ).fetchone()
        if not owned:
            return json_response({"ok": False, "error": "No access to this script"}, status_code=403)
        row = db.execute(
            """
            select id, public_id, chapter_index, title, volume_title,
                   word_count, content, created_at, updated_at
            from script_chapters
            where script_id = %s and chapter_index = %s
            """,
            (script_id, chapter_index),
        ).fetchone()
    if not row:
        return json_response({"ok": False, "error": "Chapter not found"}, status_code=404)
    from ...db import expose as _expose
    return json_response({"ok": True, "chapter": _expose(row)})


@router.post("/api/scripts/{script_id}/chapters/{chapter_index:int}")
async def api_chapter_update(request: Request, script_id: int, chapter_index: int, user=Depends(require_user)):
    """编辑单章 title/content/volume_title。

    body.base_updated_at(可选,乐观锁):与服务端 updated_at 不一致时 409+服务端当前版本,
    前端转三方合并(编辑器 P0:AI 写库与未保存改动互相静默覆盖)。不传=覆盖语义不变。"""
    body = await request.json()
    try:
        return json_response(script_import.update_chapter(
            user["id"], script_id, chapter_index,
            title=body.get("title"), content=body.get("content"),
            volume_title=body.get("volume_title"),
            base_updated_at=body.get("base_updated_at"),
        ))
    except script_import.ChapterConflict as conflict:
        return json_response(
            {"ok": False, "conflict": True, "error": "The chapter was updated by someone else",
             "server_chapter": conflict.server_chapter},
            status_code=409)
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/scripts/blank")
async def api_create_blank_script(request: Request, user=Depends(require_user)):
    """作者优先:从零新建空白剧本(含第1章空章),供作者直接写、用选区提取边写边建 KB。返回 script_id。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        return json_response(script_import.create_blank_script(user["id"], (body or {}).get("title") or ""))
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/scripts/{script_id}/add-chapter")
async def api_add_chapter(request: Request, script_id: int, user=Depends(require_user)):
    """作者优先:给剧本追加一个空白新章(owner 闸)。返回 chapter_index。
    路径用 add-chapter 而非 chapters/new,避免与 /chapters/{chapter_index:int} 冲突。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        return json_response(script_import.create_chapter(user["id"], script_id, (body or {}).get("title") or ""))
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/scripts/{script_id}/chapters/merge")
async def api_chapter_merge(request: Request, script_id: int, user=Depends(require_user)):
    """合并 first_index 与其相邻下一章(second_index 显式指定,缺省取按序的下一章)。"""
    body = await request.json()
    try:
        _second = body.get("second_index")
        _keep = body.get("keep_title_index")
        return json_response(script_import.merge_chapters(
            user["id"], script_id, int(body.get("first_index") or 0),
            second_index=(int(_second) if _second is not None else None),
            keep_title_index=(int(_keep) if _keep is not None else None),
            separator=body.get("separator") or "\n\n",
        ))
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/scripts/{script_id}/chapters/delete")
async def api_chapters_delete(request: Request, script_id: int, user=Depends(require_user)):
    """删除一批章节并整本重排(body: {indexes:[...]} 或 {chapter_index:n})。

    结构操作:RAG(按 chapter_index 的外键)与 merge/split 一致,需重新提取才能完全对齐。
    """
    body = await request.json()
    idxs = body.get("indexes")
    if idxs is None and body.get("chapter_index") is not None:
        idxs = [body.get("chapter_index")]
    try:
        return json_response(script_import.delete_chapters(
            user["id"], script_id, [int(i) for i in (idxs or [])],
        ))
    except (ValueError, TypeError) as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/api/scripts/{script_id}/chapters/{chapter_index:int}/split")
async def api_chapter_split(request: Request, script_id: int, chapter_index: int, user=Depends(require_user)):
    """按字符位置 split_at 把一章拆成两章。"""
    body = await request.json()
    try:
        return json_response(script_import.split_chapter(
            user["id"], script_id, chapter_index,
            split_at=int(body.get("split_at") or 0),
            new_title=body.get("new_title") or "",
        ))
    except ValueError as exc:
        return value_error_response(exc)


@router.post("/api/scripts/{script_id}/resplit")
async def api_script_resplit(request: Request, script_id: int, user=Depends(require_user)):
    """用新规则重切已导入剧本。保留 script + 存档，只换章节。"""
    body = await request.json()
    try:
        return json_response(script_import.resplit_script(
            user["id"], script_id,
            split_rule=body.get("split_rule", "auto"),
            custom_pattern=body.get("custom_pattern", ""),
        ))
    except ValueError as exc:
        return value_error_response(exc)
