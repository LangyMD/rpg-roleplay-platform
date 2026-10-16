"""
command_tools_persona.py — persona / character_card 工具 (拆自 command_tools_misc.py)

包含:
  create_persona            user mutate
  delete_persona            user destructive
  create_character_card     user mutate
  delete_character_card     user destructive
  generate_character_card_draft   user (console_assistant + api_direct)
  refine_character_card_draft     user (console_assistant + api_direct)
"""
from __future__ import annotations

import json

from tools_dsl._arg_guards import require_int_arg
from tools_dsl.command_dispatcher import ToolSpec, get_registry

# 角色卡/persona「创建·克隆」类(非破坏)tool 的 origin。
# 历史(task 87)排除 llm_chat,把这些工具圈在侧栏控制台助手里;但用户已退役控制台助手,
# 酒馆/游戏聊天 agent 即唯一 agent 面,需要完整接口权限 → 放开 llm_chat(与
# set_tavern_character / worldbook_add 同模式:llm_chat ∈ origins + destructive=False)。
# 注意:dispatcher 不按 permission mode 拦 tool 调用(只拦 GM 的 JSON-op 字段写),故与现有
# llm_chat 写工具行为一致;**破坏性删除仍走 _USER_DEST**(destructive=True 被 dispatcher
# 硬拦 llm_chat,只能 UI 确认,防剧情 agent 误删用户卡)。
_USER_MUTATE = frozenset({"ui_button", "api_direct", "console_assistant", "llm_chat"})
_USER_DEST = frozenset({"ui_button", "api_direct", "console_assistant"})
_CREATIVE_ORIGINS = frozenset({"console_assistant", "api_direct"})


def _t_create_persona(user_id: int, args: dict) -> str:
    name = (args.get("name") or "").strip()
    summary = (args.get("summary") or "").strip()
    if not name:
        return "Failed: name is empty"
    payload = {
        "name": name,
        "personality": summary,
        "role": (args.get("role") or "").strip(),
        "background": (args.get("background") or "").strip(),
        "appearance": (args.get("appearance") or "").strip(),
        "tags": args.get("tags") or [],
    }
    try:
        from platform_app.user_cards import upsert_persona
        row = upsert_persona(user_id, payload)
        return f"Persona created: id={row.get('id')} name={name} slug={row.get('slug')}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_delete_persona(user_id: int, args: dict) -> str:
    pid = args.get("persona_id")
    _chk = require_int_arg(pid, "persona_id")
    if isinstance(_chk, str):
        return _chk
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            row = db.execute(
                "delete from character_cards where id = %s and user_id = %s and card_type = 'persona' returning id",
                (int(pid), user_id),
            ).fetchone()
            if not row:
                return f"Failed: persona {pid} does not belong to the current user or does not exist"
        return f"Persona {pid} deleted"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_create_character_card(user_id: int, args: dict) -> str:
    name = (args.get("name") or "").strip()
    summary = (args.get("summary") or "").strip()
    if not name:
        return "Failed: name is empty"
    payload = {
        "name": name,
        "personality": summary,
        "identity": (args.get("identity") or "").strip(),
        "appearance": (args.get("appearance") or "").strip(),
        "speech_style": (args.get("speech_style") or "").strip(),
        "current_status": (args.get("current_status") or "").strip(),
        "secrets": (args.get("secrets") or "").strip(),
        "aliases": args.get("aliases") or [],
        "sample_dialogue": args.get("sample_dialogue") or [],
        "tags": args.get("tags") or [],
    }
    try:
        from platform_app.user_cards import upsert_user_card
        row = upsert_user_card(user_id, payload)
        return f"Character card created: id={row.get('id')} name={name} slug={row.get('slug')}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_delete_character_card(user_id: int, args: dict) -> str:
    cid = args.get("card_id")
    _chk = require_int_arg(cid, "card_id")
    if isinstance(_chk, str):
        return _chk
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            row = db.execute(
                "delete from character_cards where id = %s and user_id = %s and card_type = 'pc' returning id",
                (int(cid), user_id),
            ).fetchone()
            if not row:
                return f"Failed: card {cid} does not belong to the current user or does not exist"
        return f"Character card {cid} deleted"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_clone_npc_to_user_card(user_id: int, args: dict) -> str:
    """把(自有或已订阅共享的)剧本里的 NPC 角色卡完整复制成当前用户的角色卡。

    **独立副本,非指针**:full_name/背景/外貌/性格/语气/范例对白/头像全带上;站内头像
    URL 直接复用(物理不重存,同源鉴权链接放行)。镜像前端 promoteNpcToUserCard。
    鉴权:读 NPC 走 knowledge.get_character_card(owner 或订阅者均可——共享剧本无编辑权限
    也能读);写进当前用户自己的角色卡空间(upsert_user_card)。因此对「订阅了别人公开
    剧本、想把里面 NPC 收藏成自己可编辑的角色卡」这一流程是顺的。
    """
    sid = args.get("script_id")
    card_id = args.get("card_id")
    if not sid:
        return "Failed: script_id is required"
    if not card_id:
        return "Failed: card_id is required (get the NPC character card id with list_script_npcs first)"
    try:
        from platform_app import knowledge as _know
        from platform_app.user_cards import upsert_user_card
        npc = _know.get_character_card(user_id, int(sid), int(card_id))  # owner-or-subscriber 鉴权
        if not npc:
            return f"Failed: NPC character card #{int(card_id)} not found in script #{int(sid)}"
        name = (npc.get("name") or npc.get("full_name") or "").strip() or "Unnamed character"
        tags = list(npc.get("tags") or [])
        if "源自 NPC" not in tags and "From NPC" not in tags:
            tags.append("From NPC")
        payload = {
            "name": name,
            "full_name": npc.get("full_name") or "",
            "aliases": npc.get("aliases") or [],
            "identity": npc.get("identity") or "",
            "background": npc.get("background") or "",
            "appearance": npc.get("appearance") or "",
            "personality": npc.get("personality") or "",
            "speech_style": npc.get("speech_style") or "",
            "current_status": npc.get("current_status") or "",
            "secrets": npc.get("secrets") or "",
            "sample_dialogue": npc.get("sample_dialogue") or [],
            # 复制头像 URL(站内资产物理不重存);转换=完整复制一份独立用户卡,非指针。
            "avatar_path": npc.get("avatar_path") or "",
            "tags": tags,
            "metadata": {
                "source": "npc_promote",
                "source_script_id": int(sid),
                "source_npc_id": int(card_id),
            },
            "enabled": True,
        }
        row = upsert_user_card(user_id, payload)
        return (f"Cloned into a user character card: id={row.get('id')} name={name} "
                f"slug={row.get('slug')} (an independent copy; edit it or change its avatar on the 'Character cards' page)")
    except ValueError as exc:
        return f"Failed (permission): {exc}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def register_persona_tools() -> None:
    registry = get_registry()

    user_specs = [
        # task 87 Phase 7 安全审查 — user 级 mutate (跨 save 影响) 全部禁 LLM:
        ("create_persona", "Create a user persona (a player identity template). summary is written to the personality field.",
         {"type": "object",
          "properties": {
              "name": {"type": "string"},
              "summary": {"type": "string", "description": "Short personality summary, written to the personality field"},
              "role": {"type": "string"},
              "background": {"type": "string"},
              "appearance": {"type": "string"},
              "tags": {"type": "array", "items": {"type": "string"}},
          },
          "required": []},  # handler 自行校验并返回"name 为空"友好消息
         _t_create_persona, _USER_MUTATE, False),  # 跨 save 持久资源;控制台助手退役后放开酒馆/游戏 agent
        ("delete_persona", "Permanently delete a persona",
         {"type": "object", "properties": {"persona_id": {"type": "integer"}}, "required": ["persona_id"]},
         _t_delete_persona, _USER_DEST, True),
        ("create_character_card",
         "Create a reusable character card (shared across saves). summary is written to the personality field.\n"
         "This is **not** for renaming the player inside the story (that is set_player_name, which the assistant does not handle).",
         {"type": "object",
          "properties": {
              "name": {"type": "string", "description": "Character name (e.g. Stella / Ari)"},
              "summary": {"type": "string", "description": "Short personality summary (e.g. cheerful and energetic / calm and scheming)"},
              "identity": {"type": "string", "description": "One-sentence identity/background (e.g. a high-school girl transmigrator)"},
              "appearance": {"type": "string", "description": "Appearance"},
              "speech_style": {"type": "string", "description": "Way of speaking"},
              "current_status": {"type": "string", "description": "Current status"},
              "secrets": {"type": "string", "description": "Undisclosed secrets"},
              "aliases": {"type": "array", "items": {"type": "string"}},
              "sample_dialogue": {"type": "array", "items": {"type": "string"}},
              "tags": {"type": "array", "items": {"type": "string"}},
          },
          # handler 自行校验 name 为空,返回"name 为空"友好消息
          "required": []},
         _t_create_character_card, _USER_MUTATE, False),  # 跨 save;控制台助手退役后放开酒馆/游戏 agent
        ("delete_character_card", "Permanently delete a character card",
         {"type": "object", "properties": {"card_id": {"type": "integer"}}, "required": ["card_id"]},
         _t_delete_character_card, _USER_DEST, True),
        ("clone_npc_to_user_card",
         "Copy an NPC character card from a script (owned, or shared and subscribed) into a character card of the current user (an independent copy "
         "including full name / background / appearance / personality / tone / sample dialogue / avatar). Shared scripts can be cloned even without edit permission. "
         "First get script_id with list_scripts and card_id with list_script_npcs.",
         {"type": "object",
          "properties": {
              "script_id": {"type": "integer", "description": "Id of the script the NPC belongs to"},
              "card_id": {"type": "integer", "description": "NPC character card id (from list_script_npcs)"},
          },
          "required": ["script_id", "card_id"]},
         _t_clone_npc_to_user_card, _USER_MUTATE, False),  # 与 create_character_card 同策略;控制台助手退役后放开酒馆/游戏 agent
    ]
    for name, desc, schema, exec_, origins, destructive in user_specs:
        if not registry.has(name):
            registry.register(ToolSpec(
                name=name, description=desc, input_schema=schema,
                executor=exec_, scope="user", origins=origins, destructive=destructive,
            ))

    # ────────────────────────────────────────────────────────────
    # task 49: 创意工具 — generate/refine_character_card_draft
    # 仅 console_assistant + api_direct 可调; LLM 自由叙事 (llm_chat) 不允许
    # 自创角色卡 (该走 gm_provisional active_entity 路径)。
    # ────────────────────────────────────────────────────────────

    def _t_generate_card_draft(user_id: int, args: dict) -> str:
        try:
            import character_card_generator as ccg
            result = ccg.generate_character_card_draft(
                brief=str(args.get("brief") or ""),
                user_id=user_id,
                script_id=args.get("script_id"),
                kind=str(args.get("kind") or "user"),
                phase=args.get("phase"),
                timeout_sec=int(args.get("timeout_sec") or 30),
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            return f"Failed: {type(exc).__name__}: {exc}"

    def _t_refine_card_draft(user_id: int, args: dict) -> str:
        try:
            import character_card_generator as ccg
            prev = args.get("previous_draft")
            if not isinstance(prev, dict):
                return "Failed: previous_draft must be an object"
            result = ccg.refine_character_card_draft(
                previous_draft=prev,
                feedback=str(args.get("feedback") or ""),
                user_id=user_id,
                script_id=args.get("script_id"),
                timeout_sec=int(args.get("timeout_sec") or 30),
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            return f"Failed: {type(exc).__name__}: {exc}"

    creative_specs = [
        ("generate_character_card_draft",
         "Expand a short persona description into a character card candidate that fits the current script's conventions (does not write to the DB; returns only draft+validations)",
         {"type": "object",
          "properties": {
              "brief": {"type": "string", "description": "The user's short description, e.g. '20-year-old female mage, exiled noble'"},
              "script_id": {"type": "integer", "description": "Target script id (for duplicate checks / phase / style)"},
              "kind": {"type": "string", "enum": ["user", "script"], "default": "user"},
              "phase": {"type": "string", "description": "Target phase label; inferred from the DB when empty"},
              "timeout_sec": {"type": "integer", "default": 30},
          },
          "required": ["brief"]},
         _t_generate_card_draft),
        ("refine_character_card_draft",
         "Regenerate the card candidate from previous_draft + user feedback (goes through the same 5-layer validator)",
         {"type": "object",
          "properties": {
              "previous_draft": {"type": "object", "description": "The previous draft (the draft field returned by generate)"},
              "feedback": {"type": "string", "description": "User feedback, e.g. 'make the personality more introverted'"},
              "script_id": {"type": "integer"},
              "timeout_sec": {"type": "integer", "default": 30},
          },
          "required": ["previous_draft", "feedback"]},
         _t_refine_card_draft),
    ]
    for name, desc, schema, exec_ in creative_specs:
        if not registry.has(name):
            registry.register(ToolSpec(
                name=name, description=desc, input_schema=schema,
                executor=exec_, scope="user", origins=_CREATIVE_ORIGINS, destructive=False,
            ))


__all__ = ["register_persona_tools"]
