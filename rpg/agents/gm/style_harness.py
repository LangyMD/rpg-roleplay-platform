"""agents.gm.style_harness — GM 叙事「倾向性」线性可调底座(Phase 1)。

背景(用户需求):GM 的行为规则里,有一类是**审美倾向**(回应篇幅、镜头焦点、戏剧
密度、心理补写、悬念强度、剧情引导力度),原先以一刀切的硬编码写死在 _SYSTEM_BASE,
"一棒子打死",无法因人/因局调整。本模块把这 6 个维度抽成**线性旋钮**(0-100),由
旋钮值**确定性地**渲染出对应的提示词片段(数值插值 + 分级措辞),而非靠提示词求 LLM
"听话"。安全/正确性铁律(专名忠实、防剧透、信息不对称、玩家自主权、世界线必发生、
NSFW)不在本模块,永远硬编码。

Phase 1 只做:旋钮 schema + render_style_block + 四层 resolve 占位 + 默认值复刻现状。
默认 profile 渲染出的「# 叙事风格(本局)」段,在语义与关键数字上等价于原硬规则,
保证零回归。Phase 2 接配置存储(script_overrides.gm_style / 用户级 / 存档级),
Phase 3 接前端滑块 + 确定性后处理(按旋钮加权截断/校验)。
"""
from __future__ import annotations

from typing import Any

# ── 旋钮 schema ───────────────────────────────────────────────────────────────
# 每个旋钮:0-100 线性。default 复刻当前硬编码行为。
# lo/hi 给"数值插值"型旋钮的两端取值(如篇幅字数);levels 给"分级措辞"型旋钮的档位文案。

KNOBS: dict[str, dict[str, Any]] = {
    # 正文篇幅:数值插值。默认 45 → 约 300-450 字(复刻"≥300字实质推进"绑定规则)。
    "reply_length": {
        "default": 45,
        "lo": 80,    # knob=0  → ~80 words(原 ~120 字)
        "hi": 600,   # knob=100 → ~600 words(原 ~900 字)
    },
    # 镜头焦点(#28 维度):玩家动作 vs 对方反应的篇幅占比。默认 15 → 强对方反应优先。
    "player_action_focus": {"default": 15},
    # 戏剧密度:镜像玩家 vs 允许放大。默认 35 → 镜像不放大(复刻 task131 规则)。
    "drama_density": {"default": 35},
    # 心理/潜台词补写:字面处理 vs 主动补内心戏。默认 20 → 字面处理(复刻"不补潜台词")。
    "interiority": {"default": 20},
    # 结尾悬念强度:平稳收束 vs 强钩子留白。默认 60 → 有张力的留白(复刻留白铁律)。
    "cliffhanger": {"default": 60},
    # 剧情引导力度:高自由 vs 强收束往锚点引。默认 60 → 主动推进+适度收束。
    "guidance_force": {"default": 60},
}


def default_profile() -> dict[str, int]:
    return {k: int(v["default"]) for k, v in KNOBS.items()}


def _clamp(v: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def normalize_profile(profile: dict[str, Any] | None) -> dict[str, int]:
    """把任意(可能缺键/越界/None)profile 归一到完整、0-100 的 6 维 dict。缺键取默认。"""
    out = default_profile()
    if isinstance(profile, dict):
        for k in KNOBS:
            if k in profile and profile[k] is not None:
                out[k] = _clamp(profile[k])
    return out


def validate_patch(patch: Any) -> dict[str, int]:
    """校验前端/API 传来的 gm_style patch:只接受已知 6 键、值归一到 0-100 整数,
    未知键忽略。用于写端点入参清洗。空/非 dict → ValueError。"""
    if not isinstance(patch, dict):
        raise ValueError("gm_style must be an object (6 knob keys -> integers 0-100)")
    out: dict[str, int] = {}
    for k, v in patch.items():
        if k in KNOBS and v is not None:
            out[k] = _clamp(v)
    return out


def _lerp(lo: int, hi: int, knob: int) -> int:
    return int(round(lo + (hi - lo) * (knob / 100.0)))


def _band(knob: int) -> int:
    """0-100 → 档位 0..4(五档),供分级措辞选择。"""
    return min(4, knob // 20)


# 各维度的分级措辞(五档:0-19 / 20-39 / 40-59 / 60-79 / 80-100)。
# 索引 = _band(knob)。默认值落在的那一档即"复刻现状"的文案。

_FOCUS_LEVELS = [
    # default 15 → band 0:强对方反应优先(复刻镜头铁律行162)
    "The body of the prose covers **how the other NPCs and the world react to, answer and are affected by the player's action** — expressions, words, body language, shifts in emotion and stance, changes in the environment / situation; acknowledge the player's own action in one or two sentences at most, and never add lines, inner thoughts or follow-up actions the player didn't write. The shorter the player's input, the more clearly they are waiting for a reaction, and the less you should spend the length dramatizing their action.",
    "The prose centers on the other side's reactions and the consequences; a brief acknowledgment of the player's action is enough, and you do not extend actions or thoughts the player didn't write.",
    "Roughly half acknowledging the player's action and half the other side's reaction: advance their response faithfully, and you may give the player's action a sentence or two of textured description, but make no decisions the player didn't write.",
    "You may describe the unfolding, force and texture of the player's action in some detail, then write how others and the environment respond; still do not add lines or decisions the player didn't write.",
    "Focus on the process, details and tension of the player's action itself, with the other side's reaction as the backdrop; but never make unauthorized follow-up decisions for the player.",
]

_DRAMA_LEVELS = [
    "Dramatic density strictly mirrors the player's input this turn: if the player is understated, so are you; only when the player is intense are you intense. Do not escalate the current scene because the retrieved source text is dramatically dense; take state words in the player's brackets literally ('(passes out)' = faints, not dying).",
    # default 35 → band 1:基本镜像、略放大(复刻 task131"镜像而非放大")
    "Dramatic density basically mirrors the player's input, adding a very restrained touch of tension only where the plot naturally calls for it; do not escalate everyday scenes into source-style extreme events.",
    "Dramatic density may run one notch above the player's input: actively add tension and twists where reasonable, without departing from the real intensity of the current situation.",
    "You may noticeably amplify dramatic tension: actively create conflict, twists and emotional swings to make the scene more dramatic.",
    "High dramatic tension: actively escalate conflict and emotional intensity, aiming for strong dramatic effect (still without breaking the setting or the characters).",
]

_INTERIORITY_LEVELS = [
    "Describe only externally observable facts (actions, expressions, words, environment); do not add unfounded inner monologue, subtext or 'emotional undercurrents' for the player or NPCs.",
    # default 20 → band 1:字面为主,极少内心(复刻"不补潜台词")
    "Mostly external description; touch on a character's emotions very sparingly and only with clear grounds, without unfolding inner monologue.",
    "Moderately add NPCs' inner activity and subtext to help shape them; the player's inner life is still whatever the player wrote.",
    "Portray NPCs' psychology, motives and subtext more fully, so the characters feel more three-dimensional.",
    "Explore NPCs' inner drama and layers of subtext in depth; but the player character's inner life still reflects only what the player wrote.",
]

_CLIFF_LEVELS = [
    "Close this beat smoothly at the end, without deliberately creating suspense.",
    "End with a slight lingering note or something left unsaid.",
    "End on a gentle point of tension that naturally gives the player something to respond to.",
    # default 60 → band 3:有张力的留白(复刻留白铁律行158)
    "After advancing this turn, close on a tense scene beat — an NPC's action, a change in the environment, an unfinished sentence, an approaching threat — so the player naturally picks it up; in the vast majority of turns do not explicitly ask 'what do you do next?' at the end; only genuine branching choices get options, via the structured question popup.",
    "End with a strong hook: an imminent threat, a startling line or a sudden turn, creating strong suspense that pulls the player into the next turn (still without explicitly asking the player in the prose what they will do).",
]

_GUIDANCE_LEVELS = [
    "High freedom: let things unfold naturally from the player's actions, without actively pulling the story toward source anchors; give a little direction only when the player is clearly stuck.",
    "Player-led, occasionally nudging the story along toward the pending anchors when the moment allows.",
    "Actively advance the story: each turn, set the world / NPCs in motion first, and steer moderately toward the nearest pending anchor.",
    # default 60 → band 3:主动推进+收束(复刻推进铁律行157+收束行88)
    "Each turn, first move this turn forward according to the plot (NPCs act / events happen / the world reacts), and do not hand 'how should this develop' back to the player; when the player strays from the pending anchors, use fate-like devices such as coincidence / misunderstanding / intervention by others / environmental pressure to pull the story back to the nearest anchor within 1-3 turns, so the player doesn't feel strong-armed yet the anchor still happens.",
    "Strong convergence: continuously and actively push the story toward the pending anchors, markedly reducing freedom so the key beats happen as soon as possible (for when drift is too high and needs a strong pull back).",
]


def render_style_block(profile: dict[str, Any] | None) -> str:
    """旋钮 profile → 注入 system prompt 的「# 叙事风格(本局)」段。

    默认 profile 渲染出的内容,语义等价于 master.py 原先散落的 6 条硬规则
    (篇幅/镜头/戏剧密度/心理/悬念/引导),并带相同量级的字数目标。
    """
    p = normalize_profile(profile)
    target = _lerp(KNOBS["reply_length"]["lo"], KNOBS["reply_length"]["hi"], p["reply_length"])
    # 篇幅下限:默认档保留"实质推进、不敷衍"的硬约束(≥ 约 0.7*target)
    floor = int(round(target * 0.7))
    lines = [
        "# Narrative style (this game's adjustable tendencies — set by player preference; they do not affect the safety / correctness iron rules)",
        f"- Length: aim for about {floor}-{target} words of **substantive progress** in this turn's prose, with scene, action, dialogue and sensory detail that clearly moves the plot forward; never brush the player off with a sentence or two and then immediately throw out options.",
        f"- Camera focus: {_FOCUS_LEVELS[_band(p['player_action_focus'])]}",
        f"- Dramatic density: {_DRAMA_LEVELS[_band(p['drama_density'])]}",
        f"- Inner life and subtext: {_INTERIORITY_LEVELS[_band(p['interiority'])]}",
        f"- Endings and suspense: {_CLIFF_LEVELS[_band(p['cliffhanger'])]}",
        f"- Story progression and guidance: {_GUIDANCE_LEVELS[_band(p['guidance_force'])]}",
    ]
    return "\n".join(lines)


# ── 四层配置归并(Phase 2 接真实存储,Phase 1 先占位返回默认)──────────────────
def resolve_profile(
    user_id: int | None = None,
    script_id: int | None = None,
    save_id: int | None = None,
    *,
    platform_default: dict | None = None,
    user_default: dict | None = None,
    script_override: dict | None = None,
    save_override: dict | None = None,
) -> dict[str, int]:
    """四层归并:平台默认 → 用户默认 → 剧本 override → 存档 override(后者覆盖前者)。

    Phase 1:调用方还没接存储,传入的层都为 None → 返回 default_profile()。
    """
    merged = default_profile()
    for layer in (platform_default, user_default, script_override, save_override):
        if isinstance(layer, dict):
            for k in KNOBS:
                if k in layer and layer[k] is not None:
                    merged[k] = _clamp(layer[k])
    return merged
