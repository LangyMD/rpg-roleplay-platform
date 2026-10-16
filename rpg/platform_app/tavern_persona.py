"""酒馆「我的角色」切换的单一写穿层(UI bind 端点与 LLM 工具共用)。

双源病根修(用户实锤「切换不了+UI 不生效」,2026-07-08):
- GM 的玩家人设注入读 state.data['player'](context_providers/tavern.py);
- 旧 UI bind 只写 game_saves.tavern_persona_card_id(FK 列),/api/state 只刷面板视图
  tavern.persona → 面板变了,GM 继续演旧人设(半切换);
- LLM 工具面只有手写字段的 set_tavern_persona,没有「按卡切换」→ GM 只能编叙事(零切换)。

此处一次写全三层:FK 列 + game_saves.state_snapshot(player 字段+tavern.persona_card_id)
+ runtime_checkouts.state_snapshot 同款合并(工作树=回合真相源)并重算 snapshot_hash
(跨 worker 缓存失效,防「删了又回来」家族病 v1.28.3)。
调用方若持有内存 state(活跃档/工具路径)另行同步内存并 persist——见 routes/tavern.py 与
tools_dsl/command_tools_tavern.py 的调用点。
"""
from __future__ import annotations

from typing import Any


def persona_card_to_player_fields(card: dict[str, Any]) -> dict[str, str]:
    """卡→state.data['player'] 的投影(与 workspace.create_tavern_save 的
    _persona_to_fields 同口径:四字段,缺省空串;role 兜底 identity)。纯函数。"""
    return {
        "name": str(card.get("name") or "You"),
        "role": str(card.get("role") or card.get("identity") or ""),
        "background": str(card.get("background") or ""),
        "appearance": str(card.get("appearance") or ""),
    }


def apply_persona_card_to_chat(db, user_id: int, chat_id: int,
                               card: dict[str, Any], role: str = "persona") -> dict[str, Any]:
    """把一张(已鉴权属于 user_id 的)角色卡应用为 chat_id 的:
      role="persona"  → 玩家人设(GM 读 state.data['player']);
      role="character"→ AI 角色(GM 读 state.data['tavern']['character'])。
    写穿三层(FK 列 + game_saves 快照 + 工作树快照 + snapshot_hash 失效),返回投影字段。

    双源病根修同款(persona 已修、character 曾漏网):两个 role 的 GM 注入都读 state 而非 FK 列,
    只写 FK 列会让面板变了 GM 不变(半切换,重开存档才恢复)。字段读取以 activation.py
    _refresh_tavern_cards_from_library 的 (fk_col, key)+card_to_dto 为权威,不自创字段集。
    """
    cid = int(card["id"])
    if role == "character":
        # character:GM/面板都读 state.data['tavern']['character'](完整卡 DTO)。
        # 与 _refresh_tavern_cards_from_library 同口径:card_to_dto 深合并进 tavern.character。
        from platform_app.api._card_dto import card_to_dto
        fields = dict(card_to_dto(card))
        db.execute(
            "update game_saves set tavern_character_card_id = %s, updated_at = now() "
            "where id = %s and user_id = %s and save_kind = 'tavern'",
            (cid, int(chat_id), int(user_id)),
        )
        # tavern.character 字段合并 + tavern.character_card_id 对齐(jsonb || 保留其余运行时键)。
        _merge = (
            "coalesce({col}, '{{}}'::jsonb) "
            "|| jsonb_build_object('tavern', coalesce({col}->'tavern', '{{}}'::jsonb) "
            "   || jsonb_build_object('character', coalesce({col}->'tavern'->'character', '{{}}'::jsonb) || %s::jsonb) "
            "   || jsonb_build_object('character_card_id', %s::bigint))"
        )
    else:
        fields = persona_card_to_player_fields(card)
        db.execute(
            "update game_saves set tavern_persona_card_id = %s, updated_at = now() "
            "where id = %s and user_id = %s and save_kind = 'tavern'",
            (cid, int(chat_id), int(user_id)),
        )
        # player 字段合并 + tavern.persona_card_id 对齐(jsonb || 保留快照里其余运行时键)。
        _merge = (
            "coalesce({col}, '{{}}'::jsonb) "
            "|| jsonb_build_object('player', coalesce({col}->'player', '{{}}'::jsonb) || %s::jsonb) "
            "|| jsonb_build_object('tavern', coalesce({col}->'tavern', '{{}}'::jsonb) "
            "   || jsonb_build_object('persona_card_id', %s::bigint))"
        )
    import json as _json
    fj = _json.dumps(fields, ensure_ascii=False)
    db.execute(
        "update game_saves set state_snapshot = " + _merge.format(col="state_snapshot")
        + ", updated_at = now() where id = %s and user_id = %s and save_kind = 'tavern'",
        (fj, cid, int(chat_id), int(user_id)),
    )
    # 工作树(回合真相源)同款合并;snapshot_hash 重算=其他 worker 的内存缓存自检失效重载。
    db.execute(
        "update runtime_checkouts set state_snapshot = " + _merge.format(col="state_snapshot")
        + ", snapshot_hash = md5(( " + _merge.format(col="state_snapshot") + " )::text)"
        + ", updated_at = now() where user_id = %s and save_id = %s",
        (fj, cid, fj, cid, int(user_id), int(chat_id)),
    )
    if hasattr(db, "commit"):
        db.commit()
    return fields
