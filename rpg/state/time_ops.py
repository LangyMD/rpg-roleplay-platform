"""state/time_ops.py — 时间相关 helpers (_gm_is_asking_for_time_confirm, _clean_time_value, _looks_like_time_value, _format_pending_timeline, _phase_for_time)"""
from __future__ import annotations

from timeline_state import clean_time_value, looks_like_time_value

_ASKING_FOR_CONFIRM_PATTERNS = (
    r"是否(?:要|要不要|确认|继续|推进|跳到|跳转)",
    r"请(?:玩家|你)?(?:确认|选择|决定|回答)",
    r"等(?:待|待玩家)?(?:玩家|你)?(?:确认|选择|决定|回答|回应)",
    r"待确认",
    r"awaiting[_ ]?(?:gm|player)?[_ ]?confirm",
    r"pending[_ ]?confirm",
    r"询问玩家",
    r"向玩家提问",
    r"先(?:让|请)?(?:子代理|GM|你)?(?:检查|确认|核对)",
    r"不要(?:直接|立即)?(?:跳过|改写|锁定)",
    # English equivalents (narration language defaults to English)
    r"\b(?:should|shall) (?:we|i) (?:skip|jump|advance|fast[- ]forward)",
    r"\b(?:do|would) you (?:want|like) (?:me )?to (?:skip|jump|advance|fast[- ]forward)",
    r"\bplease (?:confirm|choose|decide)\b",
    r"\b(?:waiting|wait) for (?:the )?player'?s? (?:to )?(?:confirm|confirmation|answer|choice|choose|decision|decide|response|respond)",
    r"\bpending (?:player )?confirmation\b",
    r"\bask(?:ing)? the player\b",
    r"\bdo not (?:directly |immediately )?(?:skip|rewrite|lock)\b",
)


def _gm_is_asking_for_time_confirm(gm_response: str, tags: list[str]) -> bool:
    """task 22 + task 32：判断 GM 这一轮是在询问/标 pending，而不是在锁定时间。

    task 32 真实案例：GM 同时输出了 `【时间跳跃确认：待确认（当前处于 pending_confirmation 状态）】`
    和 `【询问玩家：...】`/`【设定校验：冲突】`。原 task 22 实现一旦看到任何含
    "时间跳跃确认" 的标签就立刻 return False，把后面所有"等待玩家回答""冲突"信号全无视，
    导致主 GM 锁定时间线。

    新规则（更保守）：
      1. 先扫一遍 tags 把信号分类：
         - has_explicit_confirm  ← "时间跳跃确认" 且 value 里没有 pending/待确认 等回退措辞
         - has_pending_signal    ← 任一意图标 OR "时间跳跃确认" 的 value 含 pending/待确认 OR "等待玩家"等
      2. 正文里如果命中 _ASKING_FOR_CONFIRM_PATTERNS → 也算 pending 信号
      3. has_pending_signal 优先于 has_explicit_confirm（user 报告里两者会同时出现）
    """
    import re
    blob = gm_response or ""
    has_explicit_confirm = False
    has_pending_signal = False

    pending_value_markers = ("待确认", "未确认", "暂不", "暂缓", "pending", "awaiting",
                             "unconfirmed", "not confirmed", "on hold", "deferred")
    pending_tag_keywords = (
        "询问玩家", "向玩家提问", "澄清问题",
        "时间跳跃待确认", "时间提案", "时间冲突",
        "设定冲突", "设定校验",  # 冲突/校验通常表示"先不要写入"
        "等待玩家回答", "等待玩家",
        "ask player", "asking player", "question for player", "clarifying question",
        "time jump pending", "time proposal", "time conflict",
        "setting conflict", "setting check", "awaiting player", "waiting for player",
    )

    for tag in tags or []:
        if not tag:
            continue
        # 把 "key：value" 拆开看 value
        if "：" in tag:
            _key, _val = tag.split("：", 1)
        elif ":" in tag:
            _key, _val = tag.split(":", 1)
        else:
            _key, _val = tag, ""
        if "时间跳跃确认" in _key or "时间跳跃确认" in tag or "time jump confirm" in tag.lower():
            val_low = _val.lower()
            # value 里出现"待确认/pending/awaiting"=不是真的同意确认
            if any(m in _val for m in pending_value_markers) or any(m in val_low for m in pending_value_markers):
                has_pending_signal = True
            else:
                has_explicit_confirm = True
            continue
        if any(kw in tag or kw in tag.lower() for kw in pending_tag_keywords):
            has_pending_signal = True

    if not has_pending_signal:
        for pat in _ASKING_FOR_CONFIRM_PATTERNS:
            if re.search(pat, blob, flags=re.IGNORECASE):
                has_pending_signal = True
                break

    # 关键决定：pending 信号优先；只有完全没有 pending 信号且有显式 confirm 才视为真确认
    if has_pending_signal:
        return True
    if has_explicit_confirm:
        return False
    # 兼容老返回值：纯正文询问也算 asking
    return False


def _clean_time_value(text: str) -> str:
    return clean_time_value(text)


def _looks_like_time_value(value: str) -> bool:
    return looks_like_time_value(value)


def _format_pending_timeline(pending: dict | None) -> str:
    if not pending:
        return "none"
    return f"{pending.get('from', '')} → {pending.get('to', '')}"


def _phase_for_time(time_desc: str) -> str:
    """从时间描述推断 phase 标签。

    通用 fallback:任何剧本都用 "玩家分支" 这个中性标签。
    真实的 phase 解析走 rpg/script_timeline.py 的 resolve_timeline_anchor —
    在 chat handler 里把 anchor.story_phase 写到 state.world.timeline.current_phase,
    覆盖本函数的 fallback。

    之前这里 hardcoded 柏林剧本专有词("柏林/图卢兹/哈布斯堡/北城/内城/基地"
    → "柏林暗流篇"),完全无法泛化到别的剧本。已删。
    """
    return "Player branch"


# ── 时间连续性护栏 v0(天数倒退检测)─────────────────────────────────────
# 哲学同星期验错器(a80ef39d8):确定性检测→surface 提示,不拦截不改写;标签里
# 解析不出「第N天」就休眠(玄幻/无天数计法的存档零副作用)。

_DAY_NUM_RE = None  # 惰性编译

_CJK_DIGITS = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
               "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cjk_to_int(s: str) -> int | None:
    """常见中文数字→int(支持到 999:三/十/二十三/一百零五/首)。解析不出返 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return None
    total = 0
    section = 0
    num = 0
    for ch in s:
        if ch in _CJK_DIGITS:
            num = _CJK_DIGITS[ch]
        elif ch == "十":
            section += (num if num else 1) * 10
            num = 0
        elif ch == "百":
            section += (num if num else 1) * 100
            num = 0
        else:
            return None
    total = section + num
    return total if total > 0 or s == "零" else None


_EN_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}
_EN_CARDINALS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30,
}
_EN_DAY_RES = None  # 惰性编译


def _en_day_number(label: str) -> int | None:
    """English day counters: "Day 3", "day three", "3rd day", "the third day". None if absent.
    Deliberately does not match "Day of the Dead"/"today"/"days later" (no counter → dormant)."""
    global _EN_DAY_RES
    import re as _re
    if _EN_DAY_RES is None:
        _EN_DAY_RES = (
            _re.compile(r"\bday\s+(\d{1,3})\b", _re.I),
            _re.compile(r"\b(\d{1,3})(?:st|nd|rd|th)\s+day\b", _re.I),
            _re.compile(r"\bday\s+(" + "|".join(_EN_CARDINALS) + r")\b", _re.I),
            _re.compile(r"\b(" + "|".join(_EN_ORDINALS) + r")\s+day\b", _re.I),
        )
    for rx in _EN_DAY_RES:
        m = rx.search(label or "")
        if not m:
            continue
        tok = m.group(1).lower()
        if tok.isdigit():
            return int(tok)
        return _EN_CARDINALS.get(tok) or _EN_ORDINALS.get(tok)
    return None


def _day_number(label: str) -> int | None:
    """从时间标签抽「第N天」的 N(also English "Day N"/"Nth day")。抽不出(无天数计法)返 None=护栏休眠。"""
    global _DAY_NUM_RE
    import re as _re
    if _DAY_NUM_RE is None:
        _DAY_NUM_RE = _re.compile(r"第([0-9零一两二三四五六七八九十百]+)天")
    m = _DAY_NUM_RE.search(label or "")
    if not m:
        return _en_day_number(label or "")
    return _cjk_to_int(m.group(1))


def detect_day_regression(old_label: str, new_label: str) -> str | None:
    """新时间标签的天数计数比旧的小 → 返回警示文案;否则 None。

    只在新旧标签【都】带可解析的「第N天」时才判(缺任一侧=休眠,零误伤);
    倒退是强信号(梦境/回忆通常不重置天数计法,生产 t18「第四天·入夜⟶梦境」
    后仍是「第五天」)。文案不拦截:有意的设定回调(玩家 /set 改写)可忽略。
    """
    old_day = _day_number(old_label or "")
    new_day = _day_number(new_label or "")
    if old_day is None or new_day is None:
        return None
    if new_day < old_day:
        return (
            f"Time appears to have gone backwards (Day {old_day} -> Day {new_day}). "
            "Unless the player deliberately rewound the setting, consider /retry or use /set to fix the timeline."
        )
    return None
