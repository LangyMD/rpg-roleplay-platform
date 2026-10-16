"""
command_agent.py — task 86: /set 命令的 LLM 工具调用入口。

用户反馈:
> 规则判断永远会有 bug。让 LLM 接管命令,用大模型理解用户自然语言,
> 然后对照实际支持的命令表用"工具调用"完成指令。

设计:
  · system prompt 明示工具调用语义,列出工具表能做什么
  · 用 Anthropic tool_use(强 schema) 让模型可以**并行**调多个工具
    (一次 /set 可能写多个字段,如 "/set 关系=X,主线=Y" 直接拆成 2 个工具调用)
  · Vertex Gemini / OpenAI 兼容 fallback: 走 JSON mode 返回
    [{"name":...,"input":{...}}, ...] 列表
  · 失败时 (模型没产 tool_call / 解析失败) 返回 [],由调用方决定 fallback

公开 API:
    parse_set_command(set_text, state_data, user_id=None) → list[dict]
        返回 [{"name": str, "input": dict}, ...] 准备给 command_tools.execute_tool。
"""
from __future__ import annotations

import json
from typing import Any

from agents.provider_errors import provider_detail
from core.json_parse import parse_llm_json
from core.llm_backend import (
    detect_default_api as _detect_default_api,
)
from core.llm_backend import (
    resolve_preferred_api as _resolve_preferred_api_base,
)
from core.llm_backend import (
    resolve_preferred_model as _resolve_preferred_model_base,
)
from core.logging import get_logger
from tools_dsl.command_tools import COMMAND_TOOLS

log = get_logger(__name__)

# ────────────────────────────────────────────────────────────
# Prompts
# ────────────────────────────────────────────────────────────


_SYSTEM_PROMPT = """\
You parse /set commands. The player wrote, in natural language, an instruction to force a
change to the game state. Your job is to **call tools from the tool list** to carry it out,
not to output text.

Key principles:
1. **Only call tools; do not write fiction.** Even if the player's words have a story flavor,
   your only job is to extract the operations.
2. **Combine multiple operations.** If one sentence holds several operations (e.g. "set the time
   to the moon landing, relationship Aria=trust, main quest=rescue her"), return several tool
   calls at once.
3. **Do nothing that the tool list does not cover.** If the player wants to change permissions,
   history, schema_version or other metadata, there is no tool for it: use the clarify tool to
   tell the player "I can't change this field". **Do not** try to get around this with other
   tools. This is a safety design.
4. **If the request is vague, clarify.** If the player's words are genuinely unclear, ask with
   the clarify tool. Do not guess.
5. **Keep the user's own words.** The text/target/value in tool args should use the player's
   own language. Do not retell it for them (only strip a lead-in like "I want X to happen" down
   to the event itself).

Tool selection guide (common mappings):

  Time:
    "set time to X" / "timeline=X" / "switch to X" / "go to chapter X" → set_world_time(target=X)
  Location:
    "location is now X" / "I'm now in X" → set_player_location(location=X)
  Player profile:
    "name=X" → set_player_name
    "identity/occupation/role=X" → set_player_role
    "background=X" → set_player_background
  Relationships:
    "NPC relationship=trust" → set_relationship(character=NPC, status=trust)
  Memory:
    "main quest=X" / "goal=X (long-term)" → set_main_quest
    "current objective=X" → set_current_objective
    "fact: X" → add_memory_fact
    "resource: X" / "I have X" → add_memory_resource
    "ability: X" → add_memory_ability
    "important: X" / "pin: X" → pin_memory
    "note: X" → add_memory_note
  Guesses / constraints:
    "hypothesis / I guess / maybe X" → add_hypothesis
    "hard-constraint variable X=Y" → set_user_variable
"""


def _build_user_prompt(set_text: str, state_data: dict) -> str:
    """组装 user message:当前 state 快照 + /set 文本。"""
    p = (state_data.get("player") or {})
    rels = (state_data.get("relationships") or {})
    m = (state_data.get("memory") or {})
    w = (state_data.get("world") or {})
    snippet = (
        "## Current state snapshot\n"
        f"- player.name = {p.get('name', '') or '(empty)'}\n"
        f"- player.role = {p.get('role', '') or '(empty)'}\n"
        f"- player.current_location = {p.get('current_location', '') or '(empty)'}\n"
        f"- world.time = {w.get('time', '') or '(empty)'}\n"
        f"- world.timeline.current_label = {(w.get('timeline') or {}).get('current_label', '') or '(empty)'}\n"
        f"- memory.main_quest = {m.get('main_quest', '') or '(empty)'}\n"
        f"- memory.current_objective = {m.get('current_objective', '') or '(empty)'}\n"
        f"- known relationships: {', '.join(list(rels.keys())[:10]) or '(none)'}\n"
    )
    return snippet + "\n\n## Player /set text\n" + (set_text or "")[:1500]


# ────────────────────────────────────────────────────────────
# Backend dispatch
# ────────────────────────────────────────────────────────────


def parse_set_command(
    set_text: str,
    state_data: dict,
    user_id: int | None = None,
    model_override: str | None = None,
    api_id_override: str | None = None,
    timeout_sec: int = 15,
) -> list[dict]:
    """主入口。返回 [{"name":..., "input":...}, ...] 工具调用列表。

    失败 (异常 / 模型不配合) 返回 [],外层决定 fallback。
    """
    if not set_text or not set_text.strip():
        return []

    # 模型偏好与 set_parser 共享(用户在前端 preferences 里设的同一项)。
    # 默认 backend: Vertex Gemini (与 GM 一致;部署里 vertex_sa.json 已配),
    # 而不是 Anthropic — 多数本地部署没配 ANTHROPIC_API_KEY,导致 401 → fallback。
    try:
        from core.llm_backend import first_user_model
        user_default = first_user_model(user_id)
    except Exception:
        user_default = None
    api_id = api_id_override or _resolve_preferred_api(user_id) or (user_default[0] if user_default else None) or _detect_default_api()
    model = model_override or _resolve_preferred_model(user_id) or (user_default[1] if user_default else None) or _default_model_for_api(api_id)

    # BYOK 守卫:解析出的 provider 用户实际不可用(典型:落到默认 vertex_ai 但用户没传 SA,
    # 或 stale set_parser 偏好指向没配 key 的 provider)→ 回退到用户配过 key 的第一个模型。
    # 否则 command_agent 抛「未找到 Vertex SA」→ /set 等命令解析整段失败(实测生产日志高频)。
    from core.llm_backend import guard_byok_usable as _guard_byok_usable
    api_id, model = _guard_byok_usable(user_id, api_id, model)

    user_prompt = _build_user_prompt(set_text, state_data)

    try:
        if api_id == "anthropic":
            return _call_anthropic_tools(model, user_prompt, user_id, timeout_sec)
        if api_id == "vertex_ai":
            return _call_vertex_tools(model, user_prompt, user_id)
        # OpenAI 兼容
        return _call_openai_compat_tools(api_id, model, user_prompt, user_id, timeout_sec)
    except Exception as exc:
        # provider_detail:urllib HTTPError 挂了响应体后取服务商原话(已脱敏),不再只有「HTTP Error 400」。
        log.warning(f"[command_agent] parse failed: {type(exc).__name__}: {provider_detail(exc)}")
        return []


# ────────────────────────────────────────────────────────────
# Anthropic native tool_use
# ────────────────────────────────────────────────────────────


def _call_anthropic_tools(
    model: str, user_prompt: str, user_id: int | None, timeout_sec: int = 15,
) -> list[dict]:
    """Anthropic native tool_use,允许并行多个 tool_use blocks。

    timeout_sec:调用方(聊天 directives 阶段传 15)的上限,与 OpenAI 兼容分支同口径,SDK 不重试。"""
    from agents._harness import micro_task_anthropic_client
    from platform_app.user_credentials import resolve_api_key
    result = resolve_api_key(user_id, "anthropic", env_fallback="ANTHROPIC_API_KEY")
    key = result.get("key")
    if not key:
        raise RuntimeError("No Anthropic API key for command_agent")
    # 走统一出站层(不跟随重定向 + 凭据代理),读超时守调用方的 timeout_sec。
    client = micro_task_anthropic_client(result, timeout_sec=timeout_sec)
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        tools=COMMAND_TOOLS,
        # 不强制 single tool — 允许模型并行多调
    )
    calls: list[dict] = []
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            calls.append({
                "name": block.name,
                "input": dict(block.input or {}),
            })
    return calls


# ────────────────────────────────────────────────────────────
# Vertex Gemini fallback: JSON mode (没 native function calling 兜底)
# ────────────────────────────────────────────────────────────


_JSON_MODE_INSTRUCTION = """
**Output format**: return a JSON array; each item is one tool call:
[
  {"name": "set_world_time", "input": {"target": "..."}},
  {"name": "set_relationship", "input": {"character": "...", "status": "..."}}
]
- No markdown and no natural-language explanation. Output only the JSON array.
- One /set command can hold several tool calls; the array runs in order.
- Tool names must exactly match the tool list above.
- input values must match the types the tool list gives: integer parameters take a bare
  number only (e.g. 30), with no words or units (wrong: "chapter 30", right: 30).
- If the user's words truly cannot be mapped, return [{"name": "clarify", "input": {"question": "..."}}].
"""


def _build_tool_table_doc() -> str:
    """把工具表序列化成一段文本,放进 system prompt 让 fallback 模型也能选工具。"""
    lines: list[str] = []
    for t in COMMAND_TOOLS:
        lines.append(f"- {t['name']}({_schema_args(t['input_schema'])}): {t['description']}")
    return "\n".join(lines)


def _schema_args(schema: dict) -> str:
    props = schema.get("properties", {})
    required = set(schema.get("required") or [])
    parts = []
    for name, spec in props.items():
        suffix = "" if name in required else "?"
        # 带上类型:JSON-mode fallback 模型只见这段文档,丢类型会把 integer 参数
        # 传成玩家原话字符串(生产实锤 to_chapter="第30章")。
        ftype = (spec or {}).get("type") if isinstance(spec, dict) else None
        parts.append(f"{name}{suffix}:{ftype}" if ftype else f"{name}{suffix}")
    return ", ".join(parts)


def _call_vertex_tools(model: str, user_prompt: str, user_id: int | None) -> list[dict]:
    from agents.gm import _VertexBackend
    backend = _VertexBackend(model=model)
    system_prompt = (
        _SYSTEM_PROMPT
        + "\n\n## Available tools\n"
        + _build_tool_table_doc()
        + "\n\n"
        + _JSON_MODE_INSTRUCTION
    )
    text = backend.call_structured(
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=1500,
    )
    return _parse_tool_call_json_array(text)


def _call_openai_compat_tools(
    api_id: str, model: str, user_prompt: str, user_id: int | None, timeout_sec: int
) -> list[dict]:
    """OpenAI 兼容 JSON mode。"""
    from model_registry import base_url_for
    from platform_app.user_credentials import (
        resolve_api_key,
        resolved_auth_token,
        resolved_is_usable,
    )
    cred = resolve_api_key(user_id, api_id)
    if not resolved_is_usable(cred):
        raise RuntimeError(f"No {api_id} credential for command_agent")
    key = resolved_auth_token(cred)   # 免鉴权 → 占位 token
    base_url = cred.get("base_url_override") or base_url_for(api_id)
    if not base_url:
        raise RuntimeError(f"Unknown base_url for {api_id}")
    import urllib.request

    # SSRF(不跟随重定向 + use-time 重解析 pin IP)走 core.outbound.safe_urlopen;经 _harness 那层薄包装,
    # 失败时响应体挂到 HTTPError.body 上(本路径的错误在上层被吞成 [] 只留日志,日志里也该有原话)。
    from agents._harness import _no_redirect_urlopen
    from core.outbound import credential_proxy
    _proxy = credential_proxy(cred)  # 凭据代理(本地模式才有值;没配时为 None)
    system_prompt = (
        _SYSTEM_PROMPT
        + "\n\n## Available tools\n"
        + _build_tool_table_doc()
        + "\n\n"
        + _JSON_MODE_INSTRUCTION
    )
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 1500,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with _no_redirect_urlopen(req, timeout=timeout_sec, proxy=_proxy) as resp:
        raw = resp.read().decode("utf-8")
    parsed = json.loads(raw)
    if not parsed.get("choices"):
        raise RuntimeError(f"Unexpected provider response shape: {str(parsed)[:200]}")
    content = (parsed.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return _parse_tool_call_json_array(content)


def _parse_tool_call_json_array(text: str) -> list[dict]:
    """解析模型输出的 JSON,容错地抽出 tool calls 列表。

    解析委托 core.json_parse.parse_llm_json(want=list);**原契约不变**:
    拿不到 list 返回 [](注:模型偶尔给 {"calls": [...]} 这类 dict 包裹,
    want=list 会过滤掉它,故先尝试 list,失败再尝试不限类型让 _coerce_calls
    从 dict 形状里抠 calls/tool_calls/单对象)。
    """
    if not text:
        return []
    parsed = parse_llm_json(text, want=list)
    if parsed is None:
        parsed = parse_llm_json(text)  # 容忍 {"calls": [...]} / 单对象 dict
    if parsed is None:
        return []
    return _coerce_calls(parsed)


def _coerce_calls(parsed: Any) -> list[dict]:
    """把不同形状的输出统一成 [{name,input}, ...]"""
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        if isinstance(parsed.get("calls"), list):
            items = parsed["calls"]
        elif isinstance(parsed.get("tool_calls"), list):
            items = parsed["tool_calls"]
        elif parsed.get("name"):
            items = [parsed]
        else:
            items = []
    else:
        items = []
    out: list[dict] = []
    valid_names = {t["name"] for t in COMMAND_TOOLS}
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name") or it.get("tool")
        args = it.get("input") or it.get("arguments") or it.get("args") or {}
        if not isinstance(args, dict):
            continue
        if name in valid_names:
            out.append({"name": name, "input": args})
    return out


# ────────────────────────────────────────────────────────────
# Model preference resolution — 实现已移至 core.llm_backend
# ────────────────────────────────────────────────────────────


def _default_model_for_api(api_id: str) -> str:
    if api_id == "anthropic":
        return "claude-haiku-4-5-20251001"
    from core.llm_backend import DEFAULT_FALLBACK_MODEL
    return DEFAULT_FALLBACK_MODEL


def _resolve_preferred_model(user_id: int | None) -> str | None:
    """Alias → core.llm_backend.resolve_preferred_model (set_parser namespace)."""
    return _resolve_preferred_model_base(user_id, pref_key="set_parser.model_real_name")


def _resolve_preferred_api(user_id: int | None) -> str | None:
    """Alias → core.llm_backend.resolve_preferred_api (set_parser namespace)."""
    return _resolve_preferred_api_base(user_id, pref_key="set_parser.api_id")


__all__ = ["parse_set_command"]
