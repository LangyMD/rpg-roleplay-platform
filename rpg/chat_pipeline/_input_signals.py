"""玩家输入的确定性分类信号(短输入镜头规则 / 「继续」推进 / 沉浸式开关)。
纯函数 + 常量;env 阈值 RPG_SHORT_INPUT_CHARS 在此计算。拆包自 chat_pipeline.py,行为零变化。"""

from __future__ import annotations

import os

# 反馈 #28:玩家短输入(<= N 字)→ 该回合前置「镜头规则」元指令,避免 GM 扩写玩家自己的
# 动作而忽略对方反应。阈值可用 RPG_SHORT_INPUT_CHARS 调(默认 30,覆盖绝大多数单动作短 RP)。
try:
    _SHORT_INPUT_CHARS = max(0, int(os.environ.get("RPG_SHORT_INPUT_CHARS", "30")))
except (TypeError, ValueError):
    _SHORT_INPUT_CHARS = 30
# 不含 CJK 的输入(英文等字母文字)按字符计同样意思要长得多:单独阈值,默认 80 字符
# (≈ 一两句简短动作,如 "I nod and glance at her, saying nothing.")。RPG_SHORT_INPUT_CHARS_LATIN 可调。
try:
    _SHORT_INPUT_CHARS_LATIN = max(0, int(os.environ.get("RPG_SHORT_INPUT_CHARS_LATIN", "80")))
except (TypeError, ValueError):
    _SHORT_INPUT_CHARS_LATIN = 80


def _has_cjk(text: str) -> bool:
    return any("\u3400" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff" or "\uac00" <= ch <= "\ud7af"
               for ch in text)


_SHORT_INPUT_DIRECTIVE = (
    "【Meta-instruction for this turn: camera rule (top priority; obey silently; never restate or confirm this to the player)】\n"
    "The player's input this turn is very short. That is the signal \"I do this / react like this — and then?\": what the player wants to see is "
    "**how the other NPCs and the world respond**, not you restating, embellishing or expanding their short action into a long passage. Follow strictly:\n"
    "1. Acknowledge the player's action / reaction in one or two sentences at most; never restate it at length or add drama for them (do not invent their inner thoughts, "
    "add lines for them, or extend follow-up actions they did not write).\n"
    "2. The narrative focus this turn = the other NPCs' concrete reactions to that action (expressions, words, body language, shifts in emotion and stance) plus "
    "the consequences and progression of the environment / situation.\n"
    "3. End on a tense scene beat on the other side's / the world's side, naturally handing the ball back to the player, rather than stopping on "
    "the player's own action."
)


# 「继续」按钮固定文案(game-composer continue_text,中英)。群反馈(行者无疆):该 7 字文案
# 命中短输入镜头规则→GM 被指令「聚焦对方反应、原地收尾」,与按钮 hover 承诺「推进一段剧情」
# 语义完全相反 = 点继续必水文。确定性识别(固定文案精确匹配,非语义猜测)。
_CONTINUE_CORE_TEXTS = ("继续推进剧情", "Continue the scene")


def _is_continue_request(raw_msg: str | None) -> bool:
    """「继续」按钮固定文案的确定性识别。剥首尾全/半角括号后精确匹配。纯函数。"""
    r = (raw_msg or "").strip()
    if not r:
        return False
    r = r.strip("()（）").strip()
    return r in _CONTINUE_CORE_TEXTS


_CONTINUE_DIRECTIVE = (
    "【Meta-instruction for this turn: progression rule (top priority; obey silently; never restate or confirm this to the player)】\n"
    "This turn the player handed narrative control entirely to you (they clicked \"Continue the scene\"). This is not a short reply but an explicit request "
    "for the story to move forward. Follow strictly:\n"
    "1. The story must move forward: time may pass, the scene may change, events may happen; do not linger on atmosphere, "
    "restate the current situation or write only inner thoughts.\n"
    "2. If the context gives a story soft goal / next beat / pending anchor, prioritize developments that lead toward it "
    "(at the intensity its injected level calls for).\n"
    "3. End with a new situation or decision point, handing the ball back to the player."
)


def _should_inject_short_input_directive(raw_msg: str | None) -> bool:
    """反馈 #28:确定性判定本回合是否为「短 RP 输入」需要注入镜头规则元指令。

    True 当且仅当:非空、非斜杠命令(/set /reveal 等)、strip 后长度 <= 阈值、
    且不是「继续」按钮固定文案(其语义=请求推进,与镜头规则相反,由推进规则接管)。
    纯函数,便于单测与回归锁定。"""
    r = (raw_msg or "").strip()
    if not r or r.startswith("/"):
        return False
    if _is_continue_request(r):
        return False
    return len(r) <= (_SHORT_INPUT_CHARS if _has_cjk(r) else _SHORT_INPUT_CHARS_LATIN)


# 沉浸式拟人模式:玩家明确开/关请求的【确定性】识别(harness 确定性铁律:不指望 LLM 工具一定被调)。
# 返回 True(开)/ False(关)/ None(未提)。短语集刻意收紧,降低误判;且这是可逆的本对话偏好。
_IMMERSIVE_OFF_PHRASES = ("关掉沉浸", "关闭沉浸", "退出沉浸", "取消沉浸", "别沉浸", "不要沉浸",
                          "回到正常叙事", "回到小说", "正常叙事模式", "恢复叙事")
_IMMERSIVE_ON_PHRASES = ("沉浸式", "像真人一样", "当成真人", "当作真人", "别写成小说", "不要写成小说",
                         "别像小说", "别用小说", "别替我说", "别帮我说", "不要替我", "别替我做",
                         "别帮我做决定", "以第一人称", "用第一人称")
# English equivalents(小写子串匹配;同样刻意收紧:不收裸词 "immersive",避免误判)。
_IMMERSIVE_OFF_PHRASES_EN = ("turn off immersive", "turn immersive off", "exit immersive", "leave immersive",
                             "stop immersive", "disable immersive", "immersive mode off", "no more immersive",
                             "back to normal narration", "back to narration", "back to the novel",
                             "normal narration mode", "resume narration")
_IMMERSIVE_ON_PHRASES_EN = ("immersive mode", "go immersive", "be immersive", "like a real person",
                            "don't write it like a novel", "don't write like a novel", "stop writing like a novel",
                            "not like a novel", "don't speak for me", "don't talk for me", "stop speaking for me",
                            "don't act for me", "don't decide for me", "stop deciding for me",
                            "in first person", "in the first person")


def _immersive_request(raw_msg: str | None) -> bool | None:
    t = (raw_msg or "").strip()
    if not t or t.startswith("/"):
        return None
    low = t.lower().replace("\u2019", "'")
    if any(k in t for k in _IMMERSIVE_OFF_PHRASES) or any(k in low for k in _IMMERSIVE_OFF_PHRASES_EN):
        return False   # 先判关闭(『关掉沉浸式』含『沉浸』;"turn off immersive mode" 含 "immersive mode")
    if any(k in t for k in _IMMERSIVE_ON_PHRASES) or any(k in low for k in _IMMERSIVE_ON_PHRASES_EN):
        return True
    return None
