"""context_engine.helpers — 小工具函数."""
from __future__ import annotations


def _neutralize_state_write_tags(text: str) -> str:
    """P0 #2：从检索内容里中和 `【状态写入：…】` / `【询问：…】` /
    `【时间推进：…】` 等会被 apply_structured_updates 当作 GM 写状态指令
    的标签。原文如果包含这类装饰括号，主 GM 在转述时会原样复述，
    apply_structured_updates 在 GM 输出上跑 re.findall(r"【([^】]+)】")
    就会把章节里的"假指令"当成真状态写入执行。

    修法：把检索内容里的 `【` `】` 替换成视觉上接近但 GM 解析时不会
    被识别的全形括号（U+FF3B / U+FF3D），保持人类可读的同时切断指令链路。
    """
    if not text:
        return text
    return text.replace("【", "［").replace("】", "］")


def _pending_jump_warning_text(state) -> str:
    """通用 pending_jump 警告：state 含 pending_confirmation 时，GM 必须遵守。
    这是 GM 运行契约的一部分，与 ContentPack 类型无关。
    novel-specific 的 anchor 信息由 NovelTimelineProvider 负责。"""
    data = getattr(state, "data", state) or {}
    timeline = (data.get("world") or {}).get("timeline") or {}
    pending = timeline.get("pending_jump") or {}
    if not pending:
        return ""
    pending_status = str(pending.get("status") or "")
    is_awaiting = pending_status in ("awaiting_gm_confirmation", "awaiting", "pending_confirmation")
    lines = [
        f"Player requested a time jump: {pending.get('from', '')} -> {pending.get('to', '')}",
        f"pending status: {pending_status or 'unknown'}",
    ]
    if is_awaiting:
        lines.extend([
            "⚠ This turn anchor_state=pending_confirmation: do NOT treat the future time/place the player requested as something that has already happened.",
            "Do not write anything that moves the scene forward to the target time ('The next morning...', 'The following day...', 'Before you know it...', etc.);",
            "do not output the tags 【时间跳跃确认：…】【当前时间线：<target time>】【当前位置：<new place>】【时间：<target time>】;",
            "do not give dialogue, actions or options set in the 'new time / new place' scene.",
            "This turn you may only: (1) give a conflict check; (2) list risks / costs / prerequisites; "
            "(3) output 【询问玩家：Confirm the jump to <target time>?】 + 1-3 clear options (confirm / cancel / change the target).",
            "Only if the player clearly replies 'confirm' or /confirm next turn do you actually advance the timeline and the scene.",
        ])
    else:
        lines.extend([
            "This turn you must deal with the time jump first. By default, respect the player's intent to jump or change course;",
            "if you accept, write the transition / landing point and output 【时间跳跃确认：<target time>】 and 【当前时间线：<target time>】;",
            "only output 【询问玩家：...】 if the target cannot be interpreted at all.",
            "Until it is confirmed, do not treat the requested future time as already happened; only after confirmation may you advance the scene and update location / objective.",
        ])
    return "\n".join(lines)
