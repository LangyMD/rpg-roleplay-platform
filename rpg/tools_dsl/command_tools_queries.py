"""
command_tools_queries.py — task 87 Phase 3: B 类只读查询工具。

让 LLM 主动检索上下文,而不是被动接受静态 prompt 摘要。

scope 划分:
  global  : 无作用域要求 (list_models, list_tools)
  user    : 当前用户的资源 (list_my_personas, list_my_character_cards)
  script  : 当前剧本的资源 (get_chapter_facts, list_script_npcs)
  save    : 当前 save 状态 (query_memory, get_current_scene, get_user_variables)

所有工具不写 state,只读;允许所有 origin 调用。
"""
from __future__ import annotations

import json
from typing import Any

from tools_dsl.command_dispatcher import ToolSpec, get_registry

# task 48: console_assistant 是 user-driven agent,所有 read 工具都对它开放
_READ_ANY_ORIGIN = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat", "mcp_call", "console_assistant",
})


# ── save 级 (读 GameState) ──────────────────────────────


def _t_get_game_state(state: Any, args: dict) -> str:
    fields = args.get("fields") or []
    if not isinstance(fields, list):
        fields = []
    d = state.data
    snapshot = {
        "turn": d.get("turn"),
        "player": d.get("player", {}),
        "world": {
            "time": (d.get("world") or {}).get("time"),
            "timeline": {
                "current_label": ((d.get("world") or {}).get("timeline") or {}).get("current_label"),
                "current_phase": ((d.get("world") or {}).get("timeline") or {}).get("current_phase"),
                "user_set_jump_turn": ((d.get("world") or {}).get("timeline") or {}).get("user_set_jump_turn"),
            },
            "known_events": (d.get("world") or {}).get("known_events", [])[-10:],
        },
        "relationships": d.get("relationships", {}),
        "memory": {
            "main_quest": (d.get("memory") or {}).get("main_quest"),
            "current_objective": (d.get("memory") or {}).get("current_objective"),
            "mode": (d.get("memory") or {}).get("mode"),
        },
    }
    if fields:
        snapshot = {k: v for k, v in snapshot.items() if k in set(fields)}
    return json.dumps(snapshot, ensure_ascii=False, indent=2)


def _t_query_memory(state: Any, args: dict) -> str:
    kind = (args.get("kind") or "").strip() or None
    characters = args.get("characters") or []
    time_label = (args.get("time_label") or "").strip() or None
    limit = int(args.get("limit") or 20)
    items = (state.data.get("memory") or {}).get("items") or []
    out = []
    for it in items[-200:]:
        if kind and it.get("kind") != kind:
            continue
        if characters:
            it_chars = it.get("characters") or []
            if not any(c in it_chars for c in characters):
                continue
        if time_label and it.get("time_label") != time_label:
            continue
        out.append({
            "id": it.get("id"),
            "kind": it.get("kind"),
            "text": it.get("text"),
            "turn": it.get("turn"),
            "time_label": it.get("time_label"),
            "characters": it.get("characters"),
        })
        if len(out) >= limit:
            break
    if not out:
        return "(no matches)"
    return json.dumps(out, ensure_ascii=False, indent=2)


def _t_get_user_variables(state: Any, args: dict) -> str:
    variables = (state.data.get("worldline") or {}).get("user_variables") or {}
    if not variables:
        return "(no user_variables)"
    out = {k: v.get("value") for k, v in variables.items()}
    return json.dumps(out, ensure_ascii=False, indent=2)


def _t_get_current_scene(state: Any, args: dict) -> str:
    scene = state.data.get("scene") or {}
    enc = state.data.get("encounter") or {}
    return json.dumps({
        "module_id": scene.get("module_id"),
        "location_id": scene.get("location_id"),
        "visible_clues": scene.get("visible_clues"),
        "exits": scene.get("exits"),
        "encounter_active": enc.get("active"),
        "active_entities": state.data.get("active_entities", []),
    }, ensure_ascii=False, indent=2)


def _t_get_known_events(state: Any, args: dict) -> str:
    events = (state.data.get("world") or {}).get("known_events") or []
    limit = int(args.get("limit") or 20)
    return json.dumps(events[-limit:], ensure_ascii=False, indent=2)


def _t_list_relationships(state: Any, args: dict) -> str:
    rels = state.data.get("relationships") or {}
    return json.dumps(rels, ensure_ascii=False, indent=2)


def _t_get_pending_questions(state: Any, args: dict) -> str:
    qs = (state.data.get("permissions") or {}).get("pending_questions") or []
    return json.dumps(qs, ensure_ascii=False, indent=2)


def _t_get_pending_writes(state: Any, args: dict) -> str:
    pws = (state.data.get("permissions") or {}).get("pending_writes") or []
    return json.dumps(pws, ensure_ascii=False, indent=2)


def _t_recent_audit_log(state: Any, args: dict) -> str:
    limit = int(args.get("limit") or 10)
    kind_filter = (args.get("kind") or "").strip() or None
    audit = (state.data.get("permissions") or {}).get("audit_log") or []
    if kind_filter:
        audit = [a for a in audit if a.get("kind") == kind_filter]
    return json.dumps(audit[-limit:], ensure_ascii=False, indent=2)


# ── user 级 (读 DB) ─────────────────────────────────────


def _t_list_my_personas(user_id: int, args: dict) -> str:
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            rows = db.execute(
                "select id, name, identity as role, personality, is_default "
                "from character_cards where user_id = %s and card_type = 'persona' "
                "order by updated_at desc limit 30",
                (user_id,),
            ).fetchall() or []
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2) if rows else "(no personas)"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_list_my_character_cards(user_id: int, args: dict) -> str:
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            rows = db.execute(
                "select id, name, identity, personality, enabled "
                "from character_cards where user_id = %s and card_type = 'pc' "
                "order by updated_at desc limit 50",
                (user_id,),
            ).fetchall() or []
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2) if rows else "(no cards)"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_get_my_usage(user_id: int, args: dict) -> str:
    days = int(args.get("days") or 30)
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            rows = db.execute(
                "select date_trunc('day', created_at) as day, "
                "sum(input_tokens) as in_t, sum(output_tokens) as out_t, count(*) as n "
                "from llm_usage_log where user_id = %s and created_at > now() - %s::interval "
                "group by day order by day desc limit 30",
                (user_id, f"{days} days"),
            ).fetchall() or []
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


# ── script 级 (读剧本数据) ──────────────────────────────


def _t_list_scripts(user_id: int, args: dict) -> str:
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            rows = db.execute(
                "select id, title, chapter_count, word_count from scripts "
                "where owner_id = %s "
                "order by updated_at desc limit 50",
                (user_id,),
            ).fetchall() or []
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2) if rows else "(no scripts)"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _user_can_read_script(db, sid: int, user_id: int) -> bool:
    """剧本读权限:owner 或订阅者。防 LLM 用任意 script_id 跨用户读他人私有剧本(章节/NPC)。

    权威谓词收敛到 platform_app.perms.script_readable(owner ∪ subscription),此处保留
    同名壳(被 tests 的 patch-where-used 锚定)+ int(sid) 强转位置与异常行为。
    """
    from platform_app.perms import script_readable
    return bool(script_readable(db, int(sid), user_id))


def _t_get_script_chapters(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    sid = script_id or args.get("script_id")
    if not sid:
        return "Failed: script_id is required"
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if not _user_can_read_script(db, int(sid), user_id):
                return f"Failed (permission): script #{int(sid)} does not belong to the current user or is not subscribed"
            # summary 权威源是 chapter_facts(提取流程写入,列名 chapter);script_chapters
            # 从无 summary 列(旧查询 100% UndefinedColumn)。LEFT JOIN 保留全量章节(标题/序
            # 来自权威的 script_chapters,未提取的章节不丢),summary 有则补、无则空串。
            rows = db.execute(
                "select sc.chapter_index, sc.title, coalesce(cf.summary, '') as summary "
                "from script_chapters sc "
                "left join chapter_facts cf "
                "  on cf.script_id = sc.script_id and cf.chapter = sc.chapter_index "
                "where sc.script_id = %s order by sc.chapter_index limit 200",
                (int(sid),),
            ).fetchall() or []
        return json.dumps([dict(r) for r in rows[:50]], ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_list_script_npcs(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """列出剧本的 NPC 角色卡(精简清单)。

    历史 bug:之前查的是 v28 起已不存在的 `script_character_cards` 表 + `summary` 列,
    在线上 100% UndefinedTable 抛错 → LLM「提取不到 NPC 角色卡」。NPC 卡的权威表是
    `character_cards`(card_type='npc',按 script_id 归属)。这里只返回挑卡所需的精简字段;
    要完整人设(背景/外貌/性格/语气/范例对白)走 get_script_character_card。
    """
    sid = script_id or args.get("script_id")
    if not sid:
        return "Failed: script_id is required"
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if not _user_can_read_script(db, int(sid), user_id):
                return f"Failed (permission): script #{int(sid)} does not belong to the current user or is not subscribed"
            rows = db.execute(
                "select id, name, full_name, identity, importance, "
                "       first_revealed_chapter, "
                "       (avatar_path is not null and avatar_path <> '') as has_avatar "
                "from character_cards "
                "where script_id = %s and card_type = 'npc' and coalesce(enabled, true) "
                "order by importance desc nulls last, name "
                "limit 80",
                (int(sid),),
            ).fetchall() or []
        if not rows:
            return (
                f"(Script #{int(sid)} has no NPC character cards yet. The script may not have extracted/generated character cards - "
                "ask the user to generate them in the script editor, or sketch them yourself from the plot via get_script_chapters / get_chapter_facts.)"
            )
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_get_script_character_card(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """读取剧本内某张 NPC 角色卡的完整人设(先用 list_script_npcs 拿 id)。"""
    sid = script_id or args.get("script_id")
    card_id = args.get("card_id")
    if not sid:
        return "Failed: script_id is required"
    if not card_id:
        return "Failed: card_id is required (call list_script_npcs first to get the character card id)"
    try:
        from platform_app import knowledge as _know
        card = _know.get_character_card(user_id, int(sid), int(card_id))
        if not card:
            return f"Failed: character card #{int(card_id)} not found in script #{int(sid)}"
        return json.dumps(card, ensure_ascii=False, indent=2, default=str)
    except ValueError as exc:
        return f"Failed (permission): {exc}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


# ── global 级 ───────────────────────────────────────────


def _t_list_available_tools(args: dict) -> str:
    """元工具: LLM 自查当前工具表。"""
    origin = (args.get("origin") or "").strip()
    reg = get_registry()
    if origin:
        tools = reg.list_for_origin(origin)
    else:
        tools = reg.list_all()
    # SEC(I-1): 不向 LLM 暴露 origins / destructive 元数据 —— 这是攻击面地图(便于设计注入链)。
    # 仅返回 name/description/scope 供自发现;破坏性工具本就被 dispatcher 从 llm_chat 硬阻。
    out = [
        {
            "name": t.name,
            "description": t.description,
            "scope": t.scope,
        }
        for t in tools
    ]
    return json.dumps(out, ensure_ascii=False, indent=2)


def _t_list_modules(args: dict) -> str:
    try:
        import modules as _modules
        cat = _modules.list_modules() if hasattr(_modules, "list_modules") else []
        return json.dumps(cat, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_list_available_models(args: dict) -> str:
    try:
        from model_registry import load_model_catalog
        cat = load_model_catalog() or {}
        # 只暴露简略信息,避免 prompt 爆炸
        apis = cat.get("apis") or []
        return json.dumps(
            [{"id": a.get("id"), "kind": a.get("kind"),
              "models": [m.get("id") for m in a.get("models") or []][:8]}
             for a in apis[:12]],
            ensure_ascii=False, indent=2,
        )
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


# ── 注册 ─────────────────────────────────────────────────


def register_query_tools() -> None:
    registry = get_registry()
    save_specs = [
        ("get_game_state",
         "Return a compact snapshot of the current save state: an overview of turn/player/world/relationships/memory. "
         "fields is optional; only the given top-level keys are returned.",
         {"type": "object", "properties": {
             "fields": {"type": "array", "items": {"type": "string"}}}},
         _t_get_game_state),
        ("query_memory",
         "Search memory.items filtered by kind / characters / time_label.",
         {"type": "object", "properties": {
             "kind": {"type": "string",
                      "enum": ["canon_fact", "runtime_fact", "hypothesis", "user_constraint"]},
             "characters": {"type": "array", "items": {"type": "string"}},
             "time_label": {"type": "string"},
             "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
         }},
         _t_query_memory),
        ("get_user_variables",
         "Return the current key/value pairs of worldline.user_variables.",
         {"type": "object", "properties": {}},
         _t_get_user_variables),
        ("get_current_scene",
         "Return a snapshot of the current scene/encounter/active_entities.",
         {"type": "object", "properties": {}},
         _t_get_current_scene),
        ("get_known_events",
         "Return the most recent world.known_events.",
         {"type": "object", "properties": {"limit": {"type": "integer"}}},
         _t_get_known_events),
        ("list_relationships",
         "Return the relationships dict.",
         {"type": "object", "properties": {}},
         _t_list_relationships),
        ("get_pending_questions",
         "Return the current pending_questions.",
         {"type": "object", "properties": {}},
         _t_get_pending_questions),
        ("get_pending_writes",
         "Return the current pending_writes (state writes awaiting approval).",
         {"type": "object", "properties": {}},
         _t_get_pending_writes),
        ("recent_audit_log",
         "Return the recent audit_log, optionally filtered by kind.",
         {"type": "object", "properties": {
             "kind": {"type": "string"},
             "limit": {"type": "integer", "default": 10},
         }},
         _t_recent_audit_log),
    ]
    for name, desc, schema, exec_ in save_specs:
        if not registry.has(name):
            registry.register(ToolSpec(
                name=name, description=desc, input_schema=schema,
                executor=exec_, scope="save", origins=_READ_ANY_ORIGIN,
            ))

    user_specs = [
        ("list_my_personas", "List the current user's personas.",
         {"type": "object", "properties": {}}, _t_list_my_personas),
        ("list_my_character_cards", "List the current user's character cards.",
         {"type": "object", "properties": {}}, _t_list_my_character_cards),
        ("get_my_usage", "Return LLM token consumption for the last N days.",
         {"type": "object", "properties": {"days": {"type": "integer", "default": 30}}},
         _t_get_my_usage),
        ("list_scripts", "List the scripts visible to the current user.",
         {"type": "object", "properties": {}}, _t_list_scripts),
    ]
    for name, desc, schema, exec_ in user_specs:  # type: ignore[assignment]
        if not registry.has(name):
            registry.register(ToolSpec(
                name=name, description=desc, input_schema=schema,
                executor=exec_, scope="user", origins=_READ_ANY_ORIGIN,
            ))

    script_specs = [
        ("get_script_chapters",
         "List a script's table of contents. Without script_id, it is derived from the save.",
         {"type": "object", "properties": {"script_id": {"type": "integer"}}},
         _t_get_script_chapters),
        ("list_script_npcs",
         "List the NPC character cards that come with a script (compact list: id/name/identity/importance). For the full persona use get_script_character_card.",
         {"type": "object", "properties": {"script_id": {"type": "integer"}}},
         _t_list_script_npcs),
        ("get_script_character_card",
         "Read the full persona of one NPC character card in a script (background / appearance / personality / tone / sample dialogue, etc.). Get card_id with list_script_npcs first.",
         {"type": "object", "properties": {
             "script_id": {"type": "integer"},
             "card_id": {"type": "integer"},
         }, "required": ["card_id"]},
         _t_get_script_character_card),
    ]
    for name, desc, schema, exec_ in script_specs:  # type: ignore[assignment]
        if not registry.has(name):
            registry.register(ToolSpec(
                name=name, description=desc, input_schema=schema,
                executor=exec_, scope="script", origins=_READ_ANY_ORIGIN,
            ))

    global_specs = [
        ("list_available_tools",
         "Meta tool: list all currently registered tools. Can be filtered by origin (returns the subset visible to the LLM).",
         {"type": "object", "properties": {"origin": {"type": "string"}}},
         _t_list_available_tools),
        ("list_modules",
         "List the catalog of all 5E modules.",
         {"type": "object", "properties": {}},
         _t_list_modules),
        ("list_available_models",
         "List the currently available LLM API + model configurations.",
         {"type": "object", "properties": {}},
         _t_list_available_models),
    ]
    for name, desc, schema, exec_ in global_specs:  # type: ignore[assignment]
        if not registry.has(name):
            registry.register(ToolSpec(
                name=name, description=desc, input_schema=schema,
                executor=exec_, scope="global", origins=_READ_ANY_ORIGIN,
            ))


__all__ = ["register_query_tools"]
