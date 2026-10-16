"""agents/recorder.py — Q_three_sage_pipeline Phase 2: 史官/Recorder

把三个现有 agent 合并为「单次 LLM 调用」的史官，实现：
  - extractor：读叙事 → ops[]（状态变化）
  - anchor_reconcile：读叙事 → reached[]（锚点到达）+ current_chapter
  - acceptance_verifier：读叙事 → unmet[]（未满足验收条款）

单次调用意味着：三个任务共享同一份 prompt 上下文 + 同一次推理 token，
比三次独立调用节省 60-70% 成本，同时减少三倍推理延迟。

公开 API
========
    record_turn(gm_prose, state_data, *, pending_anchors, chapter_map,
                acceptance_clauses, tasks, user_id, model_override,
                api_id_override, timeout_sec) -> dict

返回
====
    {
        "ops":            [...],    # 同 extractor 的 op 结构
        "reached":        [{"anchor_key": str, "drift_score": float}],
        "current_chapter": int | None,
        "unmet":          [...],    # 未满足的 acceptance 条款原文
    }
    任何 tasks 子集未启用 → 对应字段返回空（[]或 None）。
    任何异常 → 返回全空安全默认，绝不上抛。

模型选择（优先级）
==================
    1. api_id_override / model_override（调用方透传）
    2. user_preferences["recorder.api_id"] / ["recorder.model_real_name"]
    3. 回退：user_preferences["extractor.api_id"] / ["extractor.model_real_name"]
    4. _harness.resolve_api_and_model 通配 fallback（agent.api_id / agent.model_real_name）
    5. core.llm_backend DEFAULT_FALLBACK_*
"""
from __future__ import annotations

from typing import Any

from core.logging import get_logger

log = get_logger(__name__)

# 可用任务子集常量
_ALL_TASKS: frozenset[str] = frozenset(["ops", "anchors", "acceptance"])

# GM 正文截断（拼入 prompt 的上限）
_PROSE_CAP = 6000

# ── 合并系统提示（三 agent 指令合并）────────────────────────────────────

_SYSTEM_OPS = """\
[TASK OPS - state extraction]
Read the GM's narration for this turn plus the current state snapshot, and extract state changes into the ops array. **Do not write fiction; output JSON fields only.**

Available ops:
- "set":      overwrite a scalar field (player.* / world.time / memory.main_quest etc.)
- "append":   append to a list field (memory.resources / memory.facts / world.known_events etc.)
- "overwrite": replace a whole list (use sparingly)
- "question": the GM asks the player something in the narration (the player has to choose)

Writable fields (strict):
- player.role / player.background / player.current_location (note: **never write player.name** --
  the player's name is an identity the player chose; even if another character name appears in the source, do not change it to that; the backend rejects it)
- player.appearance / player.personality / player.speech_style (the player persona card; update only when the narration makes a **lasting** change to the player's look / temperament / way of speaking -- transformation / disguise / a major personality shift; value = full replacement text, keep it concise; do not write temporary states (one injury / a change of clothes); fields the player customized by hand are rejected, and once rejected do not retry the same field)
- world.time / world.weather / world.timeline.current_phase / world.known_events
- memory.main_quest / memory.current_objective / memory.mode
- memory.resources / memory.abilities / memory.facts / memory.pinned / memory.notes
- relationships.<character name>
- worldline.user_variables.<variable name>
- ui.<custom key>

Forbidden: player.name (player identity) / permissions.* / history.* / schema_version / created_at

Only output an op when a field really changed in the narration; if it did not change, do not invent one.
If the narration contains no state change at all, output ops as [].
"""

# 后果账本 v1(feature_enabled("consequence_ledger") 时启用,docs/design/consequence_ledger_v1.md)。
# recorder_unified 下史官是唯一权威 ops 通道(GM 自带 fence 会被剥弃,见 chat_pipeline 史官三合一段),
# 所以 consequence 必须由史官提取,否则 GM 侧登记会被静默丢弃(「提示词在≠生效」同款陷阱)。
_SYSTEM_OPS_CONSEQUENCE = """\
[TASK OPS - extra: consequence registration (consequence)]
When the narration plants "a cause now that is bound to echo later", also output a consequence op to register it in the consequence ledger:
- Register when: the player makes a promise / incurs a favor or debt / makes an enemy / saves someone and is owed / agrees on a deadline / lets a dangerous person go.
- Do not register: small things settled on the spot, pure atmosphere, uncertain speculation (use hypothesis for speculation). Fewer is better; at most 2 per turn.
- Shape (pick one):
  {"op":"consequence","text":"Promised Reynard to find out what mauled the beasts in the woods; bring proof back to the village tomorrow morning","due_turns":4}
  {"op":"consequence","text":"Revealed a non-human nature in front of Lynnie; she may let it slip when she goes to market in town","due_location":"Mawald"}
- due_turns: 2-8 is recommended (near-term echo); major foreshadowing may use 10-15. due_location: a place keyword; it comes due when the player reaches a place whose name contains it.
"""

# NPC 议程 v0(feature_enabled("npc_agenda") 时启用,docs/design/npc_agenda_v0.md)。
# 同 consequence:史官是权威 ops 通道,议程必须由史官提取。
_SYSTEM_OPS_AGENDA = """\
[TASK OPS - extra: NPC agenda update (agenda)]
When an NPC's words or actions this turn [reveal a new intention/goal, or their attitude toward the player changes], output an agenda op:
- Shape: {"op":"agenda","name":"Reynard","goal":"Find out the truth behind the mauled beasts in the east woods and keep the hunting grounds","stance":"Trusting, but still watching"}
- goal = what THE CHARACTER wants (not the player's task); stance = their current attitude toward the player; each <= 40 words;
  give at least one of goal/stance, and only the one that changed (partial update; the other is kept).
- Only update NPCs who really revealed something new this turn, at most 2 per turn; if nothing changed, output none.
- name must be a character who has already appeared (in the relationship table / present list); never invent a new name.
"""

_SYSTEM_ANCHORS = """\
[TASK ANCHORS - worldline anchor judgment - be extremely conservative; a miss is better than a false hit]
Read this turn's GM narration and do the following:
(A) judge whether it explicitly narrates any of the "pending source-story anchor events";
(B) judge which chapter of the source story this turn's plot is closest to (progress estimate).

Task A hard rules:
1. List an anchor only when this turn's text [explicitly and unambiguously narrates] that the anchor event actually happened.
   Merely mentioning, hinting, foreshadowing, planning, dreaming, remembering or hypothesizing does not count -- never list those.
2. If unsure, do not list it; a missed anchor costs far less than a false one.
3. Choose only from the given pending anchor list; never invent anchors, never alter an anchor_key.
drift_score (deviation 0.0-1.0): 0.0 = exactly as in the source; 0.3 = core kept but the process differs; 0.7+ = drastically changed. If unsure, give 0.2.

Task B hard rules:
1. Return only a chapter number listed in the chapter map; if it cannot be located -> return null.
2. Unsure / the text is too abstract -> return null (underestimating is far better than wrongly pushing progress forward).
3. The two tasks are independent: chapter reasoning must never change which anchors you pick.
"""

_SYSTEM_ACCEPTANCE = """\
[TASK ACCEPTANCE - acceptance clause judgment]
Read the GM's narration for this turn plus the acceptance clauses, and judge whether each clause is met. Put the original text of every unmet clause into the unmet array.

Principles:
- Positive clauses ("should X" / "must X" / "includes Y"): met only if the corresponding action really happens in the GM narration;
  the keyword merely appearing without being developed -> unmet.
- Negative clauses ("do not X" / "never X"): met only if the narration does not violate it; a forbidden action appears -> unmet.
- The key question is whether the GM actually advanced the narrative / responded to what happened, not whether it repeated the nouns.
- Everything passes -> unmet is [].
- Each unmet item must be exactly identical to the input clause (it is used to backfill the audit_log).
"""

_SYSTEM_OUTPUT_HEADER = """\
You are the Recorder. In a single call, complete all of the enabled tasks below.
**Do not write fiction**; output only the requested JSON object.
"""

_SYSTEM_OUTPUT_FORMAT = """\
[Output format (strict JSON, no markdown fences, no explanation)]
Output exactly one JSON object, starting with `{` and ending with `}`:
"""


def _build_system_prompt(tasks: frozenset[str], consequence_enabled: bool = False,
                         agenda_enabled: bool = False) -> str:
    """根据启用的任务集合组装 system prompt。"""
    parts = [_SYSTEM_OUTPUT_HEADER.strip()]
    if "ops" in tasks:
        parts.append(_SYSTEM_OPS.strip())
        if consequence_enabled:
            parts.append(_SYSTEM_OPS_CONSEQUENCE.strip())
        if agenda_enabled:
            parts.append(_SYSTEM_OPS_AGENDA.strip())
    if "anchors" in tasks:
        parts.append(_SYSTEM_ANCHORS.strip())
    if "acceptance" in tasks:
        parts.append(_SYSTEM_ACCEPTANCE.strip())

    # 输出格式说明
    schema_fields: list[str] = []
    if "ops" in tasks:
        _kinds = "set|append|overwrite|question"
        if consequence_enabled:
            _kinds += "|consequence"
        if agenda_enabled:
            _kinds += "|agenda"
        _extra = ',"due_turns":4' if consequence_enabled else ""
        schema_fields.append('"ops": [{"op":"%s","path":"player.xxx","value":"..."%s}]' % (_kinds, _extra))
    if "anchors" in tasks:
        schema_fields.append('"reached": [{"anchor_key":"<from the list>","drift_score":0.0}]')
        schema_fields.append('"current_chapter": <chapter number integer or null>')
        schema_fields.append('"progress_motion": <0|1|2>')
    if "acceptance" in tasks:
        schema_fields.append('"unmet": ["original clause text 1", ...]')

    schema_example = "{\n  " + ",\n  ".join(schema_fields) + "\n}"
    parts.append(_SYSTEM_OUTPUT_FORMAT.strip())
    parts.append(schema_example)
    parts.append("Fields for tasks that are not enabled may be omitted.")
    return "\n\n".join(parts)


def _build_user_prompt(
    gm_prose: str,
    state_data: dict,
    tasks: frozenset[str],
    pending_anchors: list[dict] | None,
    chapter_map: list[dict] | None,
    acceptance_clauses: list[str] | None,
    consequence_enabled: bool = False,
    agenda_enabled: bool = False,
) -> str:
    """组装 user message：state 快照 + GM 正文 + 各任务附加材料。"""
    lines: list[str] = []

    # 后果账本:已登记未到期清单喂给史官,防跨回合换措辞重复登记(生产实测第 9 回合
    # 「期限约定——」被换成「期限——」再登一遍,指纹归一化只能挡标点漂移,用词漂移靠这里)。
    if consequence_enabled:
        try:
            _pending_cq = [
                str(e.get("text") or "")
                for e in (state_data.get("consequence_ledger") or [])
                if isinstance(e, dict) and e.get("status") == "pending"
            ][:20]
        except Exception:
            _pending_cq = []
        if _pending_cq:
            lines.append("## Consequence ledger - registered, not yet due (NEVER register these again, "
                         "including the same thing described in different words)")
            lines.extend(f"- {t}" for t in _pending_cq)
            lines.append("")

    # NPC 议程:现有议程喂给史官,只在真变化时更新(防换措辞重登,consequence 同教训)。
    if agenda_enabled:
        try:
            _ag = state_data.get("npc_agendas") or {}
            _ag_lines = [
                f"- {n}: goal={v.get('goal','')} / stance={v.get('stance','')}"
                for n, v in list(_ag.items())[:12] if isinstance(v, dict)
            ]
        except Exception:
            _ag_lines = []
        if _ag_lines:
            lines.append("## NPC agendas - current values (output an agenda op only when this turn "
                         "reveals new information; do not repeat these)")
            lines.extend(_ag_lines)
            lines.append("")

    # 状态快照（始终附带，ops 任务需要；其它任务只读正文但一并提供）
    p = (state_data.get("player") or {})
    w = (state_data.get("world") or {})
    m = (state_data.get("memory") or {})
    rels = (state_data.get("relationships") or {})
    lines.append("## Current state snapshot (values before this narration)")
    lines.append(f"- player.name = {p.get('name', '') or '(empty)'}")
    lines.append(f"- player.role = {p.get('role', '') or '(empty)'}")
    lines.append(f"- player.current_location = {p.get('current_location', '') or '(empty)'}")
    lines.append(f"- world.time = {w.get('time', '') or '(empty)'}")
    lines.append(f"- world.weather = {w.get('weather', '') or '(empty)'}")
    lines.append(f"- memory.main_quest = {m.get('main_quest', '') or '(empty)'}")
    # 主线陈旧提醒(群反馈:主线五十多回合没变过,只有当前目标在变)。当前目标每轮都在
    # 议程上,主线是长程字段、写完就没人再管 —— 实测能冻上百个回合零更新,期间
    # set_current_objective 反复被调、set_main_quest 一次没有,且没有任何东西在拒绝写入。
    # 触发是确定性的(回合数),改不改、改成什么仍归史官判断:主线该写什么是叙事判断,
    # 代码代写只会写出废话。措辞刻意给「仍然准确就别动」的出口,避免逼出编造式改写。
    try:
        from state.quest_staleness import (
            MAIN_QUEST_STALE_TURNS,
            main_quest_age,
            main_quest_is_stale,
        )
        if main_quest_is_stale(state_data):
            _age = main_quest_age(state_data)
            _how_long = f"for {_age} turns" if _age is not None else "for a long time"
            lines.append(
                f"  ⚠ The main quest above has not been updated {_how_long} (threshold {MAIN_QUEST_STALE_TURNS} turns). "
                "Check it against the recent plot and pick one; you MUST do one of these this turn: "
                '(a) it is done / the plot has left it behind -> {"op":"set","path":"memory.main_quest",'
                '"value":"the new long-range goal"}; '
                "(b) it is still accurate -> **rewrite the exact same value** to confirm it (content unchanged, this only resets the timer). "
                "Do not make up a synonymous filler line just to tick the box.")
    except Exception:  # noqa: BLE001  提醒失败绝不影响史官正常工作
        pass
    lines.append(f"- memory.current_objective = {m.get('current_objective', '') or '(empty)'}")
    # 快照窗口取尾:resources 尾部 append、relationships 新键落 dict 尾;取头会让
    # 史官看不到新近获得的物品/新建立的关系(误判「未知实体」/重复发放)。
    lines.append(f"- memory.resources = {(m.get('resources') or [])[-5:]}")
    lines.append(f"- relationships = {dict(list(rels.items())[-8:])}")

    # 锚点材料（仅 anchors 任务）
    if "anchors" in tasks:
        lines.append("")
        lines.append("## Pending source-story anchors (task ANCHORS-A; choose only from these)")
        if pending_anchors:
            for a in pending_anchors:
                key = a.get("anchor_key") or ""
                summ = (a.get("summary") or "").strip().replace("\n", " ")
                if len(summ) > 240:
                    summ = summ[:240]
                fatal = "[FATAL - must happen]" if a.get("is_fatal") else ""
                lines.append(f"- anchor_key={key} {fatal} summary: {summ}")
        else:
            lines.append("(no pending anchors in this window)")

        if chapter_map:
            lines.append("")
            lines.append("## Source chapter map (task ANCHORS-B; current_chapter must be one of these "
                         "chapter numbers, or null)")
            for c in chapter_map:
                ch = c.get("chapter")
                label = (c.get("story_time_label") or c.get("label") or "").strip().replace("\n", " ")
                summ = (c.get("summary") or "").strip().replace("\n", " ")
                if len(summ) > 160:
                    summ = summ[:160]
                head = f"Chapter {ch}" + (f" \"{label}\"" if label else "")
                lines.append(f"- chapter={ch} {head}: {summ}")

        # 叙事推进度(ANCHORS-B 续):无论能否对上原著章节都要答 —— 发散/无限流副本里剧情
        # 已离开原著轨道时 current_chapter 往往只能给 null/低章,但故事仍在前进。progress_motion
        # 独立于「对不对得上原著」,只看本回合相对上一回合有没有实质推进:
        lines.append("")
        lines.append("## Narrative progress this turn (task ANCHORS-B; the integer progress_motion is required)")
        lines.append("- 0 = treading water: still the same scene / conversation, no real progress "
                     "(e.g. pure probing dialogue, scenery description, going back and forth)")
        lines.append("- 1 = normal progress: the scene, goal, conflict or a relationship moved one step forward")
        lines.append("- 2 = major leap: a time skip, entering a new instance / new location, achieving or "
                     "failing a key goal, a major turning point")
        lines.append("Judge only from this turn's GM text; it has nothing to do with whether it matches a source chapter.")

    # GM 正文
    lines.append("")
    lines.append("## GM narration this turn")
    from core.token_estimate import cjk_chars_to_budget
    _prose = (gm_prose or "").strip()
    lines.append(_prose[:cjk_chars_to_budget(_prose, _PROSE_CAP)])

    # 验收条款（仅 acceptance 任务）
    if "acceptance" in tasks and acceptance_clauses:
        lines.append("")
        lines.append("## Acceptance clauses to judge (task ACCEPTANCE)")
        for i, cond in enumerate(acceptance_clauses, start=1):
            lines.append(f"{i}. {str(cond).strip()}")

    # 【估章语义判断——必须放在所有材料之后、紧邻输出前】实测便宜模型对提示位置极敏感:同一框架
    # 放章节地图中间 → 结算回合判 None(被其后的原著章概要"带回"表面人物比对);放到正文之后末尾
    # → 稳定判到正确章号(A/B 实测 mid=[None,None,None] vs end=[17,17,16])。玩家为核心:让史官
    # 用语义理解判「在围着原著主角转 vs 干原著之外的事」,别因人物名对不上就一律 null(自插入卡章根因)。
    if "anchors" in tasks and chapter_map:
        lines.append("")
        lines.append("## Read before judging current_chapter (the player is the center)")
        lines.append("The player is often a [self-insert protagonist] -- using their own name / point of view, but possibly "
                     "following the plotline of one of the source's protagonists (living that protagonist's situation "
                     "under a different name). Use your best semantic understanding:")
        lines.append("- If the player's situation / events this turn correspond to what a source protagonist goes through "
                     "(even with different names and details) -> current_chapter = that chapter number; "
                     "**different character names are never a reason to answer null**.")
        lines.append("- If the player has genuinely left the source and is doing their own thing that the source "
                     "does not contain -> current_chapter=null.")
        lines.append("- **Purely private / everyday / romantic scenes** (washing up and daily routine, chatting and "
                     "dates, intimate moments, etc., with no counterpart in the source's plot backbone) -> always "
                     "current_chapter=null; do not match them to a chapter just because 'the characters come from the "
                     "source'; such turns also do not count as plot progress.")

    return "\n".join(lines)


# ── merged tool schema（Anthropic native tool_use）──────────────────

def _build_tool_schema(tasks: frozenset[str], acceptance_clauses: list[str] | None,
                       consequence_enabled: bool = False,
                       agenda_enabled: bool = False) -> dict:
    """构造合并后的 emit_record 工具 schema，只包含已启用任务对应的字段。

    consequence_enabled 必须与 _build_system_prompt 同源传入 —— 三通道(anthropic/vertex/
    openai_compat)都从这一份 schema 取形状,漏这里=原生 tool-use 通道吐不出 consequence
    (progress_motion 漏进 tool-schema 的 parity 事故同款,勿重蹈)。
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    if "ops" in tasks:
        _op_enum = ["set", "append", "overwrite", "question",
                    "hypothesis", "confirm_hypothesis", "reject_hypothesis"]
        _op_item_props: dict[str, Any] = {
            "op": {
                "type": "string",
                "enum": _op_enum,
            },
            "path": {"type": "string", "description": "state path; may be omitted for op=question/hypothesis/*"},
            "value": {"description": "value to write"},
            "question": {"type": "string", "description": "used with op=question"},
            "options": {"type": "array", "items": {"type": "string"}, "description": "used with op=question"},
            "text": {"type": "string", "description": "used with op=hypothesis/consequence"},
            "id": {"type": "string", "description": "used with op=confirm_hypothesis/reject_hypothesis"},
            "characters": {"type": "array", "items": {"type": "string"}, "description": "used with op=hypothesis"},
            "time_label": {"type": "string", "description": "optional with op=hypothesis"},
        }
        if consequence_enabled:
            _op_enum.append("consequence")
            _op_item_props["due_turns"] = {
                "type": "integer",
                "description": "op=consequence: comes due after N turns (2-8 recommended, 10-15 for major foreshadowing)",
            }
            _op_item_props["due_location"] = {
                "type": "string",
                "description": "op=consequence: comes due when the player reaches a place whose name contains this keyword",
            }
        if agenda_enabled:
            _op_enum.append("agenda")
            _op_item_props["name"] = {
                "type": "string",
                "description": "op=agenda: NPC name (must be a character who has already appeared)",
            }
            _op_item_props["goal"] = {
                "type": "string",
                "description": "op=agenda: what this character currently wants (<= 40 words, optional)",
            }
            _op_item_props["stance"] = {
                "type": "string",
                "description": "op=agenda: current attitude toward the player (<= 40 words, optional)",
            }
        properties["ops"] = {
            "type": "array",
            "description": "List of state-change ops. Pass [] when nothing changed.",
            "items": {
                "type": "object",
                "properties": _op_item_props,
                "required": ["op"],
            },
        }
        required.append("ops")

    if "anchors" in tasks:
        properties["reached"] = {
            "type": "array",
            "description": "Anchors explicitly reached this turn (extremely conservative; a miss is better than a false hit)",
            "items": {
                "type": "object",
                "properties": {
                    "anchor_key": {"type": "string"},
                    "drift_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["anchor_key", "drift_score"],
            },
        }
        properties["current_chapter"] = {
            "type": ["integer", "null"],
            "description": "Which source chapter this turn is closest to (cannot locate or unsure -> null)",
        }
        # fork 收编:progress_motion 之前只声明在 system prompt 文本里(_build_system_prompt:139),
        # 没进 tool schema → Anthropic 原生 tool-use / Vertex function-call 下 LLM 不吐它 →
        # _safe_progress_motion(None) → anchor_reconcile.do_pace=False → pace fallback 在主力
        # provider 上永不触发(发散局进度冻死的真根因)。tool-schema 与 prompt 必须同源。
        properties["progress_motion"] = {
            "type": ["integer", "null"],
            "description": "Narrative progress this turn (required): 0 = no progress (in place / recollection), 1 = one normal step forward, 2 = major leap. Answer it even when a divergent run has left the source; it is independent of current_chapter.",
        }
        required.extend(["reached", "current_chapter", "progress_motion"])

    if "acceptance" in tasks:
        # enum 锁定到传入条款原文（与 acceptance_verifier 完全一致）
        enum_vals = [str(c).strip() for c in (acceptance_clauses or []) if str(c).strip()][:64]
        items_schema: dict = {"type": "string"}
        if enum_vals:
            items_schema["enum"] = enum_vals
        properties["unmet"] = {
            "type": "array",
            "description": "Original text of the unmet acceptance clauses (must be exactly identical to the input clauses)",
            "items": items_schema,
        }
        required.append("unmet")

    return {
        "name": "emit_record",
        "description": (
            "Recorder's single-shot output: state ops + anchors reached + acceptance judgment. "
            "Fields for tasks that are not enabled may be omitted or left empty."
        ),
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


# ── 结果解析 ─────────────────────────────────────────────────────────

def _safe_ops(raw: Any) -> list[dict]:
    """从 LLM 输出里抠出 ops 列表，容忍裸列表 / 错误类型。"""
    if isinstance(raw, list):
        return [op for op in raw if isinstance(op, dict)]
    if isinstance(raw, dict):
        ops = raw.get("ops")
        if isinstance(ops, list):
            return [op for op in ops if isinstance(op, dict)]
    return []


def _safe_reached(raw: Any) -> list[dict]:
    """从 LLM 输出里抠出 reached 列表，规范化每条的 drift_score。"""
    items: list[Any] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        r = raw.get("reached")
        if isinstance(r, list):
            items = r
    result: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (item.get("anchor_key") or "").strip()
        if not key:
            continue
        try:
            drift = float(item.get("drift_score"))
        except (TypeError, ValueError):
            drift = 0.2
        drift = max(0.0, min(1.0, drift))
        result.append({"anchor_key": key, "drift_score": drift})
    return result


def _safe_current_chapter(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        v = int(raw)
        return v if v >= 1 else None
    except (TypeError, ValueError):
        return None


def _safe_progress_motion(raw: Any) -> int | None:
    """本回合叙事推进度,由 LLM 判定(发散/无限流副本对不上原著章节时也能答):
      0=原地踏步(同一场景、未实质推进) / 1=正常推进 / 2=重大跨越(时间跳转·进新副本·重大事件)。
    专治「current_chapter 被钳在原著章号窗口里、发散play永远估不出更高章 → 进度冻死」。
    **纯 LLM 信号**:字段缺省/非法 → None(本回合无判定,不累计、不推进),绝不用「默认前进」
    这种硬编码假设凭空推进度(那就退化成被否决的回合计数器了)。"""
    if raw is None:
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    return 0 if v <= 0 else (2 if v >= 2 else 1)


def _safe_unmet(raw: Any, acceptance_clauses: list[str] | None) -> list[str]:
    """从 LLM 输出里抠出 unmet 列表，做 fuzzy 回填保证原文对齐（与 acceptance_verifier 一致）。"""
    items: list[Any] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        u = raw.get("unmet")
        if isinstance(u, list):
            items = u
    if not items:
        return []

    acceptance: list[str] = [str(c).strip() for c in (acceptance_clauses or []) if str(c).strip()]
    out: list[str] = []
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        matched = None
        for orig in acceptance:
            if orig == s:
                matched = orig
                break
        if matched is None:
            for orig in acceptance:
                if s and (s in orig or orig in s):
                    matched = orig
                    break
        out.append(matched or s)
    # dedup 保序
    seen: set[str] = set()
    dedup: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def _parse_recorder_output(
    text: str,
    tasks: frozenset[str],
    acceptance_clauses: list[str] | None,
) -> dict:
    """从 LLM 原始文本 / tool_use JSON 中解析合并输出。

    容忍：裸 JSON 对象、裸 ops 数组、部分字段缺失、错误类型。
    始终返回完整结构（缺失字段用空默认）。
    """
    empty = _empty_result()
    if not text:
        return empty

    # 先尝试直接 parse（含 ```json 围栏兜底 → 委托 core.json_parse）
    from core.json_parse import parse_llm_json
    parsed = parse_llm_json(text, want=None)

    # 裸 ops 数组兼容（extractor 旧格式）
    if isinstance(parsed, list) and "ops" in tasks:
        # 假设是 ops 数组
        return {
            "ops": [op for op in parsed if isinstance(op, dict)],
            "reached": [],
            "current_chapter": None,
            "progress_motion": None,
            "unmet": [],
        }

    if not isinstance(parsed, dict):
        return empty

    result: dict = {}
    result["ops"] = _safe_ops(parsed.get("ops", [])) if "ops" in tasks else []
    if "anchors" in tasks:
        result["reached"] = _safe_reached(parsed.get("reached", []))
        result["current_chapter"] = _safe_current_chapter(parsed.get("current_chapter"))
        result["progress_motion"] = _safe_progress_motion(parsed.get("progress_motion"))
    else:
        result["reached"] = []
        result["current_chapter"] = None
        result["progress_motion"] = None
    result["unmet"] = (
        _safe_unmet(parsed.get("unmet", []), acceptance_clauses)
        if "acceptance" in tasks else []
    )
    return result


def _empty_result() -> dict:
    return {"ops": [], "reached": [], "current_chapter": None, "progress_motion": None, "unmet": []}


# ── 模型解析 ──────────────────────────────────────────────────────────

def _resolve_recorder_api_and_model(
    user_id: int | None,
    api_id_override: str | None,
    model_override: str | None,
) -> tuple[str, str]:
    """史官模型偏好：先找 recorder.*，回退到 extractor.*，再走 harness 通配。"""
    from agents._harness import resolve_api_and_model
    from core.llm_backend import (
        resolve_preferred_api as _rapi,
    )
    from core.llm_backend import (
        resolve_preferred_model as _rmodel,
    )

    # recorder 专用偏好
    rec_api = api_id_override or _rapi(user_id, pref_key="recorder.api_id")
    rec_model = model_override or _rmodel(user_id, pref_key="recorder.model_real_name")

    # 有 recorder 偏好就直接用 harness 解析（带 BYOK 守卫）
    if rec_api or rec_model:
        return resolve_api_and_model(
            user_id,
            api_pref_key="recorder.api_id",
            model_pref_key="recorder.model_real_name",
            api_id_override=api_id_override,
            model_override=model_override,
        )

    # 无 recorder 偏好 → 回退 extractor.*（再走 harness 通配兜底）
    return resolve_api_and_model(
        user_id,
        api_pref_key="extractor.api_id",
        model_pref_key="extractor.model_real_name",
        api_id_override=api_id_override,
        model_override=model_override,
    )


# ── 主入口 ────────────────────────────────────────────────────────────

def record_turn(
    gm_prose: str,
    state_data: dict,
    *,
    pending_anchors: list[dict] | None = None,   # [{anchor_key, summary, is_fatal}]
    chapter_map: list[dict] | None = None,        # [{chapter, story_time_label, summary}]
    acceptance_clauses: list[str] | None = None,
    tasks: list[str] | None = None,               # subset of ["ops","anchors","acceptance"]; default all
    user_id: int | None = None,
    model_override: str | None = None,
    api_id_override: str | None = None,
    timeout_sec: int = 25,
) -> dict:
    """ONE LLM call merging extractor + anchor judge + acceptance verifier.
    Returns {"ops":[...], "reached":[{"anchor_key","drift_score"}], "current_chapter": int|None, "unmet":[...]}.
    Never raises; returns {"ops":[],"reached":[],"current_chapter":None,"unmet":[]} on any failure.
    Only include prompt sections + request output fields for tasks that are enabled."""
    # 规范化任务集合
    if tasks is None:
        active_tasks = _ALL_TASKS
    else:
        active_tasks = frozenset(t for t in tasks if t in _ALL_TASKS)
    if not active_tasks:
        log.debug("[recorder] 没有启用任何任务，直接返回空结果")
        return _empty_result()

    # 模型解析
    try:
        api_id, model = _resolve_recorder_api_and_model(user_id, api_id_override, model_override)
    except Exception as exc:
        log.debug("[recorder] 模型解析失败，跳过: %s", exc)
        return _empty_result()
    if not api_id or not model:
        log.debug("[recorder] 无可用 api_id/model，跳过")
        return _empty_result()

    # 后果账本(consequence_ledger flag,默认关):史官是 recorder_unified 下唯一权威 ops
    # 通道,flag 开才教它 consequence op。prompt 与 tool-schema 必须同源同值(parity)。
    try:
        from core.feature_flags import feature_enabled as _feat
        _consequence_on = "ops" in active_tasks and _feat("consequence_ledger", user_id)
    except Exception:
        _consequence_on = False
    try:
        from core.feature_flags import feature_enabled as _feat_a
        _agenda_on = "ops" in active_tasks and _feat_a("npc_agenda", user_id)
    except Exception:
        _agenda_on = False

    system_prompt = _build_system_prompt(active_tasks, consequence_enabled=_consequence_on,
                                         agenda_enabled=_agenda_on)
    user_prompt = _build_user_prompt(
        gm_prose, state_data, active_tasks,
        pending_anchors, chapter_map, acceptance_clauses,
        consequence_enabled=_consequence_on,
        agenda_enabled=_agenda_on,
    )
    tool_schema = _build_tool_schema(active_tasks, acceptance_clauses,
                                     consequence_enabled=_consequence_on,
                                     agenda_enabled=_agenda_on)

    # 三通道 dispatch（优先 native tool_use / function calling）
    try:
        text, usage = _call_recorder(
            api_id=api_id,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tool_schema=tool_schema,
            user_id=user_id,
            timeout_sec=timeout_sec,
        )
    except Exception as exc:
        log.debug("[recorder] LLM 调用失败，返回空结果: %s", exc)
        return _empty_result()

    # 空正文护栏(268 实锤范式:LLM 返回空绝不静默当「没有结果」——空正文静默解析成全空
    # result 正是史官全灭 1300+ 回合无人发觉的原因)。带 reasoning_tokens 证据告警 + 扩预算
    # 重试一次(no_think 被 provider 忽略时思考仍可能吃预算,2400 给正文留余量);再空才放弃。
    if not (text or "").strip():
        _rt = int((usage or {}).get("reasoning_tokens") or 0)
        log.warning("[recorder] uid=%s %s·%s 返回空正文(reasoning_tokens=%s),扩预算重试一次",
                    user_id, api_id, model, _rt)
        try:
            text, usage = _call_recorder(
                api_id=api_id, model=model,
                system_prompt=system_prompt, user_prompt=user_prompt,
                tool_schema=tool_schema, user_id=user_id,
                timeout_sec=timeout_sec, max_tokens=2400,
            )
        except Exception as exc:
            log.debug("[recorder] 空正文重试调用失败，返回空结果: %s", exc)
            return _empty_result()
        if not (text or "").strip():
            log.warning("[recorder] uid=%s 重试仍空正文,本回合放弃(锚点/ops/验收全空)", user_id)
            return _empty_result()

    # 记 usage（史官三通道唯一记账点，不影响主流程，异常静默）。
    # dispatch 层不再自动记账,故这里记一次即准确、不双计。
    try:
        if user_id and usage and (usage.get("input_tokens") or usage.get("output_tokens")):
            from platform_app.usage import record_usage as _rec
            _rec(
                user_id=user_id,
                save_id=None,
                context_run_id=None,
                api_id=api_id,
                model_real_name=model,
                usage=usage,
                metadata={"kind": "recorder", "tasks": sorted(active_tasks)},
                scenario="extract",
            )
    except Exception:
        pass

    # 解析结果
    try:
        result = _parse_recorder_output(text, active_tasks, acceptance_clauses)
    except Exception as exc:
        log.debug("[recorder] 结果解析失败，返回空: %s", exc)
        return _empty_result()

    # 史官判定可观测:此前 progress_motion/reached 是黑盒,排查「进度不动是判断错误还是本就无节点」
    # 只能翻 DB。一行 INFO 记下本回合史官到底判了什么 —— motion=0/None 一眼可辨(0=判定无推进、
    # None=模型没吐该字段=结构化返回没生效)。
    try:
        _reached = [r.get("anchor_key") for r in (result.get("reached") or [])]
        log.info(
            "[recorder] uid=%s %s·%s → motion=%s reached=%s current_ch=%s ops=%d unmet=%d",
            user_id, api_id, model, result.get("progress_motion"),
            _reached or "[]", result.get("current_chapter"),
            len(result.get("ops") or []), len(result.get("unmet") or []),
        )
    except Exception:
        pass

    return result


# ── dispatch 层 ───────────────────────────────────────────────────────

def _call_recorder(
    api_id: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    tool_schema: dict,
    user_id: int | None,
    timeout_sec: int,
    max_tokens: int = 1200,
) -> tuple[str, dict]:
    """三通道 dispatch，返回 (text, usage)。

    层次（同 extractor._call_extractor_backend + _harness 完全一致）：
    1. Anthropic + native tool_use（强制 emit_record，schema 校验）
    2. Vertex AI + function calling（ANY 模式强制必调）
    3. OpenAI 兼容 → 复用 extractor._call_openai_compat_json_mode，传合并 json_hint

    三通道都从同一份 tool_schema 取「必答字段」(schema 强制),不再手写第三份 shape。
    usage 三通道都不在此层记账(anthropic/vertex 不传 agent_kind、openai_compat 直接调
    _openai_function_call),统一由 record_turn 记一次(scenario="extract"),避免双计。
    """
    from agents._harness import call_agent_json as _call_json

    if api_id == "anthropic":
        # native tool_use，返回 tool.input JSON
        text, usage = _call_json(
            api_id=api_id,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            user_id=user_id,
            tool_schema=tool_schema,
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
            no_think=True,  # 结构化微任务禁深思(268 实锤族)
            # 不传 agent_kind：usage 由下方 record_turn 统一记一次(scenario="extract"+tasks)。
            # 传了 agent_kind call_agent_json 会自动再记一次(scenario="tool")→ 史官用量双计。
        )
        # harness Anthropic tool_use 返回 tool.input 的 JSON（整个 dict），
        # 直接解析用
        return text, usage

    if api_id == "vertex_ai":
        # Vertex function calling
        text, usage = _call_json(
            api_id=api_id,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            user_id=user_id,
            tool_schema=tool_schema,
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
            no_think=True,  # 结构化微任务禁深思(268 实锤族)
            # 不传 agent_kind：usage 由下方 record_turn 统一记一次(scenario="extract"+tasks)。
            # 传了 agent_kind call_agent_json 会自动再记一次(scenario="tool")→ 史官用量双计。
        )
        return text, usage

    # OpenAI 兼容：走 native function-calling（forced tool_choice，schema 强校验），
    # 与 anthropic native tool_use / vertex function-call **同源于 tool_schema** ——
    # 三通道结构化返回要求从此单一来源。progress_motion / reached / current_chapter 等
    # 必答字段由 schema.required 强制,弱模型(flash 等)也漏不掉。
    #
    # 【历史根因】此前这条通道是唯一手写第三份 shape(json_hint)的分支,而那份 hint 漏了
    # progress_motion(批次1 只补进 tool_schema + _build_system_prompt,漏了这里),且末尾
    # 「严格符合此形状」把它当权威 → 便宜模型据此永不吐 progress_motion → _safe_progress_motion(None)
    # → pace fallback 永不触发 → 发散局进度冻死(行者无疆实测)。删掉手写 hint,消除漂移。
    #
    # _openai_function_call 内部对「中转拒绝 tools 形态」(403/400/404/405/422,群反馈实锤 op/xf
    # 等中转)自动降级到 json_object 兼容模式,降级时用的正是这里传入的 base system_prompt
    # (_build_system_prompt 的 schema_fields 已含 progress_motion + ops item 形状,json_object
    # 下弱模型也不会把 ops 输出成裸字符串)。直接调(不经 call_agent_json)避免与下方 record_turn
    # 的 record_usage 双计。
    from agents._harness import _openai_function_call
    text, usage = _openai_function_call(
        api_id=api_id,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tool_schema=tool_schema,
        user_id=user_id,
        timeout_sec=timeout_sec,
        max_tokens=max_tokens,
        # [268 二连实锤] 史官是生产在线回合唯一的锚点验收/估章/motion/ops 通道;op 中转拒 tools
        # 降级 json_object 后,思考模型(op/deepseek-v4-flash)无界思考吃光 1200 预算 → 正文 0 字
        # → 全字段静默空 → 锚点永不验收反复重演/进度冻结/时间倒流。v1.67.1 只接了 _default_judge
        # (生产不走),这里才是真正的生产缝。
        no_think=True,
    )
    return text, usage


__all__ = ["record_turn"]
