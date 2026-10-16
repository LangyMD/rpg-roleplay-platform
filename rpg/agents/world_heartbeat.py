"""agents/world_heartbeat.py — 世界心跳 v0(活世界·柱子1)。

设计文档: docs/design/world_heartbeat_v0.md

目标: 世界在玩家不注视的地方也在动 —— 每隔几回合确定性地产生 1-2 条「世界侧
小事」(村庄级/配角级/环境级),留存在 state.data["background_events"],由
context provider(rpg/context_providers/world_pulse.py)择机以传闻/路人交谈的
方式浮出。

与后果账本(柱子2, state/consequence_ledger.py)的分工: 后果=玩家种的因(有
明确到期), 心跳=世界自己的事(无因果绑定)。两者互不读写。

原则(与柱子2同一套纪律):
- 调度(should_tick)/去重/防剧透/上限/剪除 = 确定性代码; 只有事件文案由 LLM 写。
- flag `world_heartbeat` 默认关。
- 零新持久化机制: 直接改 state.data,由本回合 Phase 5 统一持久化。
- 全程 try/except: 任何失败静默跳过,绝不破回合(见 run_heartbeat_tick)。

状态结构 (state.data["background_events"]: list[dict]):
    {
      "id": "bg_a1b2c3",
      "text": "村东磨坊主的驴昨夜挣脱缰绳跑进了麦田,踩坏了半垄麦子",
      "created_turn": 12,
      "surfaced_turn": None,
    }

调度元信息 (state.data["heartbeat_meta"]: dict):
    {"last_tick_turn": int}
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Any

from core.logging import get_logger
from core.text import normalize_for_fp
from core.token_estimate import is_cjk_text
from state.parsers import _clean_item

log = get_logger(__name__)

# ── 常量(设计文档 §1/§2)───────────────────────────────────────────

MIN_TURN_TO_START = 4      # 前 3 回合让故事立足,不产心跳
TICK_INTERVAL_TURNS = 3    # K=3 节流
MAX_UNSURFACED_BACKLOG = 8   # 未浮出条目 >= 8 就别再产(积压保护,should_tick 用)
MAX_UNSURFACED_STORED = 12   # 未浮出条目上限,超出拒收(register 用)
SURFACED_RETENTION_TURNS = 5  # 已浮出条目保留 5 回合后确定性剪除

MAX_ITEM_CHARS = 120        # 单条事件文案最大字数(验收器拒绝口径)
MAX_ITEMS_PER_TICK = 2      # 一次 tick 最多产出条数
MAX_ITEM_CHARS_LATIN = 360  # 英文等拉丁文字的同口径上限(prompt 要求 ≤55 词)
_SECOND_PERSON_EN = re.compile(r"\b(?:you|your|yours|yourself)\b", re.I)  # 英文版「你」


# ── 指纹归一化(与 state/consequence_ledger._normalize_for_fp 同思路)──────


def _normalize_for_fp(text: str) -> str:
    """指纹归一化: 去掉全部标点/空白,只留文字数字。

    归一化规则统一到中立缝 core.text.normalize_for_fp(单一真源)。心跳模块与
    state.consequence_ledger 现共同依赖这条中立缝、而非互相 import——两个柱子
    仍互不读写,架构隔离成立(详见设计文档 §分工)。
    """
    return normalize_for_fp(text)


# ── 状态访问 helper ────────────────────────────────────────────────

def _events(state_data: dict) -> list[dict]:
    """取 / 建 state_data["background_events"] 列表引用(原地可变)。"""
    events = state_data.setdefault("background_events", [])
    if not isinstance(events, list):
        events = []
        state_data["background_events"] = events
    return events


def _meta(state_data: dict) -> dict:
    meta = state_data.setdefault("heartbeat_meta", {})
    if not isinstance(meta, dict):
        meta = {}
        state_data["heartbeat_meta"] = meta
    return meta


# ── 调度(纯函数)────────────────────────────────────────────────────

def should_tick(state_data: dict, user_id: int | None) -> bool:
    """本回合是否该产心跳。纯函数,不做任何写入。

    条件(全部满足才 True):
      1. flag `world_heartbeat` 开
      2. state.turn >= MIN_TURN_TO_START(前 3 回合让故事立足)
      3. turn - heartbeat_meta.last_tick_turn >= TICK_INTERVAL_TURNS(K=3 节流)
      4. 未浮出条目数 < MAX_UNSURFACED_BACKLOG(积压多就别再产)
    """
    try:
        from core.feature_flags import feature_enabled
        if not feature_enabled("world_heartbeat", user_id):
            return False
    except Exception:
        return False

    turn = int(state_data.get("turn", 0) or 0)
    if turn < MIN_TURN_TO_START:
        return False

    meta = state_data.get("heartbeat_meta") or {}
    last_tick_turn = int(meta.get("last_tick_turn", -(10 ** 9)) or -(10 ** 9))
    if turn - last_tick_turn < TICK_INTERVAL_TURNS:
        return False

    events = state_data.get("background_events") or []
    if not isinstance(events, list):
        events = []
    unsurfaced = sum(1 for e in events if isinstance(e, dict) and not e.get("surfaced_turn"))
    if unsurfaced >= MAX_UNSURFACED_BACKLOG:
        return False

    return True


# ── 验收器(确定性,代码不信 LLM)───────────────────────────────────────

def _validate_items(
    raw_items: Any,
    *,
    state_data: dict,
    player_name: str = "",
) -> list[str]:
    """逐条校验 LLM 产出的候选事件文案,返回通过的文本列表(去重、防剧透)。

    拒绝规则(设计文档 §2):
      - 非字符串 / 空串
      - 超过 MAX_ITEM_CHARS 字
      - 含「你」或玩家名(防止直接提到玩家本人)
      - 与现存 background_events 指纹重复(归一化后)
    全拒则返回空列表(正常,不重试)。
    """
    if not isinstance(raw_items, list):
        return []

    existing = _events(state_data) if isinstance(state_data, dict) else []
    seen_fp = {
        _normalize_for_fp(e.get("text", ""))
        for e in existing
        if isinstance(e, dict)
    }
    player_name = _clean_item(player_name or "")

    out: list[str] = []
    for raw in raw_items:
        if not isinstance(raw, str):
            continue
        text = _clean_item(raw)
        if not text:
            continue
        # MAX_ITEM_CHARS 按中文字数定;英文同样信息量字符更多,按语言换算
        if len(text) > (MAX_ITEM_CHARS if is_cjk_text(text) else MAX_ITEM_CHARS_LATIN):
            continue
        if "你" in text or _SECOND_PERSON_EN.search(text):
            continue
        if player_name and player_name in text:
            continue
        fp = _normalize_for_fp(text)
        if not fp or fp in seen_fp:
            continue
        seen_fp.add(fp)
        out.append(text)
        if len(out) >= MAX_ITEMS_PER_TICK:
            break
    return out


# ── 输入材料构造(防剧透: 只喂已揭示信息)──────────────────────────────

def _build_materials(state_data: dict, pending_anchors: list[dict] | None) -> dict:
    """收集喂给 LLM 的材料,全部是已揭示/揭示窗口内的(设计文档 §2)。

    不喂原著 RAG、不喂未到锚点的正文;可选喂 pending_anchors 的 summary(≤2 条)。
    """
    world = state_data.get("world") or {}
    player = state_data.get("player") or {}
    memory = state_data.get("memory") or {}
    relationships = state_data.get("relationships") or {}
    active_entities = state_data.get("active_entities") or []
    existing_events = _events(state_data)

    facts = memory.get("facts") or []
    if not isinstance(facts, list):
        facts = []

    entities_brief = []
    if isinstance(active_entities, list):
        for e in active_entities[:8]:
            if not isinstance(e, dict):
                continue
            entities_brief.append({
                "name": str(e.get("name", "")),
                "disposition": str(e.get("disposition", "unknown")),
            })

    recent_bg = [
        str(e.get("text", ""))
        for e in existing_events[-3:]
        if isinstance(e, dict)
    ]

    anchors_brief = []
    if pending_anchors:
        for a in pending_anchors[:2]:
            if isinstance(a, dict) and a.get("summary"):
                anchors_brief.append(str(a.get("summary", ""))[:200])

    return {
        "time": str(world.get("time", "")),
        "current_location": str(player.get("current_location", "")),
        "current_phase": str((world.get("timeline") or {}).get("current_phase", "")),
        "facts_recent": [str(f) for f in facts[-10:]],
        "relationship_names": list(relationships.keys()) if isinstance(relationships, dict) else [],
        "active_entities": entities_brief,
        "recent_background_events": recent_bg,
        "pending_anchor_hints": anchors_brief,
    }


def _build_prompts(materials: dict) -> tuple[str, str]:
    """构造心跳 tick 的 system + user prompt(设计文档 §2 prompt 要点)。"""
    system_prompt = (
        "You write the \"world pulse\" for a tabletop role-playing game. Your job is to imagine tiny "
        "events happening **around the player's current location, in corners the player is not "
        "looking at right now** (village-level, side-character-level or environmental everyday "
        "trifles), so the world feels like it runs on its own.\n"
        "Hard rules:\n"
        "1. Each item is at most 55 words;\n"
        "2. Never mention the player (no \"you\" and no player name);\n"
        "3. No major plot turns, and no death / war / disaster-level events (those belong to the main plot);\n"
        "4. Stay consistent with the known facts, places and character tone given below; do not "
        "invent important characters who have not appeared;\n"
        "5. **Geography rule**: events may only happen at the player's [current location] and its "
        "immediate surroundings. Distant places or people the player has only [heard of but not "
        "yet reached] (such as someone in another town) must [never] be written as something "
        "happening here right now, and locals cannot somehow know what happened far away today. If "
        "you really must mention a distant place, write it only as \"old news brought by a passing "
        "traveler / hearsay\", never as a live local event;\n"
        "6. Output only 1-2 items, strictly as one JSON array of strings, with no other text, "
        "explanation or markdown fences.\n"
        'Example output: ["The east-village miller\'s donkey slipped its halter last night and '
        'trampled half a row of wheat", "A fresh load of ore arrived at the town smithy"]'
    )
    user_prompt = (
        "Current world snapshot:\n"
        f"- Time: {materials.get('time') or '(unknown)'}\n"
        f"- Location: {materials.get('current_location') or '(unknown)'}\n"
        f"- Phase: {materials.get('current_phase') or '(unknown)'}\n"
        f"- Recent facts: {json.dumps(materials.get('facts_recent') or [], ensure_ascii=False)}\n"
        f"- Known relationship names: {json.dumps(materials.get('relationship_names') or [], ensure_ascii=False)}\n"
        f"- Tone of characters present: {json.dumps(materials.get('active_entities') or [], ensure_ascii=False)}\n"
        f"- World events already produced recently (avoid repeating their direction): "
        f"{json.dumps(materials.get('recent_background_events') or [], ensure_ascii=False)}\n"
        f"- What the world is brewing (directional hints, not settled facts): "
        f"{json.dumps(materials.get('pending_anchor_hints') or [], ensure_ascii=False)}\n\n"
        "Write 1-2 small things happening right now at the player's [current location and its "
        "immediate surroundings], in corners the player is not looking at, consistent with known "
        "facts and with no direct causal link to the scene in play. **Places or people known only "
        "by name, where the player has not yet been, must not be written as live local events** "
        "(geography rule). Output strictly a JSON array."
    )
    return system_prompt, user_prompt


# ── LLM 调用 + 落地(唯一带副作用的入口)───────────────────────────────

def run_heartbeat_tick(
    state: Any,
    user_id: int | None = None,
    *,
    api_id_override: str | None = None,
    model_override: str | None = None,
    pending_anchors: list[dict] | None = None,
    timeout_sec: int = 15,
) -> list[str]:
    """跑一次心跳 tick: 一次 LLM 调用产出 1-2 条世界侧事件,通过确定性验收后
    append 进 state.data["background_events"] + 更新 heartbeat_meta.last_tick_turn。

    直接改 state.data(本回合 Phase 5 统一持久化,与 extractor 同命运)。
    返回本次实际写入的事件文本列表(空列表 = 本 tick 空手而归,正常情况)。

    pending_anchors: 可选,调用方按需透传(设计文档 §2「世界正在酝酿什么」方向
    暗示,≤2 条 summary)。v0 接线点(chat_pipeline._worker_heartbeat)未额外做
    DB 查询取它,默认 None 不影响主流程 —— 只是 prompt 材料的锦上添花项。

    全程 try/except: 任何失败静默跳过(log.debug),绝不破回合。
    """
    try:
        state_data = getattr(state, "data", None)
        if not isinstance(state_data, dict):
            return []

        # 模型解析: 复用史官的解析函数,严格 BYOK,同用户级偏好。
        from agents.recorder import _resolve_recorder_api_and_model
        try:
            api_id, model = _resolve_recorder_api_and_model(user_id, api_id_override, model_override)
        except Exception as exc:
            log.info("[world_heartbeat] 模型解析失败,跳过: %s", exc)
            return []
        if not api_id or not model:
            log.info("[world_heartbeat] 无可用 api_id/model,跳过")
            return []

        materials = _build_materials(state_data, pending_anchors)
        system_prompt, user_prompt = _build_prompts(materials)

        from agents._harness import call_agent_json_guarded
        try:
            # 结构化微任务禁深思(268 实锤族)+ 空正文护栏(下方 dict 形态打捞逻辑保持不变)
            text, usage = call_agent_json_guarded(
                api_id=api_id,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                user_id=user_id,
                tool_schema=None,  # 心跳只要简单 JSON 数组,不用 tool schema
                max_tokens=400,
                timeout_sec=timeout_sec,
                agent_kind="world_heartbeat",
                no_think=True,
                log_tag="world_heartbeat",
            )
        except Exception as exc:
            log.info("[world_heartbeat] LLM 调用失败,跳过: %s", exc)
            return []

        from core.json_parse import parse_llm_json
        raw_items = parse_llm_json(text, want=list)
        if raw_items is None:
            # 便宜模型形态漂移打捞(生产实测:吐成 {"事件一": "事件二"} 键值对/或
            # {"items": [...]} 包装)。确定性拆出字符串候选,验收器统一把关,不放宽验收。
            _d = parse_llm_json(text, want=dict)
            if isinstance(_d, dict):
                _salvage: list[str] = []
                for _k, _v in _d.items():
                    if isinstance(_v, list):
                        _salvage.extend(x for x in _v if isinstance(x, str))
                        continue
                    for _cand in (_k, _v):
                        # ≥8 字符才算候选:滤掉 "items"/"events" 这类包装键名
                        if isinstance(_cand, str) and len(_cand) >= 8:
                            _salvage.append(_cand)
                if _salvage:
                    log.info("[world_heartbeat] dict 形态打捞出 %d 条候选", len(_salvage))
                    raw_items = _salvage
        if raw_items is None:
            log.info("[world_heartbeat] 输出不是合法 JSON 数组,跳过(raw前120字: %r)", (text or "")[:120])
            return []

        turn = int(state_data.get("turn", 0) or 0)
        # 更新节流锚点:不论本次验收是否有条目通过,只要 tick 真的跑过(拿到了 LLM
        # 输出并尝试解析)就更新 —— 避免全拒时下一回合立刻又被 should_tick 放行、
        # 短时间内重复调用 LLM(设计文档 §2:"全拒则本 tick 空手而归,正常,不重试")。
        _meta(state_data)["last_tick_turn"] = turn

        player_name = str((state_data.get("player") or {}).get("name", "") or "")
        accepted = _validate_items(raw_items, state_data=state_data, player_name=player_name)
        log.info("[world_heartbeat] tick@turn=%s raw=%d accepted=%d", turn, len(raw_items), len(accepted))
        if not accepted:
            return []

        events = _events(state_data)
        written: list[str] = []
        for text_item in accepted:
            # 未浮出上限:超出拒收(设计文档 §1),不影响已浮出的条目计数。
            unsurfaced_count = sum(
                1 for e in events if isinstance(e, dict) and not e.get("surfaced_turn")
            )
            if unsurfaced_count >= MAX_UNSURFACED_STORED:
                break
            entry = {
                "id": f"bg_{secrets.token_urlsafe(6)}",
                "text": text_item,
                "created_turn": turn,
                "surfaced_turn": None,
            }
            events.append(entry)
            written.append(text_item)

        if written:
            log.info("[world_heartbeat] tick@turn=%s 写入 %d 条世界事件", turn, len(written))
        return written
    except Exception as exc:
        log.warning("[world_heartbeat] tick 异常,跳过(不破回合): %s", exc, exc_info=True)
        return []


__all__ = [
    "MIN_TURN_TO_START",
    "TICK_INTERVAL_TURNS",
    "MAX_UNSURFACED_BACKLOG",
    "MAX_UNSURFACED_STORED",
    "SURFACED_RETENTION_TURNS",
    "should_tick",
    "run_heartbeat_tick",
    "_validate_items",
    "_normalize_for_fp",
]
