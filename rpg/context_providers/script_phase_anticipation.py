"""
script_phase_anticipation.py — task 107E (part 2/2)

剧本期望线 provider — 把剧本里"当前 phase 之后的 1-2 段" 喂给 GM 作为"未来参考",
让 GM 知道剧本预期接下来的走向 (但不强制 GM 必须沿着剧本走 — 玩家可能偏离)。

数据源:
  · phase_digests (script 级, 已存在 — 通过 chapter_facts 聚合)
  · script_timeline_anchors

规则:
  · 找 save 当前 active phase 的 phase_label
  · 在 script.phase_digests 里找该 phase_label 之后的 1-2 个 phase
  · 渲染成 "可能的未来" 段
  · 提示语强调 "这是剧本预期, 玩家可能偏离, 不要强制对齐"
"""
from __future__ import annotations

from core.token_estimate import estimate_tokens

from .base import ContextContribution, ContextProvider
from .registry import register_provider

MAX_LOOKAHEAD_PHASES = 2
PER_PHASE_BUDGET = 400


class ScriptPhaseAnticipationProvider(ContextProvider):
    """注入剧本下一阶段(s) 预期 — GM 思考未来的参考。"""
    id = "script_phase_anticipation"

    def applies(self, state, manifest, demand) -> bool:
        return True

    def collect(self, state, manifest, demand, services) -> ContextContribution:
        script_id = getattr(services, "script_id", None)
        if not script_id:
            return ContextContribution.skipped(self.id, "no script_id")

        # 当前 phase_label — 从 state.world.timeline.current_phase 取
        try:
            current_phase = (
                (state.data.get("world") or {})
                .get("timeline", {})
                .get("current_phase", "")
                or ""
            ).strip()
        except Exception:
            current_phase = ""

        try:
            phases = _load_script_lookahead(int(script_id), current_phase, MAX_LOOKAHEAD_PHASES)
        except Exception as exc:
            return ContextContribution.skipped(self.id, f"db error: {exc!r}")

        if not phases:
            return ContextContribution.skipped(self.id, "no upcoming script phases")

        text = _render_lookahead(phases, current_phase)
        layer = self.make_layer(
            "script_phase_anticipation",
            "What the Script Expects Next (reference only)",
            text,
            sticky=False,
            priority=42,  # 中等 priority, 低于 worldbook (45) 但高于 rag (40)
        )
        return ContextContribution(
            provider_id=self.id,
            kind="script_future",
            priority=42,
            layers=[layer],
            facts=[f"Next script segment: {p.get('phase_label')}" for p in phases],
            tokens_estimate=estimate_tokens(text),
            debug={"current_phase": current_phase, "lookahead": len(phases)},
        )


def _load_script_lookahead(script_id: int, current_phase: str, limit: int) -> list[dict]:
    """拉 script 在 current_phase 之后的 limit 个 phase digest。

    策略:
    1. 先找 current_phase 对应的 chapter_max
    2. 拉 chapter_min > 该 chapter_max 的 phase_digests, 按 chapter_min 升序
    3. 如果 current_phase 为空, 直接拉前 limit 个 (game 还没开始)
    """
    from platform_app.db import connect, init_db
    init_db()
    with connect() as db:
        chapter_threshold = 0
        if current_phase:
            row = db.execute(
                "select chapter_max from phase_digests where script_id=%s and phase_label=%s",
                (script_id, current_phase),
            ).fetchone()
            if row:
                chapter_threshold = int(row["chapter_max"] or 0)

        rows = db.execute(
            """
            select phase_label, chapter_min, chapter_max, summary,
                   key_events, key_locations, key_characters,
                   story_time_label_start, story_time_label_end
            from phase_digests
            where script_id = %s and chapter_min > %s
            order by chapter_min asc
            limit %s
            """,
            (script_id, chapter_threshold, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _render_lookahead(phases: list[dict], current_phase: str) -> str:
    parts = ["(Below is where the script's author expects the story to go next - a direction for reference only. The player may diverge completely; do not force the story back onto it.)"]
    if current_phase:
        parts.append(f"Currently at: {current_phase}")
    for p in phases:
        label = (p.get("phase_label") or "").strip() or "untitled segment"
        ch_range = f"chapters {p.get('chapter_min')}-{p.get('chapter_max')}"
        story_time = ""
        s = (p.get("story_time_label_start") or "").strip()
        e = (p.get("story_time_label_end") or "").strip()
        if s or e:
            story_time = f" · {s}{(' → ' + e) if e and e != s else ''}"
        head = f"# Next script segment: {label} ({ch_range}{story_time})"
        summary = (p.get("summary") or "").strip()
        events = p.get("key_events") or []
        locs = p.get("key_locations") or []

        block = [head, summary]
        if events:
            evt_lines = []
            for ev in events[:3]:
                if isinstance(ev, dict):
                    s_ev = (ev.get("summary") or ev.get("desc") or "").strip()
                    if s_ev:
                        evt_lines.append(f"  · {s_ev[:100]}")
                elif isinstance(ev, str) and ev.strip():
                    evt_lines.append(f"  · {ev[:100]}")
            if evt_lines:
                block.append("Expected events:")
                block.extend(evt_lines)
        if locs:
            loc_str = ", ".join(str(loc) for loc in locs[:5] if loc)
            if loc_str:
                block.append(f"Expected locations: {loc_str}")

        chunk = "\n".join(block)
        if len(chunk) > PER_PHASE_BUDGET:
            chunk = chunk[: PER_PHASE_BUDGET - 3] + "..."
        parts.append(chunk)
    return "\n\n".join(parts)


register_provider(ScriptPhaseAnticipationProvider())
