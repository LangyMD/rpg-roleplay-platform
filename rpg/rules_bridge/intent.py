"""intent.py — 战斗意图分类器 (deterministic, no LLM)。"""
from __future__ import annotations

import re

# Bug 2 (retest)：哪些中文动词算"移动意图"。
# "观察 / 留意 / 倾听 / 检查"等是原地行为，不应触发跨房候选。
# "靠近 / 沿 / 往 / 向 / 去 / 前往 / 走向 / 进入 / 穿过"等才是真正的移动。
_MOVEMENT_VERBS = (
    "靠近", "前往", "走向", "走到", "走过", "穿过", "翻过", "回到", "进入", "退回",
    "去", "沿", "往", "向", "通过", "潜入", "溜过去", "钻进", "上到", "下到",
)
# English movement verbs (word-boundary; in-place verbs like look/listen/inspect excluded).
_EN_MOVEMENT_RE = re.compile(
    r"\b(?:go|goes|going|went|head|heading|headed|walk|walking|move|moving|enter|entering"
    r"|approach|approaching|climb|climbing|descend|descending|ascend|ascending|follow|following"
    r"|cross|crossing|proceed|proceeding|travel|travelling|traveling|return|returning|sneak|sneaking"
    r"|slip|slipping|crawl|crawling|run|running|make my way|step (?:into|through|inside|out)"
    r"|go (?:up|down|back|through|inside|outside)|toward|towards|into)\b",
    re.IGNORECASE,
)
_EN_DIRECTIONS = (
    ("east", ("east",)), ("west", ("west",)), ("north", ("north",)), ("south", ("south",)),
    ("down", ("down", "descend", "lower", "below", "stair")),
    ("up", ("up", "ascend", "upper", "above", "stair")),
)
_EN_LABEL_STOP = frozenset(("the", "and", "of", "to", "a", "an", "path", "way", "door", "exit"))

# ── 战斗意图分类器 (5E module_adventure hard gate) ───────────────────────
#
# 现场 bug:玩家在 minecart_track (room.enemies=[]、encounter.active=False) 输入
#   "借着矿车阻挡,向后拉开距离继续放箭"
# GM 直接叙事:矿车变阻挡 / 玩家被卡住 / 两名敌人贴身 / 短弓难施展 / 陷入近战威胁。
# 这违反 "RulesEngine 是唯一规则真相源"。
#
# 此函数在 GM 被调用前对玩家文本做 deterministic 分类,返回:
#   None  — 不是战斗意图 → 正常 GM 叙事流程
#   {"kind": "no_target_combat", question, options}  — 想战斗但没合法敌人 → 阻挡 GM
#   {"kind": "combat_pending_question", question, options}  — encounter 中含糊战斗 → 阻挡 GM
#
# 全部 deterministic、不调 LLM;符合 "项目接 API 玩,不能依赖模型训练" 要求。
# 调用方 (app.py chat SSE) 收到非 None 时,直接写 pending_question + 提前结束,
# **不调主 GM**,杜绝任何 "GM 把坏结果写正文" 的可能。

_ATTACK_PHRASES = (
    "攻击", "射击", "射杀", "袭击", "开火", "放箭", "出手攻击", "突袭",
)
# 紧邻武器名时,这些"软动词"才算攻击 (避免 "射" 单独命中 "反射 / 投射 / 注射" 等)
_ATTACK_SOFT_VERBS = ("射", "放", "瞄准", "拉弓", "扣弦", "投掷", "掷", "扔",
                      "砍", "刺", "戳", "杀", "斩")
_RANGED_WEAPON_HINTS = ("短弓", "长弓", "弩", "弓箭", "弓", "箭", "标枪", "飞刀", "远程")
_MELEE_WEAPON_HINTS = ("短剑", "长剑", "匕首", "战斧", "战锤", "短棍", "近战", "肉搏")
_DISENGAGE_HINTS = ("脱离", "脱身", "Disengage", "解除接触", "解开接触")
_DODGE_HINTS = ("闪避", "防御姿态", "Dodge", "招架")
# 让玩家"远离敌人"的措辞 (5E 触发借机攻击的关键)
_MOVE_AWAY_HINTS = (
    "拉开距离", "拉远距离", "拉远", "保持距离",
    "后退", "退后", "退开", "退一步", "退两步", "向后", "往后",
    "远离", "撤离", "撤退", "脱身",
)

# English equivalents (word-boundary regexes on the raw text; Chinese tuples above unchanged).
_EN_ATTACK_RE = re.compile(
    r"\b(?:attack|attacks|attacking|shoot|shoots|shooting|shot at|open fire|fire at|loose an arrow"
    r"|stab|stabs|stabbing|slash|slashes|slashing|kill|ambush)\b", re.IGNORECASE)
_EN_ATTACK_SOFT_RE = re.compile(
    r"\b(?:fire|aim|aiming|draw|swing|swinging|throw|throwing|hurl|strike|cut|thrust)\b", re.IGNORECASE)
_EN_RANGED_RE = re.compile(
    r"\b(?:shortbow|longbow|crossbow|bow|arrows?|bolts?|javelins?|throwing knife|throwing knives"
    r"|ranged)\b", re.IGNORECASE)
_EN_MELEE_RE = re.compile(
    r"\b(?:shortsword|short sword|longsword|long sword|sword|dagger|axe|battleaxe|warhammer|hammer"
    r"|club|mace|melee|hand-to-hand|fists?)\b", re.IGNORECASE)
_EN_DISENGAGE_RE = re.compile(r"\b(?:disengag\w*|break (?:away|contact))\b", re.IGNORECASE)
_EN_DODGE_RE = re.compile(r"\b(?:dodge|dodging|parry|parrying|defensive stance)\b", re.IGNORECASE)
_EN_MOVE_AWAY_RE = re.compile(
    r"\b(?:back away|backing away|back off|step back|steps back|stepping back|fall back|falling back"
    r"|retreat|retreating|withdraw|withdrawing|keep (?:my |our )?distance|put (?:some )?distance"
    r"|get (?:some )?distance|move away|get away from|pull back|backpedal)\b", re.IGNORECASE)


def _has_movement_intent(text: str) -> bool:
    """玩家文本是否明确包含移动到另一处的动词。
    用于决定是否做跨房间 skill check 推断（如 stealth 到相邻房间）。"""
    if not text:
        return False
    return any(v in text for v in _MOVEMENT_VERBS) or bool(_EN_MOVEMENT_RE.search(text))


def _direction_to_exit(text: str, current_room: dict) -> str | None:
    """Bug 4：把玩家自然语言移动意图（如「沿外侧锈轨往东」「进入主井」）
    解析为当前房间真实 exit id。优先全词匹配 exit.label / id，再做 token 模糊匹配。"""
    exits = current_room.get("exits") or []
    if not exits:
        return None
    text_lower = text.lower()
    best_id = None
    best_score = 0
    for ex in exits:
        to_id = str(ex.get("to") or "")
        label = str(ex.get("label") or "")
        score = 0
        # 玩家说的字串里包含 label 主干（如"外侧锈轨"、"主井"）→ 强匹配
        for token in re.findall(r"[一-鿿]{2,}", label):
            if token in text:
                score += 3
        # 中文方向词
        for direction, exit_keywords in (
            ("东", ["东"]), ("西", ["西"]), ("北", ["北"]), ("南", ["南"]),
            ("下", ["下", "降"]), ("上", ["上", "升"]),
        ):
            if direction in text and any(kw in label for kw in exit_keywords):
                score += 2
        # English label words ("the north tunnel" vs "head into the tunnel")
        label_lower = label.lower()
        for word in re.findall(r"[a-z]{3,}", label_lower):
            if word not in _EN_LABEL_STOP and re.search(r"\b" + re.escape(word), text_lower):
                score += 3
        # English direction words
        for direction, exit_keywords in _EN_DIRECTIONS:
            if re.search(r"\b" + direction + r"(?:ward|wards|ern)?\b", text_lower) and any(
                re.search(r"\b" + kw, label_lower) or re.search(r"\b" + kw, to_id.lower())
                for kw in exit_keywords
            ):
                score += 2
        # 英文 fallback
        if to_id and to_id.lower() in text_lower:
            score += 5
        if score > best_score:
            best_score = score
            best_id = to_id
    return best_id if (best_id and best_score >= 2) else None


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _detect_ranged_weapon(text: str) -> bool:
    return _has_any(text, _RANGED_WEAPON_HINTS) or bool(_EN_RANGED_RE.search(text))


def _detect_melee_weapon(text: str) -> bool:
    return _has_any(text, _MELEE_WEAPON_HINTS) or bool(_EN_MELEE_RE.search(text))


def _detect_attack_verb(text: str) -> bool:
    """攻击意图。整词命中 (如"攻击 / 射击") 或软动词 + 武器名同现。"""
    if _has_any(text, _ATTACK_PHRASES) or _EN_ATTACK_RE.search(text):
        return True
    # "我用短弓射" / "拔短剑刺" 这种 — 软动词紧贴武器名
    has_soft = _has_any(text, _ATTACK_SOFT_VERBS) or bool(_EN_ATTACK_SOFT_RE.search(text))
    has_weapon = _detect_ranged_weapon(text) or _detect_melee_weapon(text)
    return has_soft and has_weapon


def _detect_move_away(text: str) -> bool:
    return _has_any(text, _MOVE_AWAY_HINTS) or bool(_EN_MOVE_AWAY_RE.search(text))


def _detect_disengage(text: str) -> bool:
    return _has_any(text, _DISENGAGE_HINTS) or bool(_EN_DISENGAGE_RE.search(text))


def _detect_dodge(text: str) -> bool:
    return _has_any(text, _DODGE_HINTS) or bool(_EN_DODGE_RE.search(text))


def classify_combat_intent(text: str, state) -> dict | None:
    """deterministic 战斗意图分类。详见模块顶注释。

    Returns None / {"kind": "no_target_combat" | "combat_pending_question", ...}.

    设计原则:
    - 单一明确的攻击 (无 move_away) → 不拦截,让 suggest_rule_actions 走 attack
    - 仅在 (无敌人 + 想战斗) 或 (encounter 中 + 含糊战斗) 时返回阻挡块
    """
    if not text or not isinstance(text, str):
        return None

    # 只对模组场景生效;小说/自由叙事不拦截 (避免误伤纯文学描写)
    scene = state.data.get("scene") or {}
    if not scene.get("module_id"):
        return None

    has_attack = _detect_attack_verb(text)
    has_ranged = _detect_ranged_weapon(text)
    has_melee = _detect_melee_weapon(text)
    has_move_away = _detect_move_away(text)
    has_disengage = _detect_disengage(text)
    _detect_dodge(text)

    # 完全没有战斗 / 远程 / 近战 / 离场 信号 → 不关我事
    if not (has_attack or has_ranged or has_melee or has_move_away):
        return None

    enc = state.data.get("encounter") or {}
    encounter_active = bool(enc.get("active"))
    live_enemies = [
        c for c in (enc.get("combatants") or [])
        if c.get("side") == "enemy" and not c.get("defeated")
    ]

    current_room = scene.get("current_room") or {}
    room_enemies = current_room.get("enemies") or []

    # ──────── case 1: 想战斗 / 攻击,但当前没合法敌人 ────────
    # room.enemies=[] AND encounter.active=False AND 玩家文本里有攻击/武器
    # → GM 不允许"幻觉敌人出来"。强制 pending_question。
    wants_combat = has_attack or has_ranged or has_melee
    if wants_combat and not encounter_active and not room_enemies:
        return {
            "kind": "no_target_combat",
            "question": "You ready yourself for a fight, but there is no clear enemy or target in sight. What do you do first?",
            "options": [
                "Look around carefully",
                "Advance slowly, staying alert",
                "Call out or make a noise to test the area",
                "Stay hidden and keep exploring",
            ],
            "source": "rules_engine",
            "reason": "wants_combat 但无敌人 + 无 encounter — GM 不应幻觉敌人",
            "signals": {
                "has_attack": has_attack, "has_ranged": has_ranged,
                "has_melee": has_melee, "room_enemies": len(room_enemies),
                "encounter_active": encounter_active,
            },
        }

    # ──────── case 2: encounter 中,move_away + ranged 同时出现 ────────
    # 5E:在敌人的 melee reach 内用远程武器要 disadvantage,直接移动要触发借机攻击。
    # 玩家想"边退边射"是经典含糊意图,必须明确选择策略。
    if encounter_active and live_enemies and has_move_away and has_ranged and not has_disengage:
        enemy_names = ", ".join(
            (e.get("name") or e.get("id") or "enemy") for e in live_enemies[:3]
        )
        return {
            "kind": "combat_pending_question",
            "question": (
                f"Enemies ({enemy_names}) are within melee reach (~5 ft). "
                "A shortbow attack at this range has disadvantage; simply backing away provokes "
                "an opportunity attack. Choose one:"
            ),
            "options": [
                "Disengage and withdraw (uses your action, no opportunity attack)",
                "Just back away (the enemy gets 1 opportunity attack, then you leave)",
                "Switch to melee (shortsword) and strike where you stand",
                "Shoot the shortbow from here (attack with disadvantage)",
            ],
            "source": "rules_engine",
            "reason": "encounter 中含糊战斗: move_away + ranged 同现",
            "signals": {
                "encounter_active": encounter_active,
                "live_enemies": len(live_enemies),
                "has_move_away": has_move_away, "has_ranged": has_ranged,
            },
        }

    # ──────── case 3: encounter 中,只 move_away 没说怎么处理敌人 ────────
    # 比 case 2 弱 — 玩家没明示用什么武器,但还是要选 Disengage / 借机后退 / 留下。
    if encounter_active and live_enemies and has_move_away and not has_disengage:
        enemy_names = ", ".join(
            (e.get("name") or e.get("id") or "enemy") for e in live_enemies[:3]
        )
        return {
            "kind": "combat_pending_question",
            "question": (
                f"You want to leave the threat range of the enemies ({enemy_names}), "
                "but haven't said how you'll handle the opportunity attack:"
            ),
            "options": [
                "Disengage and withdraw (uses your action, no opportunity attack)",
                "Just back away (take the opportunity attack)",
                "Stay put and take a different action",
            ],
            "source": "rules_engine",
            "reason": "encounter 中含糊离场",
            "signals": {
                "encounter_active": encounter_active,
                "live_enemies": len(live_enemies),
                "has_move_away": has_move_away,
            },
        }

    return None
