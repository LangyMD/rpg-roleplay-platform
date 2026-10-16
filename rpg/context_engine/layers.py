"""context_engine.layers — 各上下文层构建函数."""
from __future__ import annotations

from typing import Any

from context_engine._constants import MAX_LAYER_CHARS  # noqa: F401 (re-exported via __init__)
from timeline_index import timeline_filter_for_label


def _state_schema_layer(state, chars: dict[str, Any]) -> str:
    """task 59：把 state 字段的真实 schema + 当前 enum 候选喂给 LLM。

    痛点：之前 LLM 不知道
    - player.role 值是单字符串还是 {name, tier} 结构 → 瞎试
    - relationships.角色名 中"角色名"应是已存 NPC 还是任意新名字 → 不一致
    - memory.resources 是 list 但能写单值 / 多值 → 反复尝试

    本层给出明确 schema + 当前已知值，让 LLM 输出强类型。
    """
    p = state.data.get("player", {}) or {}
    w = state.data.get("world", {}) or {}
    rels = state.data.get("relationships", {}) or {}
    worldline = state.data.get("worldline", {}) or {}

    # 已知人物列表（玩家 + 当前 relationships + 角色卡库）
    known_npcs = sorted(set(list(rels.keys()) + [name for name in chars.keys() if name != p.get("name")]))
    known_npcs_str = ", ".join(known_npcs[:20]) if known_npcs else "(no NPCs identified yet)"

    # 用户变量当前值
    user_vars = (worldline.get("user_variables") or {})
    var_names = list(user_vars.keys())[:10]

    lines = [
        "## State field schema (follow it strictly when writing)",
        "",
        "**player.\\*** - single string fields:",
        f"- `player.name`: string. Current = {p.get('name', '') or '(empty)'}",
        f"- `player.role`: string. A short role label (e.g. \"chronicler\", \"detective\", \"physician\"), not a structure. Current = {p.get('role', '') or '(empty)'}",
        f"- `player.background`: string. One or two sentences of background. Current length = {len(p.get('background', ''))} characters",
        f"- `player.current_location`: string. A short place name (e.g. \"South City · Old Pier\", \"Abandoned mine entrance\", \"Upstairs at the tavern\"). Current = {p.get('current_location', '') or '(empty)'}",
        "",
        "**world.\\*** - time / known events:",
        f"- `world.time`: string. Any style works (e.g. \"Day 3, late afternoon\" or \"Evening of March 5, YYYY\"), but keep it consistent within this save. Current = {w.get('time', '') or '(empty)'}",
        f"- `world.weather`: optional string. Current = {w.get('weather', '') or '(empty)'}",
        "- `world.known_events`: array of strings. Append with the 【状态追加】 tag or JSON op=append.",
        "- `world.timeline.current_phase`: string. Name of the story phase.",
        "",
        "**relationships.<character name>** - string value (relationship state: trust / wary / hostile / close / neutral, etc.):",
        f"- Characters identified so far: {known_npcs_str}",
        "- **Prefer existing character names**; a new character must first be introduced in the GM narration before you write relationships for them.",
        "- Wrong: `relationships = {name: John Smith, tier: 5}` (it is not an object; it is a path)",
        "- Right: `relationships.John Smith = trust` (the path contains the character name; the value is a string)",
        "",
        "**memory.\\*** - lists vs scalars:",
        "- List fields (append with the 【状态追加】 tag or JSON op=append): `memory.resources` / `memory.abilities` / `memory.facts` / `memory.pinned` / `memory.notes`",
        "- Scalar fields (overwrite directly): `memory.main_quest` / `memory.current_objective` / `memory.mode`",
        "- Each list item is a string.",
        "",
        "**worldline.user_variables.<variable name>** - hard-constraint variables the player created with /set.",
        f"- Variables defined so far: {(', '.join(var_names) if var_names else '(none)')}",
        "- You may read them, but never create new ones yourself (they belong to the player's hard constraints).",
        "",
        "**Never write (hard blacklist)**: `permissions.*` / `history.*` / `schema_version` / `created_at`",
        "- Such writes are rejected and recorded in audit_log.",
    ]
    return "\n".join(lines)


def _fact_groups_layer(state) -> str:
    """task 76：把记忆按 kind 分组渲染，让 LLM 视觉上明确区分
    "原著事实" vs "本局已发生" vs "玩家硬约束"——codex §1+2 强调。

    数据源：state.memory.items（task 74 引入的结构化数组）。
    回退：如果 items 为空（旧存档没积累新写入）就读 legacy memory.facts
    作为 runtime_fact 显示，保证向后兼容。
    """
    memory = state.data.get("memory", {}) or {}
    items = memory.get("items", []) or []
    # 按 kind 分桶（只取 active 状态）
    groups: dict[str, list[dict]] = {
        "canon_fact": [],
        "runtime_fact": [],
        "user_constraint": [],
    }
    for it in items:
        if it.get("status") and it.get("status") != "active":
            continue
        # 自动归档的旧条目排除出 GM 上下文(与 MemoryProvider 读 bucket 同口径),减少
        # 「事实库过时数据」漏进上下文。notes/pinned 已豁免自动归档(见 context_providers.
        # memory._maybe_auto_archive),玩家手记不会因此被滤掉。
        if it.get("archived"):
            continue
        k = it.get("kind")
        if k in groups:
            groups[k].append(it)
    # 各取最近 N 条（按 turn 倒序，便于聚焦"新鲜"信息）
    for k in groups:
        groups[k].sort(key=lambda x: x.get("turn", 0), reverse=True)
    canon = groups["canon_fact"][:8]
    runtime = groups["runtime_fact"][:12]
    constraints = groups["user_constraint"][:6]
    # 回退：items 没积累 runtime_fact，但旧 memory.facts 有 → 显示 facts
    legacy_facts = []
    if not runtime:
        # facts 尾部 append → 「最近 10 条」取尾(与上方 items 分组按 turn 倒序同向)
        legacy_facts = [f for f in (memory.get("facts") or []) if f][-10:]

    lines = []
    if canon:
        lines.append("## Canon facts (canon) - boundaries of the setting, NOT things that happened in this playthrough")
        for it in canon:
            lines.append(f"- {it.get('text', '?')[:80]}")
        lines.append("")
    if runtime:
        lines.append("## Happened in this playthrough (runtime) - lived through by the player; may be retold in narration")
        for it in runtime:
            meta = []
            if it.get("time_label"):
                meta.append(it["time_label"])
            if it.get("characters"):
                meta.append(", ".join(it["characters"][:3]))
            meta_str = f"({' · '.join(meta)})" if meta else ""
            lines.append(f"- {it.get('text', '?')[:80]} {meta_str}")
        lines.append("")
    elif legacy_facts:
        lines.append("## Happened in this playthrough (runtime, legacy) - data from before an old save was migrated")
        for f in legacy_facts:
            lines.append(f"- {f[:80]}")
        lines.append("")
    if constraints:
        lines.append("## Player hard constraints (user_constraint) - highest priority, override everything")
        for it in constraints:
            lines.append(f"- {it.get('text', '?')[:80]}")
    if not lines:
        return ""
    return "\n".join(lines).rstrip()


def _candidate_actions_layer(plan: dict[str, Any] | None) -> str:
    """task 82：把 curator 的 candidate_actions 显式作为 anchor 喂给主 GM。
    不是强制约束，是优先级提示——让 GM 优先在候选范围内选，减少自由发挥越界。
    """
    if not plan:
        return ""
    candidates = plan.get("candidate_actions") or []
    if not candidates:
        return ""
    lines = [
        "The curator listed the following candidate actions for this turn; **prefer staying within them** when narrating or writing state.",
        "If none of them fit, you may choose \"other\" (explain in the prose why you departed from the candidates):",
    ]
    for i, c in enumerate(candidates[:5], 1):
        lines.append(f"{i}. {str(c)[:120]}")
    lines.append("(The candidates are suggestions, not requirements; the final output is still your call.)")
    return "\n".join(lines)


def _active_hypotheses_layer(state) -> str:
    """task 75：暴露 active hypothesis 给 LLM，让模型知道自己已经登记过哪些推测，
    避免重复推测同一件事或把推测当事实复述。
    """
    try:
        hypos = state.list_active_hypotheses() if hasattr(state, "list_active_hypotheses") else []
    except Exception:
        hypos = []
    if not hypos:
        return ""
    lines = [
        "These are this save's **unconfirmed hypotheses** (only guesses by you / the sub-agents; **never retell them as facts that happened**):",
    ]
    for h in hypos[:8]:
        chars = ", ".join(h.get("characters", []) or [])
        time_label = h.get("time_label") or ""
        meta = " · ".join(x for x in [time_label, chars] if x)
        meta_str = f"({meta})" if meta else ""
        lines.append(f"- [{h.get('id', '?')}] {h.get('text', '?')[:60]} {meta_str}")
    lines.append(
        "If new information confirms a hypothesis, output "
        "`{\"op\":\"confirm_hypothesis\",\"id\":\"...\"}` to promote it to a fact; "
        "if it is disproved, output `{\"op\":\"reject_hypothesis\",\"id\":\"...\"}`."
    )
    return "\n".join(lines)


def _write_results_layer(state) -> str:
    """task 54：把上轮 GM 标签的处理结果反馈给模型，闭合 codex 流水线最后一环。

    构造一段简短的"上轮发生了什么"叙述：
    - 真生效的写入
    - 入 pending 的（玩家审批中）
    - 被硬黑名单拒的
    告诉 LLM 不必重写已 pending 的同一路径；让它知道 read_only/default
    模式下哪些标签起不到作用。
    """
    memory = (state.data.get("memory") or {})
    permissions = (state.data.get("permissions") or {})
    last_updates = memory.get("last_structured_updates") or []
    pending = permissions.get("pending_writes") or []
    audit_log = permissions.get("audit_log") or []

    lines = []
    if last_updates:
        lines.append("What actually happened to the tags you output last turn:")
        for u in last_updates[:12]:
            lines.append(f"- {u}")

    if pending:
        lines.append("")
        lines.append(f"Writes currently awaiting player approval ({len(pending)} total · already queued, do not rewrite the same path):")
        for p in pending[-8:]:  # 最近 8 条
            risk = p.get("risk", "?")
            field = p.get("path") or p.get("field", "?")
            val = str(p.get("value", p.get("to", "")))[:50]
            lines.append(f"- [{risk}] {field} = {val}")

    blocked = [a for a in audit_log[-15:] if a.get("blocked") == "hard_forbidden"]
    if blocked:
        lines.append("")
        lines.append("Rejected by the hard blacklist last turn (permissions.* / history.* are forbidden in any form; do not write them again):")
        for a in blocked[-5:]:
            lines.append(f"- {a.get('path')} = {str(a.get('value',''))[:50]}")

    # task 60: 解析失败反馈 — 让 LLM 看到自己写的标签为什么没生效
    parse_errors = [a for a in audit_log[-20:] if a.get("kind") == "parse_error"]
    if parse_errors:
        lines.append("")
        lines.append("⚠️ Tags you output last turn **failed to parse** (recorded before being silently dropped; fix the format and try again):")
        for a in parse_errors[-5:]:
            lines.append(f"- {a.get('raw_spec', '?')[:60]}")
            if a.get("hint"):
                lines.append(f"  · Reason: {a['hint']}")
        lines.append("Correct format examples:")
        lines.append("- JSON: `{\"op\":\"set\",\"path\":\"player.role\",\"value\":\"chronicler\"}`")
        lines.append("- 【】 tag: `【状态写入：player.role=chronicler】` (ASCII = sign; no spaces in the path)")

    # 洪泛闸反馈 — 没有这一段,闸就只是「悄悄拒绝」,GM 下轮还会原样再写一遍。
    flood = [a for a in audit_log[-20:] if a.get("kind") == "memory_flood_blocked"]
    if flood:
        lines.append("")
        lines.append("⚠️ Some memory writes last turn **were rejected by the flood gate** (one thing was split into too many entries, and the player would have to delete each one by hand in the panel):")
        for a in flood[-5:]:
            lines.append(f"- {a.get('path')} ← {str(a.get('value', ''))[:40]}")
            if a.get("hint"):
                lines.append(f"  · Reason: {a['hint']}")
        lines.append("What to do: **merge entries of the same kind into one** (tell the details in the prose and keep a single summary entry with the progress / count); do not append them one by one.")

    rejected = [a for a in audit_log[-15:] if "rejected" in str(a.get("source", "")) or a.get("kind") == "rejected"]
    if rejected:
        lines.append("")
        lines.append("Recent writes the player rejected (do not rewrite them right away; set them up in the narration first or ask instead):")
        for a in rejected[-5:]:
            lines.append(f"- {a.get('path')} = {str(a.get('value',''))[:50]}")

    if not lines:
        return "(This is the first turn of this save, or no tags were output last turn.)"
    return "\n".join(lines)


def _safe_timeline_filter(label: str) -> dict[str, Any]:
    try:
        return timeline_filter_for_label(label)
    except Exception:
        return {
            "chapter_min": None,
            "chapter_max": None,
            "anchor_chapter": None,
            "anchor_event": "",
            "story_time_label": "",
            "confidence": 0.0,
        }


def _timeline_layer(state) -> dict[str, Any]:
    world = state.data.get("world", {})
    timeline = world.get("timeline", {})
    pending = timeline.get("pending_jump") or {}
    locked_label = world.get("time") or timeline.get("current_label") or ""
    retrieval_label = locked_label

    # 真相源:state.world.timeline.{anchor_chapter, chapter_min, chapter_max, anchor_phase}
    # 由 chat handler 在 /set 后调 script_timeline.resolve_timeline_anchor 写入。
    # 没写入时退化到 SQLite vectors.db 索引 (旧 _safe_timeline_filter)。
    real_anchor_chapter = timeline.get("anchor_chapter")
    real_chapter_min = timeline.get("chapter_min")
    real_chapter_max = timeline.get("chapter_max")
    real_anchor_phase = timeline.get("anchor_phase")
    real_anchor_event = timeline.get("anchor_event")
    if real_anchor_chapter and real_chapter_min and real_chapter_max:
        anchor = {
            "anchor_chapter": real_anchor_chapter,
            "chapter_min": real_chapter_min,
            "chapter_max": real_chapter_max,
            "anchor_event": real_anchor_event or "",
            "story_time_label": locked_label,
            "story_phase": real_anchor_phase or "",
            "confidence": timeline.get("anchor_confidence") or 0.0,
        }
    else:
        anchor = _safe_timeline_filter(retrieval_label)
        if not anchor.get("anchor_chapter"):
            previous = (timeline.get("last_transition") or {}).get("from")
            if previous:
                anchor = _safe_timeline_filter(previous)
                retrieval_label = previous
    target_anchor = _safe_timeline_filter(pending.get("to", "")) if pending else {}

    # 阶段显示:anchor_phase (用户 /set 后查锚点拿到) 优先于 current_phase (可能过时)
    effective_phase = (
        timeline.get("anchor_phase")
        or timeline.get("current_phase")
        or anchor.get("story_phase")
        or "unknown"
    )
    lines = [
        f"Locked timeline: {locked_label}",
        f"Current phase: {effective_phase}",
        f"Anchor state: {timeline.get('anchor_state') or 'locked'}",
        f"Novel retrieval anchor: chapter {anchor.get('anchor_chapter') or '?'} · {anchor.get('anchor_event') or anchor.get('story_phase') or 'no match'}",
        f"Allowed retrieval chapter window: {anchor.get('chapter_min') or '?'} - {anchor.get('chapter_max') or '?'}",
    ]
    if pending:
        pending_status = str(pending.get("status") or "")
        # task 44：之前 prompt 鼓励 GM "默认接受、输出【时间跳跃确认】+【当前时间线：目标】"
        # —— 这让 state 处于 pending_confirmation 时 GM 正文还在叙事到目标时间。
        # 玩家用『先让子代理检查冲突，不要直接跳过确认』这类措辞触发的 pending，
        # 强制 GM 这一轮只输出冲突检查 + 风险清单 + 询问玩家确认，禁止：
        #   - 叙事推进到目标时间（不能写"翌日上午""转眼已是次日"等过去式时间过渡）
        #   - 输出【时间跳跃确认：目标】tag（state 端已 task 32/35 防御，但 prompt 也要主动禁）
        #   - 输出【当前时间线：目标】或【当前位置：新地点】tag（把未发生的事写进 state）
        #   - 声明在新地点新时间发生的具体场景/选项
        is_awaiting = pending_status in ("awaiting_gm_confirmation", "awaiting", "pending_confirmation")
        lines.extend([
            f"Player requested a time jump: {pending.get('from', '')} -> {pending.get('to', '')}",
            f"Target novel match: chapter {target_anchor.get('anchor_chapter') or '?'} · {target_anchor.get('anchor_event') or 'no exact match'}",
            f"pending status: {pending_status or 'unknown'}",
        ])
        if is_awaiting:
            lines.extend([
                "⚠ This turn anchor_state=pending_confirmation: do NOT treat the future time/place the player requested as something that has already happened.",
                "Do not write anything that moves the scene forward to the target time ('The next morning...', 'The following day...', 'Before you know it...', etc.);",
                "do not output the tags 【时间跳跃确认：…】【当前时间线：<target time>】【当前位置：<new place>】【时间：<target time>】;",
                "do not give dialogue, actions or options set in the 'new time / new place' scene.",
                "This turn you may only: (1) give a conflict check (is it consistent with the worldbook / timeline anchors?); (2) list risks / costs / prerequisites; "
                "(3) output 【询问玩家：Confirm the jump to <target time>?】 + 1-3 clear options (confirm / cancel / change the target).",
                "Only if the player clearly replies 'confirm' or /confirm next turn do you actually advance the timeline and the scene.",
            ])
        else:
            lines.extend([
                "This turn you must deal with the time jump first. By default, respect the player's intent to jump or change course; if you accept, write the transition / landing point and output 【时间跳跃确认：<target time>】 and 【当前时间线：<target time>】; only output 【询问玩家：...】 if the target cannot be interpreted at all.",
                "Until it is confirmed, do not treat the requested future time as already happened; only after confirmation may you advance the scene and update location / objective.",
            ])
    else:
        # 新增分支:用户当回合刚用 /set 硬覆盖时间线 (last_transition.source="user_set")。
        # 这是**覆盖式跳跃**,不是叙事过渡:state.world.time 已经直接变了,GM 必须
        # 把新时间视作既定事实,从新时间点的场景开始叙事,不能写"穿越/醒来/拨回时钟"
        # 等过渡剧情。
        # task 86：除了 last_transition.source 判定,还检查 user_set_jump_turn —
        # 因为 GM 在响应中可能再调 update_time(source="gm") 把 last_transition
        # 改写,但 user_set_jump_turn 只会被新的 user_set 跳跃覆盖,可靠地表示
        # 本回合是否有过用户硬覆盖。
        last_t = timeline.get("last_transition") or {}
        try:
            _last_turn = int(last_t.get("turn") or -1)
            _cur_turn = int(state.data.get("turn") or 0)
        except (TypeError, ValueError):
            _last_turn = -1
            _cur_turn = 0
        try:
            _user_jump_turn = int(timeline.get("user_set_jump_turn")) if timeline.get("user_set_jump_turn") is not None else None
        except (TypeError, ValueError):
            _user_jump_turn = None
        _is_user_set_now = (
            (last_t.get("source") == "user_set" and _last_turn == _cur_turn)
            or (_user_jump_turn == _cur_turn)
        )
        if _is_user_set_now:
            _from = last_t.get("from") or "(unknown)"
            _to = last_t.get("to") or locked_label or "(unknown)"
            lines.extend([
                "",
                f"⚠ This turn the player used /set to hard-override the timeline: from \"{_from}\" -> to \"{_to}\"",
                "This is an **overriding jump**, not a narrative transition. Your job is to open the scene directly at the new point in time; do not narrate the passage of time.",
                "**Never** write the following phrasing or plot devices (violations get stripped / flagged):",
                "  · transmigration, time slips / shifting through time, going back to the past, rifts in time, time flowing backwards",
                "  · waking up, opening your eyes again, coming to from unconsciousness / sleep",
                "  · the clock being turned back, time being pulled back (by a pair of hands)",
                "  · the world restarting, the scene / time being reset, the world being rewritten",
                "  · convulsive / amnesiac / unconscious openings such as 'a bone-deep cold' or 'shivering with cold'",
                "  · template transitions such as 'When you once again X...' or 'When you open X, X is already gone'",
                "**Instead**: treat state.world.time + state.player.current_location as established facts, "
                "and start from what the player character is doing, seeing and who they are with 'right now'. "
                "The player is deliberately moving the game forward: **a change of timeline label = the camera cutting to a new point in time**; the character feels no amnesia and no sense of having travelled through time.",
            ])
        else:
            lines.append("No pending time jump; keep to the current timeline anchor when generating, unless the player proposes a new jump this turn.")

    debug = {
        "anchor_state": timeline.get("anchor_state") or "locked",
        "current_label": locked_label,
        "current_phase": timeline.get("current_phase") or "",
        "pending_jump": pending,
        "retrieval_label": retrieval_label,
        "chapter_min": anchor.get("chapter_min"),
        "chapter_max": anchor.get("chapter_max"),
        "anchor_chapter": anchor.get("anchor_chapter"),
        "anchor_event": anchor.get("anchor_event"),
        "story_time_label": anchor.get("story_time_label"),
        "confidence": anchor.get("confidence", 0.0),
        "target_anchor": target_anchor,
    }
    return {"text": "\n".join(lines), "debug": debug}
