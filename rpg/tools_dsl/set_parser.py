"""set_parser.py — task 77：/set 自然语言参数解析子代理

设计动机（codex §4+7.3）：
当前 detect_set_directive 只能识别 /set path=value 这种简单形式。
玩家说 "/set 蕾穆丽娜对斯雷因的信任度降低，因为她发现他隐瞒情报"
不能精确落到多个字段。

set_parser 用便宜 LLM 把自然语言 /set 拆成多条 JSON ops：
  - relationships.<角色>: 关系变化
  - memory.facts (append): 本局事实
  - worldline.user_variables.<key>: 硬约束变量
  - player.* / world.*: 属性修改
  - hypothesis: 玩家想假设的内容

接口：
    parse_set_directive(set_text, state_data, user_id=None, ...) → list[dict]

失败语义：
- 模型异常 / JSON 解析失败 → 返回 []（外层不破坏 /set 流程）
- 模型说"无法拆分" → 返回 []

调用约定：
- 外层（ui.py）应在 apply_player_directives 之后调用本模块
- 本模块返回的 ops 由外层走 apply_state_write(source="user:/set:parser", force=True)
- 完全 opt-in: 用户 preferences.set_parser.enabled = true 才启用

模型选择（同 extractor）：
1. api_id_override / model_override
2. user_preferences.set_parser.api_id / model_real_name
3. 默认 vertex_ai / gemini-3.5-flash（最便宜的当代旗舰）
"""
from __future__ import annotations

import json
import re

from core.logging import get_logger

log = get_logger(__name__)

_SET_PARSER_SYSTEM = """\
You are the /set parser. The player has described, in natural language, settings they want to force-overwrite;
you break that down into a precise list of JSON ops for the system to write. **Do not write fiction**; output JSON only.

Writable fields:
- player.name / player.role / player.background / player.current_location
- world.time / world.weather / world.timeline.current_phase
- memory.main_quest / memory.current_objective
- memory.facts (use op=append)
- relationships.<character name>  - a relationship status such as "trusting/wary/hostile/close/tense/distant"
- worldline.user_variables.<variable name>  - a player hard-constraint variable

Never write (hard blacklist):
- permissions.* / history.* / schema_version

Available ops:
- "set":      overwrite the field
- "append":   append to a list (only list fields such as memory.facts/resources/abilities/pinned/notes)
- "hypothesis": something the player wants to hypothesize; stored separately, not in facts

Output format (**strict JSON, no markdown, no explanation**):
{
  "ops": [
    {"op":"set","path":"relationships.Slaine","value":"trust declining"},
    {"op":"append","path":"memory.facts","value":"Lemrina discovered that Slaine is withholding intel"},
    {"op":"set","path":"worldline.user_variables.trust_slaine","value":"Lemrina's trust in Slaine is declining"}
  ]
}

If the player's wording is vague (e.g. "/set make the story a bit darker"), do not force a breakdown; output ops=[]
and let the GM absorb it naturally in the narration; do not cram it into set fields.

If there is no field-level intent to break down at all, output {"ops":[]}.
"""


def _build_user_prompt(set_text: str, state_data: dict) -> str:
    """组装 set_parser 的 user message：当前 state 快照 + /set 文本。"""
    p = (state_data.get("player") or {})
    rels = (state_data.get("relationships") or {})
    m = (state_data.get("memory") or {})
    snippet = (
        f"## Current state snapshot\n"
        f"- player.name = {p.get('name', '') or '(empty)'}\n"
        f"- player.role = {p.get('role', '') or '(empty)'}\n"
        f"- player.current_location = {p.get('current_location', '') or '(empty)'}\n"
        f"- memory.main_quest = {m.get('main_quest', '') or '(empty)'}\n"
        f"- Known relationships: {', '.join(list(rels.keys())[:10]) or '(none)'}\n"
    )
    return snippet + "\n\n## The player's /set text\n" + (set_text or "")[:1200]


_JSON_FENCE = re.compile(r"```(?:json)?\s*\n?\s*([\[\{][\s\S]*?[\]\}])\s*\n?```", re.MULTILINE)


def _parse_parser_output(text: str) -> list[dict]:
    """从模型回复里抠出 ops 数组。支持裸 dict {ops:[...]} / 裸数组 / fence。"""
    if not text:
        return []
    text = text.strip()
    # 1) 整段是 JSON
    for candidate in (text, text.lstrip("`json").rstrip("`").strip()):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and "ops" in parsed:
                ops = parsed["ops"]
                if isinstance(ops, list):
                    return [o for o in ops if isinstance(o, dict)]
            if isinstance(parsed, list):
                return [o for o in parsed if isinstance(o, dict)]
        except Exception:
            pass
    # 2) ```json 块兜底
    for m in _JSON_FENCE.finditer(text):
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict) and "ops" in parsed:
                ops = parsed["ops"]
                if isinstance(ops, list):
                    return [o for o in ops if isinstance(o, dict)]
            if isinstance(parsed, list):
                return [o for o in parsed if isinstance(o, dict)]
        except Exception:
            continue
    return []


def parse_set_directive(
    set_text: str,
    state_data: dict,
    user_id: int | None = None,
    model_override: str | None = None,
    api_id_override: str | None = None,
    timeout_sec: int = 15,
) -> list[dict]:
    """主入口。失败返回 []。

    复用 extractor.py 已经写好的 3 条 native function calling 通道
    （Anthropic tool_use / Vertex JSON mode / OpenAI response_format），
    没必要重新发明轮子——它的实现就是结构化 JSON 调用，set_parser 用法完全一样。
    """
    if not set_text or not set_text.strip():
        return []

    try:
        from core.llm_backend import (
            DEFAULT_FALLBACK_API,
            DEFAULT_FALLBACK_MODEL,
            first_user_model,
        )
        user_default = first_user_model(user_id)
    except Exception:
        user_default = None
        # import 失败时的硬编码兜底必须与 core.llm_backend.DEFAULT_FALLBACK_MODEL 同值
        # (现行『当前默认』gemini-3.5-flash),否则又制造 2.5/3.5 漂移。
        DEFAULT_FALLBACK_API, DEFAULT_FALLBACK_MODEL = "vertex_ai", "gemini-3.5-flash"
    api_id = api_id_override or _resolve_preferred_api(user_id) or (user_default[0] if user_default else None) or DEFAULT_FALLBACK_API
    model = model_override or _resolve_preferred_model(user_id) or (user_default[1] if user_default else None) or DEFAULT_FALLBACK_MODEL

    try:
        # 复用 extractor 的 backend dispatcher（同 schema 同协议同 fallback）
        from agents.extractor import _call_extractor_backend
        text = _call_extractor_backend(
            api_id=api_id,
            model=model,
            system_prompt=_SET_PARSER_SYSTEM,
            user_prompt=_build_user_prompt(set_text, state_data),
            user_id=user_id,
            timeout_sec=timeout_sec,
        )
    except Exception as exc:
        log.warning(f"[set_parser] call failed: {exc}")
        return []
    return _parse_parser_output(text)


def _resolve_preferred_model(user_id: int | None) -> str | None:
    """薄委托 → core.llm_backend.resolve_preferred_model(set_parser 命名空间)。

    收编原裸 SQL 副本:统一走 request cache + _model_in_catalog 失效校验
    —— 偏好里的模型已下线/迁移(不在用户 catalog)时回退到 first_user_model,
    不再返回 stale 模型(本批次修的 bug)。返回契约不变(model 字符串或 None)。
    """
    from core.llm_backend import resolve_preferred_model
    return resolve_preferred_model(user_id, pref_key="set_parser.model_real_name")


def _resolve_preferred_api(user_id: int | None) -> str | None:
    """薄委托 → core.llm_backend.resolve_preferred_api(set_parser 命名空间)。失效校验同上。"""
    from core.llm_backend import resolve_preferred_api
    return resolve_preferred_api(user_id, pref_key="set_parser.api_id")
