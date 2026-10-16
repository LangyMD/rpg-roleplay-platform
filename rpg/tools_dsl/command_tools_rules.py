"""
command_tools_rules.py — task 87 Phase 2.3: 5E 模组规则工具表。

把 /api/rules/* 系列端点改造成 LLM 可调工具:
  · module_load          模组加载到当前 save
  · module_launch        模组启动 (高层入口,会初始化角色卡 + 入场)
  · module_enter_room    切换房间
  · combat_start         开打 (按 encounter_id)
  · combat_next_turn     推进回合
  · combat_player_attack 玩家攻击
  · combat_enemy_attack  敌方回合攻击
  · skill_check          技能检定
  · saving_throw         豁免检定
  · short_rest           短休
  · grant_item           授予物品到背包(canonical inventory)
  · pickup_loot          拾取当前房间 loot 进背包
  · consume_item         消耗物品

所有工具 save 级,执行规则函数后会:
  1. 把结果写回 state.permissions.audit_log 的 rule_receipt
  2. 清掉已过期的 pending_questions
  3. 触发 state.save() 持久化
这些与原 HTTP 端点一致。
"""
from __future__ import annotations

from typing import Any

from rules.seed_policy import coerce_external_seed
from tools_dsl.command_dispatcher import ToolSpec, get_registry

# 5E 模组工具默认 origin: UI / API / LLM 都可调,但战斗具体动作禁止 llm_chat
# (LLM 必须明确通过 /set 或 UI 显式按按钮才能动 HP/initiative)。
# task 62: 移除 console_assistant — 模组装载/战斗都是 save 内行为,
# 控制台助手是跨 save 资源管理,不该越界触发战斗 / move 房间。
# 用户想玩模组就去 Game Console 走 GM。
_RULES_FULL_ORIGINS = frozenset({"ui_button", "api_direct", "llm_set", "llm_chat_json_op"})
_RULES_LLM_CHAT_ALLOWED_ORIGINS = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat", "llm_chat_json_op",
})


# ── 工具执行器 ───────────────────────────────────────────


def _t_module_load(state: Any, args: dict) -> str:
    mod_id = (args.get("module_id") or "").strip()
    if not mod_id:
        return "Failed: module_id is empty"
    overrides = args.get("character_overrides") or None
    try:
        from rules_bridge import start_module
        result = start_module(state, mod_id, character_overrides=overrides)
        if not result.get("ok"):
            return f"Failed: {result.get('error') or 'unknown error'}"
        return f"Module {mod_id} loaded (starting room: {result.get('start_location_id', '?')})"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_module_enter_room(state: Any, args: dict) -> str:
    loc = (args.get("location_id") or "").strip()
    if not loc:
        return "Failed: location_id is empty"
    try:
        from rules_bridge import enter_room
        res = enter_room(state, loc)
        if not res.get("ok"):
            return f"Failed: {res.get('error') or 'unknown error'}"
        return f"Entered room {loc} ✓"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_combat_start(state: Any, args: dict) -> str:
    enc_id = (args.get("encounter_id") or "").strip()
    if not enc_id:
        return "Failed: encounter_id is empty"
    seed = args.get("seed")
    seed_int = coerce_external_seed(seed)  # 外部/LLM 提供的 seed 默认忽略(防操纵掷骰)
    try:
        from rules_bridge import start_encounter_by_id
        res = start_encounter_by_id(state, enc_id, seed=seed_int)
        if not res.get("ok"):
            return f"Failed: {res.get('error') or 'unknown error'}"
        return f"Combat started: {enc_id} (initiative order is ready)"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_combat_next_turn(state: Any, args: dict) -> str:
    try:
        from rules_bridge import advance_turn
        res = advance_turn(state)
        if not res.get("ok"):
            return f"Failed: {res.get('error') or 'unknown error'}"
        if res.get("resolved"):
            # next_turn 兜底强制结束(>50 回合僵局):别再误报"推进到下一回合"
            return res.get("message") or f"Combat over: {res.get('outcome','stalemate')}."
        enc = res.get("encounter") or {}
        return f"Advanced to the next turn (round={enc.get('round','?')}, turn_index={enc.get('turn_index','?')})"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_combat_player_attack(state: Any, args: dict) -> str:
    target = (args.get("target_id") or "").strip()
    weapon = (args.get("weapon_id") or "shortsword").strip()
    seed = args.get("seed")
    seed_int = coerce_external_seed(seed)  # 外部/LLM 提供的 seed 默认忽略(防操纵掷骰)
    if not target:
        return "Failed: target_id is empty"
    try:
        from rules_bridge import player_attack
        res = player_attack(state, target_id=target, weapon_id=weapon, seed=seed_int)
        if not res.get("ok"):
            return f"Failed: {res.get('error') or 'unknown error'}"
        r = res.get("result") or {}
        return f"Attack {target} with {weapon}: {r.get('summary') or r}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_combat_enemy_attack(state: Any, args: dict) -> str:
    attacker = (args.get("attacker_id") or "").strip()
    target = (args.get("target_id") or "player").strip()
    seed = args.get("seed")
    seed_int = coerce_external_seed(seed)  # 外部/LLM 提供的 seed 默认忽略(防操纵掷骰)
    if not attacker:
        return "Failed: attacker_id is empty"
    try:
        from rules_bridge import enemy_attack
        res = enemy_attack(state, attacker_id=attacker, target_id=target, seed=seed_int)
        if not res.get("ok"):
            return f"Failed: {res.get('error') or 'unknown error'}"
        return f"Enemy {attacker} -> {target}: {(res.get('result') or {}).get('summary') or 'done'}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_skill_check(state: Any, args: dict) -> str:
    skill = (args.get("skill") or "").strip()
    dc = args.get("dc")
    if not skill or not isinstance(dc, (int, float)):
        return "Failed: skill / dc missing"
    seed = args.get("seed")
    seed_int = coerce_external_seed(seed)  # 外部/LLM 提供的 seed 默认忽略(防操纵掷骰)
    try:
        from rules_bridge import perform_skill_check
        res = perform_skill_check(state, skill=skill, dc=int(dc), seed=seed_int)
        return f"{skill} check DC={dc}: {res.get('summary') or res}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_saving_throw(state: Any, args: dict) -> str:
    save = (args.get("save") or "").strip()
    dc = args.get("dc")
    if not save or not isinstance(dc, (int, float)):
        return "Failed: save / dc missing"
    seed = args.get("seed")
    seed_int = coerce_external_seed(seed)  # 外部/LLM 提供的 seed 默认忽略(防操纵掷骰)
    try:
        from rules_bridge import perform_saving_throw
        res = perform_saving_throw(state, ability=save, dc=int(dc), seed=seed_int)
        return f"{save} saving throw DC={dc}: {res.get('summary') or res}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_short_rest(state: Any, args: dict) -> str:
    seed = args.get("seed")
    seed_int = coerce_external_seed(seed)  # 外部/LLM 提供的 seed 默认忽略(防操纵掷骰)
    try:
        from rules_bridge import short_rest
        res = short_rest(state, seed=seed_int)
        return f"Short rest complete: {res.get('summary') or 'recovered'}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_grant_item(state: Any, args: dict) -> str:
    item_id = (args.get("item_id") or "").strip()
    name = args.get("name") or None
    kind = (args.get("kind") or "misc").strip() or "misc"
    qty = args.get("qty") or 1
    if not item_id:
        return "Failed: item_id is empty"
    try:
        from rules_bridge import grant_item_action
        res = grant_item_action(state, item_id=item_id, name=name, qty=int(qty), kind=kind,
                                reason=str(args.get("reason") or ""))
        if not res.get("ok"):
            return f"Failed: {res.get('error') or 'unknown error'}"
        facts = (res.get("result") or {}).get("gm_facts") or []
        return facts[0] if facts else f"Granted {item_id} x{qty} ✓"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_pickup_loot(state: Any, args: dict) -> str:
    item_id = (args.get("item_id") or "").strip()
    location_id = (args.get("location_id") or "").strip() or None
    if not item_id:
        return "Failed: item_id is empty"
    try:
        from rules_bridge import pickup_loot_action
        res = pickup_loot_action(state, item_id=item_id, location_id=location_id,
                                 reason=str(args.get("reason") or ""))
        if not res.get("ok"):
            return f"Failed: {res.get('error') or 'unknown error'}"
        facts = (res.get("result") or {}).get("gm_facts") or []
        return facts[0] if facts else f"Picked up {item_id} ✓"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_consume_item(state: Any, args: dict) -> str:
    item_id = (args.get("item_id") or "").strip()
    qty = args.get("qty") or 1
    if not item_id:
        return "Failed: item_id is empty"
    try:
        from rules_bridge import consume_item_action
        res = consume_item_action(state, item_id=item_id, qty=int(qty))
        if not res.get("ok"):
            return f"Failed: {res.get('error') or 'unknown error'}"
        return f"Consumed {item_id} x{qty}: {res.get('summary') or 'done'}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


# ── 注册 ─────────────────────────────────────────────────


def register_rules_tools() -> None:
    registry = get_registry()
    specs: list[ToolSpec] = [
        ToolSpec(
            name="module_load",
            description="Load the given 5E module into the current save (initializes the character sheet + starting room).",
            input_schema={
                "type": "object",
                "properties": {
                    "module_id": {"type": "string"},
                    "character_overrides": {"type": "object",
                                             "description": "Optional: override the default character sheet attributes"},
                },
                "required": [],  # handler 自行校验并返回"module_id 为空"友好消息
            },
            executor=_t_module_load,
            scope="save",
            origins=_RULES_FULL_ORIGINS,
            destructive=True,  # 改写整张角色卡,LLM 不直接调
        ),
        ToolSpec(
            name="module_enter_room",
            description="Move the player to the room with the given location_id. location_id must be a room that exists in the current module.",
            input_schema={
                "type": "object",
                "properties": {"location_id": {"type": "string"}},
                "required": ["location_id"],
            },
            executor=_t_module_enter_room,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
        ToolSpec(
            name="combat_start",
            description="Start combat for the given encounter_id and compute the initiative order.",
            input_schema={
                "type": "object",
                "properties": {
                    "encounter_id": {"type": "string"},
                    "seed": {"type": "integer", "description": "Optional RNG seed, for testing"},
                },
                "required": ["encounter_id"],
            },
            executor=_t_combat_start,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
        ToolSpec(
            name="combat_next_turn",
            description="Advance combat to the next turn (moves one step along the initiative order).",
            input_schema={"type": "object", "properties": {}, "required": []},
            executor=_t_combat_next_turn,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
        ToolSpec(
            name="combat_player_attack",
            description="The player attacks the given target with the given weapon. HP/AC and other numbers are decided by the RulesEngine.",
            input_schema={
                "type": "object",
                "properties": {
                    "target_id": {"type": "string"},
                    "weapon_id": {"type": "string", "default": "shortsword"},
                    "seed": {"type": "integer"},
                },
                "required": [],  # handler 自行校验并返回"target_id 为空"友好消息
            },
            executor=_t_combat_player_attack,
            scope="save",
            origins=_RULES_FULL_ORIGINS,  # llm_chat 不直接调战斗,要走 chat 路径
        ),
        ToolSpec(
            name="combat_enemy_attack",
            description="Enemy turn - the given enemy attacks the player (used to drive the combat demo).",
            input_schema={
                "type": "object",
                "properties": {
                    "attacker_id": {"type": "string"},
                    "target_id": {"type": "string", "default": "player"},
                    "seed": {"type": "integer"},
                },
                "required": ["attacker_id"],
            },
            executor=_t_combat_enemy_attack,
            scope="save",
            origins=_RULES_FULL_ORIGINS,
        ),
        ToolSpec(
            name="skill_check",
            description="Skill check (perform_skill_check).",
            input_schema={
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "dc": {"type": "integer"},
                    "seed": {"type": "integer"},
                },
                "required": [],  # handler 自行校验并返回"dc 缺失"友好消息
            },
            executor=_t_skill_check,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
        ToolSpec(
            name="saving_throw",
            description="Saving throw (perform_saving_throw).",
            input_schema={
                "type": "object",
                "properties": {
                    "save": {"type": "string"},
                    "dc": {"type": "integer"},
                    "seed": {"type": "integer"},
                },
                "required": ["save", "dc"],
            },
            executor=_t_saving_throw,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
        ToolSpec(
            name="short_rest",
            description="Short rest: recover HP / resources (per 5E rules).",
            input_schema={
                "type": "object",
                "properties": {"seed": {"type": "integer"}},
                "required": [],
            },
            executor=_t_short_rest,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
        ToolSpec(
            name="grant_item",
            description=(
                "Grant an item to the player's inventory (canonical inventory). When the GM narrates that the player 'obtains X', it must call this tool; "
                "do not write memory.resources directly - that is only a derived display layer, and the player cannot use anything written there. "
                "item_id is a stable English id (e.g. antidote / silver_key), name is the display name, "
                "kind ∈ {weapon,gear,consumable,key_item,artifact,misc}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "name": {"type": "string", "description": "Display name"},
                    "qty": {"type": "integer", "default": 1, "minimum": 1},
                    "kind": {"type": "string", "default": "misc"},
                    "reason": {"type": "string"},
                },
                "required": [],  # handler 自行校验并返回"item_id 为空"友好消息
            },
            executor=_t_grant_item,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
        ToolSpec(
            name="pickup_loot",
            description=(
                "Pick up a loot item from the player's current room into the inventory. item_id must be an id that really exists in the current room's loot. "
                "Only items in the room the player is in can be picked up; once picked up, that loot cannot be picked up again."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "location_id": {"type": "string", "description": "Optional: validated to equal the current room"},
                    "reason": {"type": "string"},
                },
                "required": [],  # handler 自行校验并返回"item_id 为空"友好消息
            },
            executor=_t_pickup_loot,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
        ToolSpec(
            name="consume_item",
            description="Consume an item (potion / food, etc.).",
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "qty": {"type": "integer", "default": 1, "minimum": 1},
                    "seed": {"type": "integer"},
                },
                "required": [],  # handler 自行校验并返回"item_id 为空"友好消息
            },
            executor=_t_consume_item,
            scope="save",
            origins=_RULES_LLM_CHAT_ALLOWED_ORIGINS,
        ),
    ]
    for spec in specs:
        if not registry.has(spec.name):
            registry.register(spec)


__all__ = ["register_rules_tools"]
