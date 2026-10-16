"""
command_tools.py — task 86: LLM 命令工具表。

设计理念 (用户反馈):
> 规则判断永远会有 bug。用 LLM 接管命令,用大模型理解用户自然语言,
> 然后对照实际支持的命令表用"工具调用"完成指令。
> 不要再让规则判断束缚大模型的手脚。

每个工具:
  · 名字 + JSON Schema 描述参数
  · 一个执行函数,直接对接 GameState 的 public API
  · 不暴露权限/历史/元数据写入(这些没有对应工具,LLM 不能调出来)

工具列表 (12 个,覆盖 /set 几乎所有合理用法):

  时间/位置/世界:
    set_world_time          世界时间 = X(走 update_time(source='user_set'))
    set_player_location     玩家当前位置 = X
    set_world_known_event   往 world.known_events 追加一条

  玩家档案:
    set_player_name         玩家姓名
    set_player_role         玩家身份/职业
    set_player_background   玩家背景

  关系:
    set_relationship        某 NPC 的关系状态

  记忆:
    set_main_quest          主线任务
    set_current_objective   当前目标
    add_memory_fact         事实
    add_memory_resource     资源
    add_memory_ability      能力
    pin_memory              固定记忆(高优先级)
    add_memory_note         笔记

  推测/世界线:
    add_hypothesis          推测/计划/草稿
    set_user_variable       玩家世界线硬约束变量

如果工具表里没有用户想做的事(比如改 permissions),LLM 无法找到对应工具
→ command_agent 应返回 "没有对应工具" 让 chat handler 提示用户。
这是设计上的安全特性:没有工具就不能写。
"""
from __future__ import annotations

from typing import Any

# ────────────────────────────────────────────────────────────
# Tool schema (Anthropic tool_use input_schema 兼容)
# ────────────────────────────────────────────────────────────


COMMAND_TOOLS: list[dict[str, Any]] = [
    {
        "name": "set_world_field",
        "description": (
            '[Recommended entry point - merged] Set any world.* field. The key decides how it is written:\n'
            '· "time": goes through update_time and triggers timeline inference (same as the old set_world_time)\n'
            '· "location": goes through update_location and triggers a scene refresh (same as the old set_player_location, but writes world.location)\n'
            '· any other key: writes world[key] (same as the old set_world_attribute, but time is allowed too)\n'
            'Replaces the 3 separate tools set_world_time / set_player_location / set_world_attribute.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Field name under world to write"},
                "value": {"type": "string", "description": "New value (string)"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "set_world_time",
        "description": (
            "Set the world's current time / timeline anchor to a new value. Use this whenever the user writes things like "
            '"set the time to Mars - inside Landing City" / "timeline = the lunar period" / "switch time to the Berlin undercurrent arc". '
            "**Important**: this is a hard user override; it triggers the narrative_guard check, and next turn the GM must not write transitional narration such as time travel or waking up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "New time / timeline label, any user description, e.g. 'Mars - inside Landing City', 'the lunar period of the story', 'Berlin undercurrent arc'",
                }
            },
            "required": ["target"],
        },
    },
    {
        "name": "set_player_location",
        "description": 'Set the player\'s current location. Use this whenever the user writes "move location to X" / "at X" / "current location = X", etc.',
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "New current location label"},
            },
            "required": ["location"],
        },
    },
    {
        "name": "set_world_known_event",
        "description": (
            '[Event tools: pick 1 of 5 - decision tree] To record something that has happened, choose the right tool:\n'
            '· set_world_known_event (this tool): a one-line quick log in world.known_events, **not stored in the KB / not in the history record / does not affect retrieval**. Good for small passing events such as "the patrol changed shifts".\n'
            '· vs record_history_anchor: use it when the player did something with importance>=60 (changed an NPC relationship / faction stance / rewrote a canon anchor); it writes the **save\'s own history timeline**, and retrieve_context injects it to the GM as [past tense] next time.\n'
            '· vs kb_record_event: goes into the KB world tree (canon_entities/graph_edges permanent layer) and is found by search_canon/graph_neighbors. Use it for **relationship / faction changes between NPCs in this playthrough**.\n'
            '· vs add_memory_fact: personal / character-level "I know X" goes to memory.facts, e.g. "I remember hiding the key under the stove"; it is **not a public world-level event**.\n'
            '· vs mark_anchor_satisfied: if the source script has this anchor and it has been triggered, use mark_anchor_satisfied with drift_score; **do not also** write it to known_events.\n'
            '\nBottom line: this tool is the weakest "running log" level; prefer the other 4.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event": {"type": "string", "description": "Event description"},
            },
            "required": ["event"],
        },
    },
    {
        "name": "set_world_attribute",
        "description": (
            'Set a scalar attribute world.<key>, such as weather/atmosphere/season/region. '
            'Cannot be used to change time/timeline (use the dedicated tool set_world_time for that).'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string",
                        "description": "Attribute name under world, e.g. weather/atmosphere"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "confirm_time_jump",
        "description": (
            'Confirm a pending time jump. After the player proposes a jump in natural language, '
            'the GM asks "jump to X?", and when the player answers "confirm", call this tool. target is optional; '
            'defaults to pending_jump.to.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Optional; the time label to jump to"},
            },
            "required": [],
        },
    },
    {
        "name": "reject_time_jump",
        "description": (
            'Reject a pending time jump: clears pending_jump and keeps the original timeline.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Reason for rejecting, optional"},
            },
            "required": [],
        },
    },
    {
        "name": "set_player_name",
        "description": "Set the player character's name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "set_player_role",
        "description": 'Set the player\'s identity / occupation / role (e.g. "Transmigrator - Witch", "exiled noble").',
        "input_schema": {
            "type": "object",
            "properties": {"role": {"type": "string"}},
            "required": ["role"],
        },
    },
    {
        "name": "set_player_background",
        "description": "Set the player's backstory (free text).",
        "input_schema": {
            "type": "object",
            "properties": {"background": {"type": "string"}},
            "required": ["background"],
        },
    },
    {
        "name": "set_player_appearance",
        "description": "Set the player's appearance description (replaces it entirely).",
        "input_schema": {
            "type": "object",
            "properties": {"appearance": {"type": "string"}},
            "required": ["appearance"],
        },
    },
    {
        "name": "set_player_personality",
        "description": "Set the player's personality / detailed profile (replaces it entirely).",
        "input_schema": {
            "type": "object",
            "properties": {"personality": {"type": "string"}},
            "required": ["personality"],
        },
    },
    {
        "name": "set_player_speech_style",
        "description": "Set the player's tone / way of speaking (replaces it entirely).",
        "input_schema": {
            "type": "object",
            "properties": {"speech_style": {"type": "string"}},
            "required": ["speech_style"],
        },
    },
    {
        "name": "set_relationship",
        "description": (
            'Set the relationship status between the player and an NPC. Use this when the user writes "NPC relationship = trust" / "X is wary of me", etc.\n'
            "Example: set_relationship(character=\"Rosemary\", status=\"close\")"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "character": {"type": "string", "description": "NPC name (the field is named character, not npc_name)"},
                "status": {"type": "string",
                           "description": "Relationship status description (the field is named status, not status_label), e.g. 'trusting/wary/hostile/close/tense/distant'"},
            },
            "required": ["character", "status"],
        },
    },
    {
        "name": "delete_relationship",
        "description": 'Delete the relationship entry between the player and an NPC (removes the whole entry rather than clearing it). Called when the user clicks x on a relationship card in the sidebar.',
        "input_schema": {
            "type": "object",
            "properties": {
                "character": {"type": "string", "description": "Name of the NPC to delete"},
            },
            "required": ["character"],
        },
    },
    {
        "name": "set_timeline_phase",
        "description": (
            'Set the worldline\'s current phase label (world.timeline.current_phase). '
            'It is recorded in user_locked_fields, so later update_time calls no longer overwrite it via _phase_for_time inference. '
            'Called when the user picks/types a phase directly in the sidebar.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phase": {"type": "string", "description": "Phase label, e.g. 'Berlin undercurrent arc / lunar period'"},
            },
            "required": ["phase"],
        },
    },
    {
        "name": "set_main_quest",
        "description": "Set the main quest text.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "set_current_objective",
        "description": "Set the current (short-term) objective.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "advance_story_progress",
        "description": (
            "Advance the player's progress to the given source-novel chapter number (progress_chapter; monotonic, only increases, never goes back). "
            "Use it when the player has [already played through] a stretch of story but system progress has not caught up - typically self-insert / divergent play "
            "(e.g. infinite-flow instance runs) whose plot does not hit canon anchors, so progress is stuck at an early chapter. The player catches it up explicitly. "
            "Affects: the floor of the anti-spoiler ceiling, the retrieval window, and the starting chapter for soft guidance's 'next beat'. "
            "Call it when the player says 'advance to chapter X / I'm already past chapter X / jump progress to chapter X / I've played through a dozen chapters but it's still stuck at chapter 7 or 8'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_chapter": {
                    "type": "integer",
                    "description": "Target source chapter number (>=1). Values below current progress are ignored (monotonic, never decreases).",
                },
            },
            "required": ["to_chapter"],
        },
    },
    {
        "name": "add_memory",
        "description": (
            '[Recommended entry point - merged] Append one entry to any memory bucket. The bucket enum picks the bucket:\n'
            '· "facts": facts known in this playthrough (player: "I note down X")\n'
            '· "resources": items/resources (player: "I have X" / "obtained X")\n'
            '· "abilities": abilities/skills\n'
            '· "notes": low-priority notes\n'
            '· "pinned": high-priority pinned entries (you can also pass pin=true when writing facts/resources)\n'
            'Replaces the 5 separate tools add_memory_fact/resource/ability/note/pin_memory, '
            'shrinking the GM\'s decision surface; the old tools remain for backward compatibility, but the GM should prefer this one.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bucket": {"type": "string", "enum": ["facts", "resources", "abilities", "notes", "pinned"]},
                "text": {"type": "string"},
                "pin": {"type": "boolean", "description": "true = also write it to the pinned bucket (high-priority duplicate)"},
            },
            "required": ["bucket", "text"],
        },
    },
    {
        "name": "add_memory_fact",
        "description": '[DEPRECATED] Same as add_memory(bucket="facts", text=X). Use add_memory instead.',
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add_memory_resource",
        "description": '[DEPRECATED] Same as add_memory(bucket="resources", text=X). Use add_memory instead.',
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add_memory_ability",
        "description": '[DEPRECATED] Same as add_memory(bucket="abilities", text=X). Use add_memory instead.',
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "pin_memory",
        "description": '[DEPRECATED] Same as add_memory(bucket="pinned", text=X). Use add_memory instead.',
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add_memory_note",
        "description": '[DEPRECATED] Same as add_memory(bucket="notes", text=X). Use add_memory instead.',
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add_hypothesis",
        "description": 'Record a hypothesis / plan / draft. Unlike add_memory_fact, a hypothesis is **not** a fact.',
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "characters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "NPC/character names involved, optional",
                },
                "time_label": {
                    "type": "string",
                    "description": "Time label at which the hypothesis applies, optional",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "set_user_variable",
        "description": (
            'Set a player hard-constraint variable (worldline.user_variables). Used to force the direction of the story, '
            'e.g. "trust_slaine=trust declining". Unlike add_memory_fact, a user_variable is an explicit constraint that worldline simulation must satisfy first.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Variable name (ASCII identifier, e.g. trust_slaine)"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "clarify",
        "description": (
            "When you cannot clearly map the user's words to any tool above, or the user's sentence is ambiguous, "
            "use this tool to ask the user. Use it **only when you genuinely cannot decide**."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question for the user"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional choices, 2-4 items",
                },
            },
            "required": ["question"],
        },
    },
]


# ────────────────────────────────────────────────────────────
# Tool execution: 直接调 GameState public API
# ────────────────────────────────────────────────────────────


def _set_player_profile_field(state, args, field, label):
    """玩家人设卡字段(appearance/personality/speech_style/background)的整体替换写入。

    锁语义:玩家亲手改过的字段(_origin ∈ 用户意图集)会被 mark_user_locked,
    此后 GM/史官的自动改写(_origin=llm_chat_json_op 等,即史官 ops 路由)一律被拒,
    只能玩家再从状态面板手动改。dispatcher 已无条件覆盖 args["_origin"]=env.origin,
    故此处读到的 _origin 不可被 LLM 伪造。"""
    v = (args.get(field) or "").strip()
    if not v:
        return f"set_player_{field} failed: {field} is empty"
    path = f"player.{field}"
    origin = str(args.get("_origin") or "")
    user_intent = origin in ("ui_button", "llm_set", "api_direct")
    if not user_intent and state._is_user_locked(path):
        return f"Failed: the player's {label} was customized by the player (locked); the GM/chronicler may not rewrite it automatically. The player can edit it in the status panel"
    state.data.setdefault("player", {})[field] = v
    if user_intent:
        try:
            state.mark_user_locked(path)
        except Exception:
            pass
    return f"Player {label} -> {v[:40]}"


def _exec_set_world_field(state, args) -> str:
    key = (args.get("key") or "").strip()
    value = (args.get("value") or "").strip()
    if not key or not value:
        return "set_world_field failed: key or value is empty"
    if key == "time":
        return execute_tool(state, "set_world_time", {"target": value})
    if key == "location":
        return execute_tool(state, "set_player_location", {"location": value})
    return execute_tool(state, "set_world_attribute", {"key": key, "value": value})


def _exec_add_memory(state, args) -> str:
    bucket = (args.get("bucket") or "").strip()
    text = (args.get("text") or "").strip()
    pin = bool(args.get("pin"))
    if not bucket or not text:
        return "add_memory failed: bucket or text is empty"
    valid_buckets = {"facts", "resources", "abilities", "notes", "pinned"}
    if bucket not in valid_buckets:
        return f"add_memory failed: invalid bucket ({bucket} not in {valid_buckets})"
    # dispatch 到对应旧 executor
    old_map = {
        "facts": "add_memory_fact",
        "resources": "add_memory_resource",
        "abilities": "add_memory_ability",
        "notes": "add_memory_note",
        "pinned": "pin_memory",
    }
    main = execute_tool(state, old_map[bucket], {"text": text})
    if pin and bucket != "pinned":
        pin_r = execute_tool(state, "pin_memory", {"text": text})
        return f"{main} + also pinned: {pin_r}"
    return main


def _exec_set_world_time(state, args) -> str:
    target = (args.get("target") or "").strip()
    if not target:
        return "set_world_time failed: target is empty"
    old = state.data.get("world", {}).get("time", "")
    state.update_time(target, source="user_set")
    # 时间连续性护栏 v0:天数倒退检测(检测→surface,不拦截;解析不出天数即休眠)。
    try:
        from state.time_ops import detect_day_regression
        _regress = detect_day_regression(old, target)
    except Exception:
        _regress = None
    if _regress:
        try:
            from datetime import datetime as _dt
            _audit = state.data.setdefault("permissions", {}).setdefault("audit_log", [])
            _audit.append({
                "ts": _dt.now().isoformat(timespec="seconds"),
                "kind": "time_day_regression",
                "source": "time_continuity_guard",
                "turn": int(state.data.get("turn") or 0),
                "from": old, "to": target,
                "hint": _regress,
            })
            state.data["permissions"]["audit_log"] = _audit[-200:]
        except Exception:
            pass
        return f"Timeline -> {target} (was: {old}) ⚠ {_regress}"
    return f"Timeline -> {target} (was: {old})"


def _exec_set_world_known_event(state, args) -> str:
    event = (args.get("event") or "").strip()
    if not event:
        return "set_world_known_event failed: event is empty"
    # acceptance 验收元信息属流水线审计,不进玩家可见事件库(与 apply_ops 列表闸/
    # save_kb.materialize 同谓词,dispatcher 工具路径是第三个写入口)。
    from state.json_ops import is_acceptance_meta
    if is_acceptance_meta(event):
        return "set_world_known_event ignored: acceptance-check metadata does not go into the event log"
    events = state.data.setdefault("world", {}).setdefault("known_events", [])
    if event not in events:
        events.append(event)
        # 硬上限:known_events 原本无 cap,GM 每轮记流水账长局后会无界堆积撑大
        # state_snapshot(持久化进 DB)。注入只看最近 15 条,故保留最近 100 条足矣。
        if len(events) > 100:
            del events[:-100]
        return f"Known events += {event}"
    return f"Known event already exists: {event}"


def _exec_set_world_attribute(state, args) -> str:
    key = (args.get("key") or "").strip()
    value = (args.get("value") or "").strip()
    if not key or not value:
        return "set_world_attribute failed: key or value is empty"
    # 禁用 time/timeline (有专门工具)
    if key in {"time", "timeline"}:
        return f"set_world_attribute failed: use set_world_time to change {key}"
    world = state.data.setdefault("world", {})
    world[key] = value
    return f"world.{key} = {value}"


def _exec_confirm_time_jump(state, args) -> str:
    target = (args.get("target") or "").strip() or None
    timeline = (state.data.get("world") or {}).get("timeline") or {}
    pending = timeline.get("pending_jump") or {}
    actual_target = target or pending.get("to") or state.data.get("world", {}).get("time")
    if not pending:
        return "confirm_time_jump failed: there is no pending_jump awaiting confirmation"
    state.confirm_time_jump(actual_target)
    return f"Time jump confirmed -> {actual_target}"


def _exec_delete_relationship(state, args) -> str:
    ch = (args.get("character") or "").strip()
    if not ch:
        return "delete_relationship failed: character is empty"
    rels = state.data.setdefault("relationships", {})
    if ch not in rels:
        return f"delete_relationship: {ch} is not in relationships (nothing to delete)"
    del rels[ch]
    return f"Relationship deleted: {ch}"


def _exec_set_timeline_phase(state, args) -> str:
    phase = (args.get("phase") or "").strip()
    if not phase:
        return "set_timeline_phase failed: phase is empty"
    timeline = state.data.setdefault("world", {}).setdefault("timeline", {})
    old = timeline.get("current_phase", "")
    timeline["current_phase"] = phase
    # 走现成 mark_user_locked,后续 update_time / _phase_for_time 不再覆盖
    try:
        state.mark_user_locked("world.timeline.current_phase")
    except Exception:
        pass
    return f"timeline.current_phase: {old or '∅'} → {phase}"


def _exec_advance_story_progress(state, args) -> str:
    raw = args.get("to_chapter")
    try:
        to_ch = int(raw)
    except (TypeError, ValueError):
        return "advance_story_progress failed: to_chapter must be an integer chapter number"
    if to_ch < 1:
        return "advance_story_progress failed: to_chapter must be >= 1"
    # save_id 由 dispatcher 无条件注入 args(服务端绑定、防跨档),不信任 state。
    sid = args.get("save_id")
    if not sid:
        return "advance_story_progress failed: no active save (save not ready)"
    clamp_note = ""
    try:
        from gm_serving.settings import advance_progress, read_settings, set_user_progress_floor
        from platform_app.db import connect
        with connect() as db:
            # 手滑护栏:advance_progress 是 max-only 单调,目标超剧本实际章数
            # (如想打 30 打成 300)会顶死进度并炸开全部防剧透 → 钳到最后一章。
            # 无剧本档(script_id null/酒馆)或章表空时不钳,发散语义保留。
            row = db.execute(
                "select coalesce(max(sc.chapter_index), 0) as m "
                "from game_saves gs join script_chapters sc on sc.script_id = gs.script_id "
                "where gs.id = %s",
                (int(sid),),
            ).fetchone()
            max_ch = int((row or {}).get("m") or 0)
            if max_ch > 0 and to_ch > max_ch:
                clamp_note = f" (target chapter {to_ch} exceeds the script's {max_ch} chapters; advanced to chapter {max_ch} instead)"
                to_ch = max_ch
            before = (read_settings(db, int(sid)) or {}).get("progress_chapter")
            advance_progress(db, int(sid), to_ch)  # max-only,单调只增
            # 玩家显式跳章=确定性地板,揭示钳制(clamp_reveal_progress)对它放行,
            # 逃生阀语义保留(d50eb926a)。
            set_user_progress_floor(db, int(sid), to_ch)
            after = (read_settings(db, int(sid)) or {}).get("progress_chapter")
    except Exception as exc:
        return f"advance_story_progress failed: {type(exc).__name__}: {exc}"
    if before is not None and after is not None and int(after) == int(before):
        return f"Progress unchanged: already at chapter {after} (target chapter {to_ch} <= current; progress never goes back){clamp_note}"
    return f"Progress advanced: chapter {before} -> chapter {after}{clamp_note}"


def _exec_add_hypothesis(state, args) -> str:
    v = (args.get("text") or "").strip()
    if not v:
        return "add_hypothesis failed: text is empty"
    # 权限闸门(孪生洞补齐):本工具直调 state.add_hypothesis,绕过 apply_state_write 权限
    # 闸门。推测经 context_providers/memory.py 以「未确认推测」注入 GM 上下文,有真实叙事
    # 影响,与 apply_ops.py 的 JSON-op "hypothesis" 分支同构须闸——同走 add_pending_narrative_op
    # 入队、同 _approve_narrative_op_pending 回放(value 键 text/time_label/characters 一致)。
    # GM 自主写(llm_chat/llm_chat_json_op)在 read_only/default 下入 pending 不直写;玩家主动
    # origin(ui_button/llm_set/api_direct = UI 按钮 / /set 命令 / 直接 API)属玩家意志,豁免
    # 直写。_origin 由 dispatcher 无条件注入(env.args["_origin"]=env.origin),不可被 LLM
    # 伪造;user_intent 判定口径对照本域 _set_player_profile_field 的现行读法。
    origin = str(args.get("_origin") or "")
    user_intent = origin in ("ui_button", "llm_set", "api_direct")
    if not user_intent and state._gm_narrative_needs_pending():
        return state.add_pending_narrative_op(
            "hypothesis",
            {"text": v, "time_label": args.get("time_label"),
             "characters": args.get("characters")},
            source="gm:tool",
            display=f"Hypothesis recorded: {v[:40]}",
        )
    hid = state.add_hypothesis(
        text=v,
        source="user:/set:tool",
        time_label=args.get("time_label"),
        characters=args.get("characters"),
    )
    return f"Hypothesis recorded: {hid}"



def execute_tool(state: Any, name: str, args: dict) -> str:
    """执行单个工具调用,返回人类可读的执行结果文本。

    失败 (state 没有对应方法 / 参数缺) 不抛异常,返回错误描述,
    让 command_agent 写到 audit_log 让 LLM 自纠或前端展示。
    """
    try:
        # iter#6 合并版入口 — dispatch 到对应旧 executor 路径
        if name == "set_world_field":
            return _exec_set_world_field(state, args)
        if name == "add_memory":
            return _exec_add_memory(state, args)
        if name == "set_world_time":
            return _exec_set_world_time(state, args)
        if name == "set_player_location":
            loc = (args.get("location") or "").strip()
            if not loc:
                return "set_player_location failed: location is empty"
            state.update_location(loc)
            return f"Location -> {loc}"
        if name == "set_world_known_event":
            return _exec_set_world_known_event(state, args)
        if name == "set_world_attribute":
            return _exec_set_world_attribute(state, args)
        if name == "confirm_time_jump":
            return _exec_confirm_time_jump(state, args)
        if name == "reject_time_jump":
            reason = (args.get("reason") or "Rejected by the player").strip()
            timeline = (state.data.get("world") or {}).get("timeline") or {}
            if not (timeline.get("pending_jump")):
                return "reject_time_jump failed: there is no pending_jump awaiting confirmation"
            state.reject_time_jump(reason)
            return f"Time jump cancelled: {reason}"
        if name == "set_player_name":
            v = (args.get("name") or "").strip()
            if not v:
                return "set_player_name failed: name is empty"
            state.data.setdefault("player", {})["name"] = v
            return f"Player name -> {v}"
        if name == "set_player_role":
            v = (args.get("role") or "").strip()
            if not v:
                return "set_player_role failed: role is empty"
            state.data.setdefault("player", {})["role"] = v
            return f"Player role -> {v}"
        if name == "set_player_background":
            return _set_player_profile_field(state, args, "background", "background")
        if name == "set_player_appearance":
            return _set_player_profile_field(state, args, "appearance", "appearance")
        if name == "set_player_personality":
            return _set_player_profile_field(state, args, "personality", "personality")
        if name == "set_player_speech_style":
            return _set_player_profile_field(state, args, "speech_style", "speech style")
        if name == "set_relationship":
            ch = (args.get("character") or "").strip()
            st = (args.get("status") or "").strip()
            if not ch or not st:
                return "set_relationship failed: character or status is empty"
            state.update_relationship(ch, st)
            return f"Relationship {ch} -> {st}"
        if name == "delete_relationship":
            return _exec_delete_relationship(state, args)
        if name == "set_timeline_phase":
            return _exec_set_timeline_phase(state, args)
        if name == "set_main_quest":
            v = (args.get("text") or "").strip()
            if not v:
                return "set_main_quest failed: text is empty"
            state.data.setdefault("memory", {})["main_quest"] = v
            # 打「上次更新回合」戳 —— 陈旧提醒靠它。写入路径有两条(本执行器 + apply_ops
            # 老路径的标量分支),两条都要戳,漏一条主线就会假性陈旧、天天被催。
            from state.quest_staleness import stamp_main_quest
            stamp_main_quest(state.data)
            return f"Main quest -> {v}"
        if name == "set_current_objective":
            v = (args.get("text") or "").strip()
            if not v:
                return "set_current_objective failed: text is empty"
            state.data.setdefault("memory", {})["current_objective"] = v
            return f"Current objective -> {v}"
        if name == "advance_story_progress":
            return _exec_advance_story_progress(state, args)
        if name in ("add_memory_fact", "add_memory_resource", "add_memory_ability",
                     "pin_memory", "add_memory_note"):
            bucket = {
                "add_memory_fact": "facts",
                "add_memory_resource": "resources",
                "add_memory_ability": "abilities",
                "pin_memory": "pinned",
                "add_memory_note": "notes",
            }[name]
            v = (args.get("text") or "").strip()
            if not v:
                return f"{name} failed: text is empty"
            # _origin 由 dispatcher 无条件注入(用户意图分流的既有约定):玩家自己的写入
            # 不受洪泛闸,GM/史官的受。拒绝理由原样回给 GM,让它下一轮自己合并。
            ok, why = state.add_memory_ex(bucket, v, origin=str(args.get("_origin") or ""))
            if ok:
                return f"memory.{bucket} += {v}"
            # why 来自 state.add_memory_ex(中文或英文化后的去重文案都认)
            if why and "去重" not in why and "dedup" not in why.lower() and "duplicate" not in why.lower():
                return f"Failed: {name} was rejected - {why}"
            return f"memory.{bucket} already contains this entry (deduplicated)"
        if name == "add_hypothesis":
            return _exec_add_hypothesis(state, args)
        if name == "set_user_variable":
            k = (args.get("key") or "").strip()
            v = (args.get("value") or "").strip()
            if not k or not v:
                return "set_user_variable failed: key or value is empty"
            state.set_user_variable(k, v, source="user:/set:tool")
            return f"user_variables.{k} = {v}"
        if name == "clarify":
            q = (args.get("question") or "").strip()
            opts = args.get("options") or []
            return f"clarify: {q} (options: {opts})"
        return f"unknown tool: {name}"
    except Exception as exc:
        return f"{name} error: {type(exc).__name__}: {exc}"


# Public re-exports
__all__ = ["COMMAND_TOOLS", "execute_tool"]
