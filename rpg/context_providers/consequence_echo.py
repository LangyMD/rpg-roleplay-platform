"""
consequence_echo.py — 后果账本 v1(活世界·柱子2)context provider。

设计文档: docs/design/consequence_ledger_v1.md

每回合 GM 生成前扫描 pending 的后果条目、触发到期的，并把"本回合刚触发的 +
最近几回合触发未满兑现窗口的"渲染成一段提示，加入 novel + freeform 两份
manifest。扫描+触发+注入在 collect() 一处完成，不另开管线钩子。

feature gate: core.feature_flags.feature_enabled("consequence_ledger", user_id)，
默认关，灰度验后开（与 episodic_recall 同口径）。
"""
from __future__ import annotations

from .base import ContextContribution, ContextProvider
from .registry import register_provider

# 与设计文档 §4 一致。
PRIORITY = 85


class ConsequenceEchoProvider(ContextProvider):
    """后果账本回响 — 扫描到期后果并提示 GM 自然兑现。"""
    id = "consequence_echo"

    def applies(self, state, manifest, demand) -> bool:
        return super().applies(state, manifest, demand)

    def collect(self, state, manifest, demand, services) -> ContextContribution:
        from core.feature_flags import feature_enabled
        user_id = getattr(services, "user_id", None)
        if not feature_enabled("consequence_ledger", user_id):
            return ContextContribution.skipped(self.id, "consequence_ledger flag 关闭")

        state_data = getattr(state, "data", None)
        if not isinstance(state_data, dict):
            return ContextContribution.skipped(self.id, "state.data 不可用")

        from state.consequence_ledger import entries_for_injection, scan_and_fire

        # collect 时一处完成：扫描 + 触发（写 status=fired）+ 取注入集合。
        scan_and_fire(state_data)
        entries = entries_for_injection(state_data)
        if not entries:
            return ContextContribution.skipped(self.id, "无到期后果")

        text = _render(entries)
        layer = self.make_layer(
            "consequence_echo",
            "Consequence Echoes",
            text,
            sticky=False,
            priority=PRIORITY,
        )
        return ContextContribution(
            provider_id=self.id,
            kind="consequence_echo",
            priority=PRIORITY,
            layers=[layer],
            facts=[f"Consequence echo (planted on turn {e.get('created_turn')}): {e.get('text', '')}" for e in entries],
            tokens_estimate=len(text) // 2,
            debug={"fired_count": len(entries)},
        )


def _render(entries: list[dict]) -> str:
    lines = [
        "[Consequence echoes] Past causes are catching up. Let them pay off naturally this turn or over the next few turns "
        "(show them as story events; do not mechanically recite this list):",
    ]
    for e in entries:
        lines.append(f"- (planted on turn {e.get('created_turn')}) {e.get('text', '')}")
    return "\n".join(lines)


register_provider(ConsequenceEchoProvider())
