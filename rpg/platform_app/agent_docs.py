"""platform_app.agent_docs — 编辑器写作搭档的「拖入文档」暂存 + 确定性拆章。

设计目标(用户原话:降低服务器压力 + 安全):
- 文档原文【不进 LLM 上下文】—— 存服务端,agent 只拿 doc_id 编排;LLM 绝不啃几 MB 正文。
- 拆章用【确定性】chapter_splitter(纯 regex,零 LLM token)。
- 安全:owner 闸(端点处)+ 体积上限 + TTL 清理(防表无限膨胀)。
"""
from __future__ import annotations

import base64
import secrets
from typing import Any

from platform_app.db import connect, init_db

# 拖入文档的体积上限:比整本小说导入(128MB)小得多 —— 写作搭档场景是「一段/一章/一节」级别。
AGENT_DOC_MAX_BYTES = 12 * 1024 * 1024  # 12MB
_DOC_TTL_DAYS = 3


def _new_doc_id() -> str:
    return f"doc-{secrets.token_urlsafe(9)}"


def _cleanup_old(db) -> None:
    """机会式清理:删 TTL 之外的旧文档(每次新存时顺手跑,不另起定时任务)。"""
    try:
        db.execute(
            "delete from agent_doc_uploads where created_at < now() - interval '%s days'" % int(_DOC_TTL_DAYS)
        )
    except Exception:
        pass


def store_doc(user_id: int, script_id: int | None, filename: str, *,
              content_b64: str = "", content_text: str = "") -> dict[str, Any]:
    """暂存一份拖入文档。content_b64(优先)或 content_text 二选一。返回 {doc_id, filename, chars, preview}。"""
    init_db()
    if content_b64:
        try:
            raw = base64.b64decode(content_b64, validate=False)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Document base64 decode failed: {exc}") from exc
        if len(raw) > AGENT_DOC_MAX_BYTES:
            raise ValueError(f"Document is too large (>{AGENT_DOC_MAX_BYTES // (1024 * 1024)}MB)")
        # 用 chapter_splitter 的编码探测,兼容 GBK/UTF-8 等中文小说常见编码。
        import chapter_splitter
        text, _enc = chapter_splitter.ChapterSplitter().decode_bytes(raw)
    else:
        text = content_text or ""
        if len(text.encode("utf-8", "ignore")) > AGENT_DOC_MAX_BYTES:
            raise ValueError(f"Document is too large (>{AGENT_DOC_MAX_BYTES // (1024 * 1024)}MB)")
    text = (text or "").replace("\x00", "")
    if not text.strip():
        raise ValueError("Document is empty")
    doc_id = _new_doc_id()
    fname = (filename or "").strip()[:200]
    with connect() as db:
        _cleanup_old(db)
        db.execute(
            "insert into agent_doc_uploads(doc_id, user_id, script_id, filename, content, chars) "
            "values (%s,%s,%s,%s,%s,%s)",
            (doc_id, int(user_id), (int(script_id) if script_id else None), fname, text, len(text)),
        )
        if hasattr(db, "commit"):
            db.commit()
    return {"doc_id": doc_id, "filename": fname, "chars": len(text), "preview": text[:240]}


def load_doc(user_id: int, doc_id: str) -> dict[str, Any] | None:
    """按 doc_id + user_id 取暂存文档(owner 隔离:别人的 doc 取不到)。"""
    init_db()
    if not (doc_id and user_id):
        return None
    with connect() as db:
        row = db.execute(
            "select doc_id, filename, content, chars, script_id from agent_doc_uploads "
            "where doc_id=%s and user_id=%s",
            (doc_id, int(user_id)),
        ).fetchone()
    return dict(row) if row else None
