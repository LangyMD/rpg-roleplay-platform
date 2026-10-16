"""
RulesProvider — 在 manifest.ruleset 非 none 时启用。
注入 player_character 摘要、dice_log、rule_candidate_actions。
"""
from __future__ import annotations

from core.token_estimate import estimate_tokens

from .base import ContextContribution, ContextProvider
from .registry import register_provider


def _has_ruleset(state, manifest) -> bool:
    rs = manifest.get("ruleset")
    if rs and rs != "none":
        return True
    data = getattr(state, "data", state) or {}
    rs_state = (data.get("ruleset") or {}).get("id")
    return bool(rs_state)


class RulesProvider(ContextProvider):
    id = "rules"

    def applies(self, state, manifest, demand) -> bool:
        if not super().applies(state, manifest, demand):
            return False
        return _has_ruleset(state, manifest)

    def collect(self, state, manifest, demand, services) -> ContextContribution:
        data = getattr(state, "data", state) or {}
        ruleset = data.get("ruleset") or {}
        pc = data.get("player_character") or {}
        dice_log = list(data.get("dice_log") or [])[-8:]

        lines: list[str] = []
        lines.append(f"[Ruleset] {ruleset.get('public_label') or ruleset.get('id') or 'unknown'}")

        # Codex #1+#2:硬约束 prompt 由 GamePolicy 统一提供。
        # 一个 policy 类同时负责 preflight (GM 前拦截) + prompt 文本 (GM 真被调用时兜底),
        # 避免两处分别维护;新增约束只动 game_policy.py。
        try:
            from game_policy import get_game_policy as _get_policy
            policy = _get_policy(state)
            policy_constraints = policy.gm_prompt_constraints(state) or []
        except Exception:
            policy_constraints = []
        if policy_constraints:
            lines.append("")
            for ln in policy_constraints:
                lines.append(ln)
        if pc:
            lines.append(
                f"[Character] {pc.get('name')} · Lv {pc.get('level')} {pc.get('class_name', '')} · "
                f"HP {pc.get('hp')}/{pc.get('max_hp')} · AC {pc.get('ac')} · "
                f"proficiency +{pc.get('proficiency_bonus', 0)}"
            )
            abilities = pc.get("abilities") or {}
            if abilities:
                lines.append("  · Abilities: " + " ".join(
                    f"{a.upper()} {abilities.get(a, 10)}" for a in ("str", "dex", "con", "int", "wis", "cha")
                ))
            if pc.get("conditions"):
                lines.append(f"  · Conditions: {', '.join(pc['conditions'])}")
        # rule_candidate_actions（Demand Resolver 产出）
        rcas = (demand.rule_candidate_actions or []) if demand else []
        if rcas:
            lines.append("\n[Rule candidate actions this turn]")
            for a in rcas[:6]:
                desc = f"{a.get('kind')} {a.get('skill') or a.get('ability') or a.get('target') or ''}"
                if a.get("dc") is not None:
                    desc += f" DC {a['dc']}"
                if a.get("reason"):
                    desc += f" — {a['reason']}"
                lines.append(f"  · {desc}")
            lines.append("⚠️ The GM must not roll dice itself; every roll goes through the RulesEngine.")
        if dice_log:
            lines.append("\n[Recent dice log]")
            for d in dice_log:
                summary = (
                    f"{d.get('kind')} · {d.get('actor', '')} · "
                    f"{d.get('expression', '')}={d.get('total')}"
                )
                if d.get("dc") is not None:
                    summary += f" vs DC {d['dc']}"
                if d.get("success") is True:
                    summary += " ✓"
                elif d.get("success") is False:
                    summary += " ✗"
                lines.append(f"  · {summary}")
        text = "\n".join(lines)
        layer = self.make_layer(
            # 用独立 id 避免与 universal_layers 的静态 "rules"(A级缓存)撞 id;
            # 且本层含每回合变的 HP/AC/dice_log,显式 cache_tier="C"(逐回合易变),
            # 否则继承 LAYER_CACHE_TIER["rules"]="A" → 被标 ephemeral 缓存但每回合 miss(零效率)。
            "rules_state", "Ruleset State", text,
            sticky=False, priority=80, cache_tier="C",
        )
        facts: list[str] = []
        if pc:
            facts.append(f"Character HP {pc.get('hp')}/{pc.get('max_hp')}, AC {pc.get('ac')}")
        if rcas:
            facts.append(f"{len(rcas)} rule candidate action(s) this turn")
        return ContextContribution(
            provider_id=self.id,
            kind="rules",
            priority=80,
            facts=facts,
            layers=[layer],
            tokens_estimate=estimate_tokens(text),
            debug={
                "ruleset": ruleset.get("id"),
                "pc_hp": pc.get("hp"),
                "dice_log_count": len(data.get("dice_log") or []),
                "candidate_actions_count": len(rcas),
            },
        )


register_provider(RulesProvider())
