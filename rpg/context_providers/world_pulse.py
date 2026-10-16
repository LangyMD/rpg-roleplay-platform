"""
world_pulse.py — 世界心跳 v0(活世界·柱子1)context provider。

设计文档: docs/design/world_heartbeat_v0.md §3

每回合取最多 2 条最旧的未浮出 background_events,标记 surfaced_turn=当前turn +
执行过期剪除(已浮出超 SURFACED_RETENTION_TURNS 回合的确定性剪除),渲染成一段
提示交给 GM 自然浮现(传闻/路人交谈/环境痕迹),不强求当回合全用。

feature gate: core.feature_flags.feature_enabled("world_heartbeat", user_id)，
默认关（与 consequence_ledger 同口径）。

与 consequence_echo 的关系: 同一批「活世界」provider，priority 55（低于
memory 60，高于历史摘要 48），novel + freeform 双 manifest 都挂。
"""
from __future__ import annotations

from core.token_estimate import estimate_tokens

from .base import ContextContribution, ContextProvider
from .registry import register_provider

# 与设计文档 §3 一致。
PRIORITY = 55


class WorldPulseProvider(ContextProvider):
    """世界脉动 — 浮出玩家不在场时发生的世界侧小事,供 GM 自然带出。"""
    id = "world_pulse"

    def applies(self, state, manifest, demand) -> bool:
        return super().applies(state, manifest, demand)

    def collect(self, state, manifest, demand, services) -> ContextContribution:
        from core.feature_flags import feature_enabled
        user_id = getattr(services, "user_id", None)
        if not feature_enabled("world_heartbeat", user_id):
            return ContextContribution.skipped(self.id, "world_heartbeat flag 关闭")

        state_data = getattr(state, "data", None)
        if not isinstance(state_data, dict):
            return ContextContribution.skipped(self.id, "state.data 不可用")

        from agents.world_heartbeat import SURFACED_RETENTION_TURNS

        events = state_data.get("background_events")
        if not isinstance(events, list):
            return ContextContribution.skipped(self.id, "无世界事件")

        current_turn = int(state_data.get("turn", 0) or 0)

        # 过期剪除:已浮出(surfaced_turn 非空)超过 SURFACED_RETENTION_TURNS 回合的
        # 确定性剪除(防膨胀)。未浮出的条目不剪。
        kept: list[dict] = []
        for e in events:
            if not isinstance(e, dict):
                continue
            surfaced_turn = e.get("surfaced_turn")
            if surfaced_turn is not None:
                try:
                    surfaced_turn_int = int(surfaced_turn)
                except (TypeError, ValueError):
                    surfaced_turn_int = current_turn
                if current_turn - surfaced_turn_int > SURFACED_RETENTION_TURNS:
                    continue  # 剪除
            kept.append(e)
        if len(kept) != len(events):
            state_data["background_events"] = kept
        events = kept

        # 取最多 2 条最旧的未浮出条目(按 created_turn 升序,早种下的先浮出)。
        unsurfaced = [e for e in events if not e.get("surfaced_turn")]
        if not unsurfaced:
            return ContextContribution.skipped(self.id, "无未浮出的世界事件")
        unsurfaced.sort(key=lambda e: e.get("created_turn", 0))
        to_surface = unsurfaced[:2]

        for e in to_surface:
            e["surfaced_turn"] = current_turn

        text = _render(to_surface)
        layer = self.make_layer(
            "world_pulse",
            "World Pulse",
            text,
            sticky=False,
            priority=PRIORITY,
        )
        return ContextContribution(
            provider_id=self.id,
            kind="world_pulse",
            priority=PRIORITY,
            layers=[layer],
            facts=[f"World pulse (happened on turn {e.get('created_turn')}): {e.get('text', '')}" for e in to_surface],
            tokens_estimate=estimate_tokens(text),
            debug={"surfaced_count": len(to_surface)},
        )


def _render(entries: list[dict]) -> str:
    lines = [
        "[World pulse · while you were elsewhere] Small things that happened in the world meanwhile. Pick one and let it surface naturally "
        "as a rumor / passers-by talking / traces in the surroundings (no need to use them all this turn; never announce them flatly):",
    ]
    for e in entries:
        lines.append(f"- {e.get('text', '')}")
    return "\n".join(lines)


register_provider(WorldPulseProvider())
