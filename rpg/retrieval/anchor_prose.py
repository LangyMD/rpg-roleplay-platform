"""retrieval.anchor_prose — rail 原文注入族:锚点章节原文抓取 + 作者文风样本抽取。

拆包(纯机械搬家):自 rpg/retrieval.py 逐字搬来,函数体零改动。
"""
from __future__ import annotations


# task 125: 强制拉 anchor 章节的真实原文,解决 GM "拿到标题没拿到内容"问题。
# 不依赖 BM25 命中 (开场 turn=0 时 query 太弱),直接按 chapter_index 取 chunks。
def _load_anchor_chapter_text(script_id: int, chapter_min: int, chapter_max: int | None = None, max_chars: int = 2400) -> str:
    """取 chapter_min..chapter_max 范围内前几章的实际原文 (从 document_chunks),
    供 GM 在开场/低 turn 时严格基于原著重写,不凭空捏造。
    """
    if not script_id or not chapter_min:
        return ""
    cmax = chapter_max if chapter_max is not None else chapter_min
    # 限制窗口:开场只需要 anchor 当前章 + 紧邻 1-2 章
    cmax = min(int(cmax), int(chapter_min) + 2)
    try:
        from platform_app.db import connect as _connect
        with _connect() as db:
            rows = db.execute(
                """
                select chapter_index, chunk_index, content
                from document_chunks
                where script_id = %s and chapter_index between %s and %s
                order by chapter_index asc, chunk_index asc
                limit 48
                """,
                (int(script_id), int(chapter_min), int(cmax)),
            ).fetchall() or []
        if not rows:
            return ""
        # 按章节聚合,每章拼 2-3 个 chunk,但总长度限 max_chars
        out_lines = []
        used = 0
        last_ch = None
        for r in rows:
            ch = int(r["chapter_index"])
            content = (r["content"] or "").strip()
            if not content:
                continue
            if ch != last_ch:
                out_lines.append(f"--- Chapter {ch} source excerpt ---")
                last_ch = ch
            piece = content[: max(0, max_chars - used)]
            out_lines.append(piece)
            used += len(piece)
            if used >= max_chars:
                break
        return "\n".join(out_lines)
    except Exception:
        return ""


def _extract_style_sample(text: str, n_sentences: int = 5, max_chars: int = 500) -> str:
    """task 131-B: 从锚点章节原文抽 5 句作 style anchor 给 GM 学句法 / 节奏 / 词汇。
    简单算法 — 不依赖 LLM,直接按句号切,挑长度适中的句子(避免短促对白和长段景物):
      · 10 < len(s) < 60 (有信息密度,不是 '。' 或 '嗯。')
      · 不要句首是描写性符号(去掉对话/旁白引导)
      · 优先取前 N 段(不要从结尾抽,通常是高潮段不代表整本)
    通用 — 适用任何小说,不挑特定书。
    """
    if not text or len(text) < 80:
        return ""
    import re as _re
    # 去除 markdown 头 / 元数据
    body = _re.sub(r"^---.*?---\s*", "", text, flags=_re.DOTALL).strip()
    body = _re.sub(r"^#+\s*[^\n]+\n", "", body, count=2).strip()  # 剥 ## 第 X 章 标题
    # 拿前 1500 字
    body = body[:1500]
    sentences = _re.split(r"(?<=[。！？.!?])\s*", body)
    picked = []
    used = 0
    for s in sentences:
        s = s.strip().lstrip("【】").strip()
        if 10 <= len(s) <= 60 and not s.startswith(("---", "#", "【")):
            piece = s
            if used + len(piece) + 4 > max_chars:
                break
            picked.append(piece)
            used += len(piece) + 1
            if len(picked) >= n_sentences:
                break
    return "\n".join(picked) if picked else ""
