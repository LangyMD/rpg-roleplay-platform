"""context_engine.rules_text — 规则文本生成函数."""
from __future__ import annotations

from typing import Any


def _story_rules() -> str:
    return "\n".join([
        "This is an immersive text RPG. The GM only describes what the player character can perceive or could plausibly learn.",
        "Keep the source's style: restrained, precise, information-dense; do not turn NPCs into question-answering machines.",
        "Never decide actions for the player. You may end on pressure, a clue or a choice, but never make the choice for the player.",
        "The player's actions may branch away from the original story; the worldbook and character cards take priority in keeping characters' logic and faction boundaries intact.",
        "When the state changes this turn, append structured tags after the prose so the system can write them back to the save.",
    ])


def _agent_runtime_rules() -> str:
    # task 67：主体契约已合并到 gm.py _SYSTEM_BASE「主 GM 运行契约」段，
    # 这里只保留 "本轮特定" 的运行提醒（动态层用，每轮可重申）。
    return "\n".join([
        "This turn, be sure to: read the sub-agent decision -> rule on how the world reacts -> write the prose -> output the JSON ops array (only if something actually changed).",
        "If the context is not enough to move forward, state the uncertainty in the prose and output a question op to let the player choose; do not make things up.",
    ])


def _context_agent_decision(plan: dict[str, Any] | None) -> str:
    """task 79：DemandLedger 渲染。显式分组展示 hard vs soft constraint，
    acceptance 单独 section，confidence + clarifying_question 单独提示。"""
    if not plan:
        return "There is no LLM sub-agent decision this turn; the main GM must generate conservatively from the timeline layer and the retrieval reference."
    must_include = plan.get("must_include") or (plan.get("retrieval_plan", {}) or {}).get("must_include") or []
    risk_flags = plan.get("risk_flags") or []
    hard = plan.get("hard_constraints") or []
    soft = plan.get("soft_preferences") or []
    targets_e = plan.get("target_entities") or []
    acceptance = plan.get("acceptance") or []
    candidates = plan.get("candidate_actions") or []
    conf = plan.get("confidence", 1.0)
    clarify = (plan.get("clarifying_question") or "").strip()

    lines = [
        f"Sub-agent's reading of intent: {plan.get('intent') or 'not stated'}",
    ]
    if plan.get("active_goal"):
        lines.append(f"Underlying real goal: {plan['active_goal']}")
    lines.append(f"Target timeline: {plan.get('timeline_target') or 'no jump requested'}")
    if plan.get("target_location"):
        lines.append(f"Target location: {plan['target_location']}")
    if plan.get("target_time"):
        lines.append(f"Target time: {plan['target_time']}")
    if targets_e:
        lines.append(f"Entities involved: {', '.join(str(x) for x in targets_e[:8])}")
    if hard:
        lines.append("[Hard constraints] (must be satisfied)")
        for c in hard[:6]:
            lines.append(f"  · {c}")
    if soft:
        lines.append("[Soft preferences] (better satisfied, may be compromised)")
        for c in soft[:6]:
            lines.append(f"  · {c}")
    lines.append(f"Retrieval query: {plan.get('retrieval_query') or 'not provided'}")
    lines.append("Must-include facts: " + ("; ".join(str(x) for x in must_include) if must_include else "none"))
    if acceptance:
        lines.append("[Acceptance checks this turn] (after you answer, the system checks each one)")
        for a in acceptance[:6]:
            lines.append(f"  · {a}")
    if candidates:
        lines.append("[Suggested candidate actions] (the GM may prefer these; not mandatory)")
        for c in candidates[:5]:
            lines.append(f"  · {c}")
    lines.append("Risk flags: " + ("; ".join(str(x) for x in risk_flags) if risk_flags else "none"))
    lines.append(f"Sub-agent confidence: {conf:.2f}")
    if clarify:
        lines.append(f"⚠️ The sub-agent suggests asking the player first: {clarify}")
    lines.append(f"Reasoning: {plan.get('reason') or 'not stated'}")
    lines.append("The main GM may only use this as the result of context selection; never turn the sub-agent's reasoning into facts visible to the player.")
    return "\n".join(lines)


def _context_agent_debug(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not plan:
        return {}
    return {
        "intent": plan.get("intent", ""),
        "active_goal": plan.get("active_goal", ""),
        "timeline_target": plan.get("timeline_target", ""),
        "retrieval_query": plan.get("retrieval_query", ""),
        "must_include": plan.get("must_include", []),
        "hard_constraints": plan.get("hard_constraints", []),
        "soft_preferences": plan.get("soft_preferences", []),
        "target_entities": plan.get("target_entities", []),
        "candidate_actions": plan.get("candidate_actions", []),
        "acceptance": plan.get("acceptance", []),
        "risk_flags": plan.get("risk_flags", []),
        "confidence": plan.get("confidence", 1.0),
        "clarifying_question": plan.get("clarifying_question", ""),
    }
