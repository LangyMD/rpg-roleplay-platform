"""Async LLM summary generation for branch commits."""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor

from platform_app.db import connect

_SUMMARY_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="branch-summary")
_SUMMARY_GM = None
_SUMMARY_GM_LOCK = threading.Lock()
_LLM_SUMMARY_SYSTEM = (
    "You are a story summary assistant. After reading one turn's player input and GM response, "
    "summarize what happened in that turn in 6-12 words.\n"
    "Requirements:\n"
    "- Output only the summary itself, with no prefix\n"
    "- Lead with verbs and avoid a subject\n"
    "- No trailing period, quotes or labels\n"
    "- Describe failures, refusals and interruptions objectively too"
)


def _get_summary_gm():
    global _SUMMARY_GM
    if _SUMMARY_GM is not None:
        return _SUMMARY_GM
    with _SUMMARY_GM_LOCK:
        if _SUMMARY_GM is None:
            try:
                from agents.gm import GameMaster
                _SUMMARY_GM = GameMaster()  # 默认 gemini-3.5-flash，够用
            except Exception:
                _SUMMARY_GM = False
    return _SUMMARY_GM or None


def _run_llm_summary(commit_id: int, player_text: str, gm_text: str) -> None:
    """后台线程：用 LLM 重写 branch_commits.summary。失败静默。"""
    try:
        gm = _get_summary_gm()
        if not gm:
            return
        prompt = f"Player input:\n{player_text[:600]}\n\nGM response:\n{gm_text[:1200]}"
        summary = gm._backend.call(
            system=_LLM_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
        ).strip()
        # 清理标点、引号、前缀
        summary = re.sub(r"^[【「\"'：:\-—]+", "", summary)
        summary = re.sub(r"[】」\"'。！？!?]+$", "", summary)
        summary = summary.replace("\n", " ").strip()
        if len(summary) > 32:
            summary = summary[:32]
        if len(summary) < 4:
            return  # 太短的不写回，保留 rough_summary
        with connect() as db:
            db.execute(
                "update branch_commits set summary = %s where id = %s",
                (summary, commit_id),
            )
    except Exception:
        pass


def schedule_llm_summary(commit_id: int, player_text: str, gm_text: str) -> None:
    """fire-and-forget 触发 LLM 摘要后台任务。"""
    if not commit_id or not (player_text or gm_text):
        return
    try:
        _SUMMARY_POOL.submit(_run_llm_summary, int(commit_id), player_text or "", gm_text or "")
    except Exception:
        pass
