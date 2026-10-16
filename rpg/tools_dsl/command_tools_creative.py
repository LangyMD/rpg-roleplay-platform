"""
command_tools_creative.py — 创意推荐工具

当前包含:
  recommend_player_identity
    新建存档时, 根据剧本 + 出生点 + 角色卡, 用 LLM 推荐 3-5 个契合出生点
    剧情阶段的初始身份 (玩家在剧本世界中的定位/职业/动机)。

scope="script", origins=_USER_ORIGINS_READ (任意 origin 可调, 纯 LLM 推荐, 无写入)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from tools_dsl.command_dispatcher import ToolSpec, get_registry

_log = logging.getLogger(__name__)

# 与 command_tools_saves.py 保持一致 — 任何 origin 都可以调只读工具
_USER_ORIGINS_READ = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat", "console_assistant",
})


# ────────────────────────────────────────────────────────────
# 数据拉取
# ────────────────────────────────────────────────────────────


def _fetch_script_info(script_id: int, user_id: int) -> dict[str, Any] | None:
    """从 DB 拉剧本 title + description, 验证 owner 或公开剧本订阅者归属。

    返回 None 代表无权访问或不存在。
    """
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            # task: union owned + subscribed(read-only,GM 推荐身份等内部工具调用)
            row = db.execute(
                """select s.id, s.title, s.description from scripts s
                where s.id = %s and (
                  s.owner_id = %s
                  or s.id in (select script_id from user_script_subscriptions where user_id = %s)
                )""",
                (script_id, user_id, user_id),
            ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "title": row["title"], "description": row["description"]}
    except Exception:
        return None


def _fetch_phase_digest(script_id: int, phase: str) -> str:
    """按 story_phase 拉前 5 章 chapter_facts.summary 拼成阶段概要。

    返回空字符串表示没拿到 (软降级);此时 _build_system_prompt 不会附【阶段剧情参考】段。

    历史 bug: 旧版 SELECT 不存在的列 fact_text / chapter_index → 异常被 except 静默吞掉 →
    LLM 永远拿不到剧本信息 → 推荐永远跑到 fallback。chapter_facts 实际列名是 chapter/summary。
    """
    if not phase:
        return ""
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            rows = db.execute(
                "select chapter, title, summary from chapter_facts "
                "where script_id = %s and story_phase ilike %s "
                "  and coalesce(summary, '') <> '' "
                "order by chapter asc limit 5",
                (script_id, f"%{phase[:30]}%"),
            ).fetchall() or []
        if not rows:
            return ""
        parts: list[str] = []
        for r in rows:
            ch = r.get("chapter")
            title = (r.get("title") or "").strip()
            summ = (r.get("summary") or "").strip()
            if not summ:
                continue
            head = ""
            if ch is not None:
                head = f"Chapter {ch}"
                if title:
                    head += f" \"{title}\""
            elif title:
                head = f"\"{title}\""
            parts.append(f"[{head}] {summ[:160]}" if head else summ[:160])
        return "\n".join(parts)[:1600]
    except Exception:
        return ""


def _fetch_anchor_info(script_id: int, phase: str, label: str) -> str:
    """从 script_timeline_anchors 拉 story_time_label + sample_summary。"""
    if not label:
        return ""
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            row = db.execute(
                "select story_time_label, story_phase, sample_summary, chapter_min, chapter_max "
                "from script_timeline_anchors "
                "where script_id = %s and story_time_label ilike %s "
                "order by chapter_min limit 1",
                (script_id, f"%{label[:30]}%"),
            ).fetchone()
        if row:
            parts = []
            if row.get("story_phase"):
                parts.append(f"Story phase: {row['story_phase']}")
            if row.get("story_time_label"):
                parts.append(f"Time anchor: {row['story_time_label']}")
            if row.get("chapter_min") is not None:
                parts.append(f"Chapter range: {row['chapter_min']}-{row['chapter_max']}")
            if row.get("sample_summary"):
                parts.append(f"Scene summary: {row['sample_summary'][:200]}")
            return " | ".join(parts)
    except Exception:
        pass
    return ""


def _fetch_character_card(card_id: int, kind: str, user_id: int) -> dict[str, Any] | None:
    """拉角色卡信息 (persona / user_card / script_card)。"""
    if not card_id:
        return None
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if kind == "persona":
                row = db.execute(
                    "select name, identity as role, background, appearance, personality "
                    "from character_cards where id = %s and user_id = %s and card_type = 'persona'",
                    (card_id, user_id),
                ).fetchone()
            elif kind == "user_card":
                row = db.execute(
                    "select name, identity, appearance, personality "
                    "from character_cards where id = %s and user_id = %s and card_type = 'pc'",
                    (card_id, user_id),
                ).fetchone()
            elif kind == "script_card":
                # task: 公开剧本订阅者也能读其 character_card
                row = db.execute(
                    """select cc.name, cc.identity, cc.appearance, cc.personality
                    from character_cards cc
                    join scripts s on cc.script_id = s.id
                    where cc.id = %s and (
                      s.owner_id = %s
                      or s.id in (select script_id from user_script_subscriptions where user_id = %s)
                    )""",
                    (card_id, user_id, user_id),
                ).fetchone()
            else:
                return None
        if not row:
            return None
        return dict(row)
    except Exception:
        return None


# ────────────────────────────────────────────────────────────
# LLM 推荐
# ────────────────────────────────────────────────────────────


_IDENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Identity name or character name"},
                    "role": {"type": "string", "description": "Position/role in one sentence"},
                    "background": {
                        "type": "string",
                        "description": "Background in 20-55 words, describing the connection to the script's world",
                    },
                },
                "required": ["name", "role", "background"],
            },
            "minItems": 1,
            "maxItems": 6,
        }
    },
    "required": ["recommendations"],
}


def _build_system_prompt(
    script_title: str,
    script_desc: str,
    phase: str,
    label: str,
    phase_digest: str,
    anchor_info: str,
    card: dict | None,
    n: int,
    player_origin: str = "soul",
) -> str:
    # 跟身份卡正交:player_origin 决定生成的身份候选是
    # - isekai: "现代灵魂穿越成 X" (X = 该剧本世界里的某个身份),角色卡是穿越后的身体
    # - native: "原作世界 X 身份" (X = 卧底/流亡贵族/避难所逃亡者...),无现代记忆
    # 身份候选风格:魂穿(soul)/肉穿(body)=外来灵魂视角(现代记忆)→"现代灵魂穿越成 X";
    # 一体双魂(dual)/彻底扮演(native)=原住民身份→"原作世界里 X 身份"。旧值 isekai 等同 soul。
    isekai = player_origin in ("isekai", "soul", "body")
    lines = [
        "You are the RPG platform's identity recommendation assistant.",
        (
            "Based on the script, birthpoint and character card the player chose, recommend differentiated starting identities of the form "
            "[a modern soul transmigrated into X]. "
            "The player is essentially a soul from modern-day Earth now occupying the body of the chosen character card, with modern memories + knowledge of the other world."
            if isekai else
            "Based on the script, birthpoint and character card the player chose, recommend differentiated starting identities of the form "
            "[an X identity native to the original world]. "
            "The player is essentially a character born and raised in this script's world, with no modern memories or transmigrator background; their knowledge is limited to the script's setting."
        ),
        "",
        f"[Script title] {script_title}",
    ]
    if script_desc:
        lines.append(f"[Script synopsis] {script_desc[:400]}")
    if phase:
        lines.append(f"[Birthpoint phase] {phase}")
    if label:
        lines.append(f"[Birthpoint time anchor] {label}")
    if anchor_info:
        lines.append(f"[Anchor details] {anchor_info}")
    if phase_digest:
        lines.append(f"[Phase story reference] {phase_digest}")
    if card:
        card_lines = []
        if card.get("name"):
            card_lines.append(f"Name: {card['name']}")
        role_or_id = card.get("role") or card.get("identity") or ""
        if role_or_id:
            card_lines.append(f"Identity/position: {role_or_id}")
        if card.get("personality"):
            card_lines.append(f"Personality: {card['personality'][:80]}")
        if card.get("appearance"):
            card_lines.append(f"Appearance: {card['appearance'][:80]}")
        if card_lines:
            lines.append(f"[Chosen character card] {' | '.join(card_lines)}")
    lines += [
        "",
        f"Generate {n} differentiated starting identity options.",
        "Requirements:",
        "  · Each identity has a different perspective (e.g. active participant / passive witness / outsider / insider of power / bottom-rung survivor)",
        "  · Each identity fits the story logic of the current birthpoint phase closely",
        "  · name: the character's full name or code name",
        "  · role: their position / occupation / relationships in the script's world, in one sentence",
        "  · background: 20-55 words explaining the character's origins and connection to the birthpoint phase; "
        "**an objective third-person description without a subject** (e.g. \"An undercover agent embedded in the enemy camp, carrying the vengeance of a slaughtered clan...\"); never use the second person (\"you\" / \"you are\")",
        (
            "  · Must show [transmigrator traits] - a modern soul + an other-world body + memories of the original world + partial foreknowledge of the canon plot"
            if isekai else
            "  · Strictly no [modern / transmigration / reincarnation / visitor-from-another-world / canon foreknowledge] elements - the player is a native of this world, with knowledge limited to the script's setting"
        ),
        "  · Do not stuff all of the script's lore into background; focus on motives directly related to the birthpoint",
        "",
        "Output the JSON in one go through the emit_identities tool; do not write any extra explanation.",
    ]
    return "\n".join(lines)


def _call_llm_emit_identities(
    user_id: int,
    system: str,
    n: int,
) -> list[dict] | None:
    """调 LLM 生成身份推荐列表。Anthropic 走 native tool_use, 其余走 JSON mode。"""
    # 复用 character_card_generator 的 backend 选择逻辑
    try:
        from character_card_generator import _select_backend
        backend = _select_backend(user_id)
    except Exception:
        _log.exception("[identity-gen] _select_backend 失败 user_id=%s", user_id)
        return None

    backend_kind = type(backend).__name__
    # 直连 backend(未经 _harness),输出语言指令在此确定性补上
    try:
        from core.language import agent_language_directive
        system = system + agent_language_directive(user_id)
    except Exception:
        pass

    tool_def = {
        "name": "emit_identities",
        "description": "Output the list of recommended identities.",
        "input_schema": _IDENTITY_SCHEMA,
    }

    if backend_kind == "_AnthropicBackend":
        try:
            resp = backend.client.messages.create(
                model=backend.model_name,
                max_tokens=1200,
                temperature=0.85,
                system=system,
                messages=[{"role": "user", "content": f"Generate {n} identity recommendations."}],
                tools=[tool_def],
                tool_choice={"type": "tool", "name": "emit_identities"},
            )
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "emit_identities":
                    inp = block.input or {}
                    if isinstance(inp, dict):
                        return inp.get("recommendations") or []
        except Exception:
            _log.exception("[identity-gen] Anthropic 调用失败 model=%s", getattr(backend, "model_name", "?"))
            return None
    else:
        # JSON mode fallback
        try:
            schema_hint = json.dumps(_IDENTITY_SCHEMA, ensure_ascii=False, indent=2)[:1500]
            full_sys = (
                system
                + "\n\nYou must return only a JSON object matching the following JSON Schema, without Markdown fences:\n"
                + schema_hint
            )
            text = backend.call_structured(
                full_sys,
                [{"role": "user", "content": f"Generate {n} identity recommendations."}],
                max_tokens=1200,
            )
            obj = _parse_json_safely(text)
            if obj and isinstance(obj.get("recommendations"), list):
                return obj["recommendations"]
            # 诊断:LLM 有返回但格式不符(缺 recommendations 数组)→ 记 model + 文本片段,
            # 便于定位「身份推荐为空」的根因。采自社区 PR #16/#18(xingzhiyou)。
            _log.warning("[identity-gen] %s 返回格式异常 model=%s text=%s",
                         backend_kind, getattr(backend, "model_name", "?"),
                         (text or "")[:800])
        except Exception:
            _log.exception("[identity-gen] %s 调用失败 model=%s",
                           backend_kind, getattr(backend, "model_name", "?"))
            return None
    return None


def _parse_json_safely(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None


# harness:身份卡描述强制第三人称无主语。AI 常写成「你是XXX」(第二人称),文学上不对 ——
# 身份卡是对"这个身份"的客观描述,不是对玩家喊话。不靠提示词运气,这里确定性剥掉第二人称主语。
_SUBJ_DROP = (("作为你", ""), ("作为您", ""), ("你是", ""), ("您是", ""),
              ("你乃", ""), ("你即", ""), ("你的", ""), ("您的", ""))


def _to_subjectless(text: str) -> str:
    """把第二人称身份描述(「你是XXX」/「你的过去…」)确定性转成第三人称无主语客观叙述。
    无论 LLM 怎么写,保证输出不残留「你/您」第二人称主语。"""
    if not text:
        return text
    s = str(text).strip()
    for a, b in _SUBJ_DROP:
        s = s.replace(a, b)
    s = re.sub(r"[你您]", "", s)                       # 残留的「你/您」→ 删(无主语)
    s = re.sub(r"^[\s，,、。:：；;！!？?]+", "", s)       # 清理删词后留下的前导标点
    s = re.sub(r"[，,、]{2,}", "，", s)                 # 合并因删词产生的连续逗号
    return s.strip()


def _normalize_recommendation(item: Any) -> dict[str, str]:
    """确保 name/role/background 非 null 字符串;并把 role/background 强制成第三人称无主语。"""
    if not isinstance(item, dict):
        item = {}
    return {
        "name": str(item.get("name") or ""),
        "role": _to_subjectless(str(item.get("role") or "")),
        "background": _to_subjectless(str(item.get("background") or "")),
    }


# 注:v27 删除了 _fallback_recommendations。LLM 失败时不再返回硬编码模板,
# 而是显式报错给上层,让 UI 引导用户走"直接用角色卡"或"手动自定义身份"两条路径。
# 历史模板是"剧本主角"+"局外观察者",在前端表现为永远固定两个建议 → 用户体验等同于推荐
# 完全失效。删除是为了暴露真实的 LLM/数据问题(否则 fallback 永远兜底,bug 不会冒头)。


# ────────────────────────────────────────────────────────────
# 工具主函数
# ────────────────────────────────────────────────────────────


def _t_recommend_player_identity(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """推荐初始身份 — script 级工具, executor 签名 (user_id, script_id, args, state)。

    返回值约定:
      成功: {"ok": true, "recommendations": [{name, role, background}, ...]}
      失败: {"ok": false, "error": "<真实错误描述>"}  ← UI 应展示并引导用户改走自定义
    """
    # 参数解析
    sid = script_id or args.get("script_id")
    if not sid:
        return json.dumps({"ok": False, "error": "script_id is required"}, ensure_ascii=False)
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "script_id must be an integer"}, ensure_ascii=False)

    phase = (args.get("birthpoint_phase") or "").strip()
    label = (args.get("birthpoint_label") or "").strip()
    card_id_raw = args.get("character_card_id")
    card_kind = (args.get("character_card_kind") or "").strip() or "user_card"
    n_raw = args.get("n", 4)
    try:
        n = max(1, min(6, int(n_raw)))
    except (TypeError, ValueError):
        n = 4
    # player_origin: 'isekai'(穿越/转生) | 'native'(原作角色)
    # 跟身份卡正交 — isekai 时生成"现代灵魂穿越成 X",native 时生成"原作世界 X 身份"
    player_origin = (args.get("player_origin") or "soul").strip().lower()
    if player_origin == "isekai":
        player_origin = "soul"  # 旧值兼容
    if player_origin not in ("soul", "body", "dual", "native"):
        player_origin = "soul"

    # 1) 验证剧本归属
    script_info = _fetch_script_info(sid, user_id)
    if not script_info:
        return json.dumps(
            {"ok": False, "error": "No access to this script"},
            ensure_ascii=False,
        )

    # 2) 拉辅助数据 (软降级, 失败不崩)
    phase_digest = _fetch_phase_digest(sid, phase)
    anchor_info = _fetch_anchor_info(sid, phase, label)
    card: dict | None = None
    if card_id_raw is not None:
        try:
            card = _fetch_character_card(int(card_id_raw), card_kind, user_id)
        except Exception:
            card = None

    # 3) 构建 prompt
    system = _build_system_prompt(
        script_title=script_info["title"],
        script_desc=script_info.get("description") or "",
        phase=phase,
        label=label,
        phase_digest=phase_digest,
        anchor_info=anchor_info,
        card=card,
        n=n,
        player_origin=player_origin,
    )

    # 4) 调 LLM
    raw_recs = _call_llm_emit_identities(user_id=user_id, system=system, n=n)

    # 5) 处理结果 — v27: 失败显式报错,不再兜模板
    if not (raw_recs and isinstance(raw_recs, list) and len(raw_recs) > 0):
        # 区分两类失败:1) backend 选择/调用失败(返 None) 2) 返了但空 list
        detail = "the LLM returned no recommendations"
        if raw_recs is None:
            detail = "the LLM call failed (backend not configured / network error / response could not be parsed)"
        elif isinstance(raw_recs, list) and len(raw_recs) == 0:
            detail = "the LLM returned an empty list, possibly due to insufficient context or a model refusal"
        return json.dumps(
            {"ok": False, "error": f"Identity recommendation failed: {detail}. Create an identity card manually or use the chosen character card directly."},
            ensure_ascii=False,
        )

    recommendations = [_normalize_recommendation(r) for r in raw_recs[:6]]
    return json.dumps(
        {"ok": True, "recommendations": recommendations},
        ensure_ascii=False,
        indent=2,
    )


# ────────────────────────────────────────────────────────────
# 注册
# ────────────────────────────────────────────────────────────


def register_creative_tools() -> None:
    registry = get_registry()

    spec = ToolSpec(
        name="recommend_player_identity",
        description=(
            "When creating a new save, use the LLM to recommend 3-5 starting identities that fit the birthpoint's "
            "story phase (the player's position / occupation / motive in the script's world), based on script + birthpoint + character card. "
            "Returns JSON {ok, recommendations:[{name,role,background}]}. "
            "Optional birthpoint: birthpoint_phase (phase name) + birthpoint_label (time-anchor label). "
            "Optional character card: character_card_id + character_card_kind (persona/user_card/script_card)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "script_id": {
                    "type": "integer",
                    "description": "Target script id",
                },
                "birthpoint_phase": {
                    "type": "string",
                    "description": "Story phase name of the birthpoint (optional)",
                },
                "birthpoint_label": {
                    "type": "string",
                    "description": "Birthpoint time-anchor label (optional, e.g. story_time_label)",
                },
                "character_card_id": {
                    "type": "integer",
                    "description": "Chosen character card id (optional)",
                },
                "character_card_kind": {
                    "type": "string",
                    "enum": ["persona", "user_card", "script_card"],
                    "description": "Character card type (optional, default user_card)",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of identities to recommend (default 4, range 1-6)",
                    "default": 4,
                    "minimum": 1,
                    "maximum": 6,
                },
            },
            "required": ["script_id"],
        },
        executor=_t_recommend_player_identity,
        scope="script",
        origins=_USER_ORIGINS_READ,
        destructive=False,
    )

    if not registry.has(spec.name):
        registry.register(spec)


__all__ = ["register_creative_tools"]
