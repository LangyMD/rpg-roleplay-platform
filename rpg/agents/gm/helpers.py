"""agents.gm.helpers — 共享工具函数 (format_tools, curator tool_use, text_marker_loop)."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any


def _anthropic_curator_tool_use(
    backend, agent_prompt: str, messages: list[dict], max_tokens: int,
) -> str:
    """task 68：用 native tool_use 跑 context curator，input_schema 强校验。

    定义一个 `select_context` 工具，input_schema 描述 curator 的 6 字段输出；
    模型必须以 tool_use block 返回（tool_choice 强制），SDK 校验合规。
    错误率比 re.search(r'\\{.*\\}') 抠 text JSON 低 5-10×。
    返回 dumped JSON 字符串（保持 curate_context 既有 -> str 契约）。
    """
    # task 79：Demand Ledger schema 替换原 6 字段 curator_plan。让 Anthropic
    # native tool_use 强校验所有字段，配合 context_agent.AGENT_PROMPT 同步升级。
    tool = {
        "name": "select_context",
        "description": "Produce this turn's Demand Ledger: player intent, hard/soft constraints, candidate actions, acceptance criteria, confidence self-assessment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "The player's intent in one sentence"},
                "active_goal": {"type": "string", "description": "The underlying real goal (not the literal request)"},
                "hard_constraints": {"type": "array", "items": {"type": "string"}, "description": "Hard constraints that must be satisfied"},
                "soft_preferences": {"type": "array", "items": {"type": "string"}, "description": "Soft preferences that should ideally be satisfied"},
                "target_entities": {"type": "array", "items": {"type": "string"}, "description": "Names of characters / factions involved"},
                "target_location": {"type": "string", "description": "Target location; empty if none"},
                "target_time": {"type": "string", "description": "Target time; empty if none"},
                "timeline_target": {"type": "string", "description": "Target label if a time skip is requested; empty if none"},
                "retrieval_query": {"type": "string", "description": "Short retrieval query"},
                "retrieval_plan": {
                    "type": "object",
                    "properties": {
                        "must_include": {"type": "array", "items": {"type": "string"}, "description": "Facts that must be included this turn"},
                        "should_include": {"type": "array", "items": {"type": "string"}, "description": "Helpful but optional material"},
                    },
                },
                "candidate_actions": {"type": "array", "items": {"type": "string"}, "description": "2-5 candidate actions the GM can take this turn"},
                "acceptance": {"type": "array", "items": {"type": "string"}, "description": "Acceptance criteria for this turn's success, each programmatically verifiable"},
                "risk_flags": {"type": "array", "items": {"type": "string"}, "description": "Risk flags"},
                "confidence": {"type": "number", "description": "Self-assessed confidence 0.0-1.0; <0.5 triggers clarifying_question"},
                "clarifying_question": {"type": "string", "description": "When confidence is low, a closed question + candidate answers; otherwise empty"},
                "reason": {"type": "string", "description": "Why you planned it this way (not shown to the player)"},
            },
            "required": ["intent", "timeline_target", "retrieval_query", "risk_flags", "confidence", "reason"],
        },
    }
    resp = backend.client.messages.create(
        model=backend.model_name,
        max_tokens=max_tokens,
        temperature=0.1,
        system=agent_prompt,
        messages=messages,
        tools=[tool],
        tool_choice={"type": "tool", "name": "select_context"},
    )
    # capture usage 同 backend.call
    usage = getattr(resp, "usage", None)
    if usage:
        backend.last_usage = {
            "input_tokens": int(getattr(usage, "input_tokens", 0)),
            "output_tokens": int(getattr(usage, "output_tokens", 0)),
            "cached_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        }
        backend.last_usage["total_tokens"] = backend.last_usage["input_tokens"] + backend.last_usage["output_tokens"]
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "select_context":
            inp = block.input or {}
            return json.dumps(inp, ensure_ascii=False)
    # 没拿到 tool_use 块 → 返回最小合法 JSON 让 _parse_curator_json 不崩
    return json.dumps({
        "intent": "", "timeline_target": "", "retrieval_query": "",
        "must_include": [], "risk_flags": ["curator returned no tool_use"], "reason": "fallback",
    }, ensure_ascii=False)


def _format_tools_for_prompt(tools: list[dict[str, Any]]) -> str:
    """把 MCP 工具清单格式化成附加 system prompt 片段（text-marker fallback 路径用）。

    协议说明已经在 _SYSTEM_BASE 的「工具调用」段统一描述（task 67），这里只
    枚举本轮可用的工具清单。Anthropic / native tool_use 路径不调用这个函数，
    它专为 Vertex / OpenAI 兼容等还在用文本 marker 的 backend 服务。
    """
    if not tools:
        return ""
    lines = [
        "",
        "【Tool calls: prose iron rule (text-marker path)】",
        "Before and after calling a tool (<<TOOL_CALL>>...<<END_TOOL_CALL>>), never narrate the tool's execution "
        "or results in natural language — no meta-narration like \"character created\", \"setting things up...\", \"all set\", \"let me build this for you...\". "
        "The prose is only the story itself (characters' words and actions, scenes, dialogue); tools are backstage machinery the player cannot see, "
        "and they should not learn of their existence from your prose. When you need to switch / set up a character, emit the tool-call marker directly, and once it is done "
        "carry on naturally with immersive story prose, without explaining the behind-the-scenes work.",
        "",
        # 格式说明必须跟着清单走:GM 的 _SYSTEM_BASE 里写了,但助手等其它调用方的 system 里没有,
        # 模型只看到「<<TOOL_CALL>>」一个词、不知道里面装什么,DeepSeek 就改用它原生的 DSML
        # 标记 → 解析器不认、原样漏给用户(反馈 #106)。
        "【Tool call format】Output each call as its own block: "
        '<<TOOL_CALL>>{"server_id":"<the part before the slash in the list>","tool":"<the part after the slash>","arguments":{...}}<<END_TOOL_CALL>>, '
        "and stop this turn's output right after writing <<END_TOOL_CALL>> to wait for the tool result. Use only this format; "
        "do not output any other tool markup such as function_calls / invoke / DSML.",
        "",
        "【MCP tools available this turn】",
    ]
    for t in tools[:40]:  # 防止 prompt 过长
        sid = t.get("server_id", "")
        name = t.get("name", "")
        desc = (t.get("description", "") or "").strip().replace("\n", " ")[:160]
        schema = t.get("schema") or {}
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        arg_hint = ""
        if props:
            # 带上类型:text-marker 模型只见这段文档,丢类型会把 integer 参数
            # 传成原话字符串("第30章"),与 command_agent._schema_args 同族病
            def _p(k: str) -> str:
                spec = props.get(k)
                ftype = spec.get("type") if isinstance(spec, dict) else None
                star = "*" if k in required else ""
                return f"{k}{star}:{ftype}" if ftype else f"{k}{star}"
            arg_hint = " · args: " + ", ".join(_p(k) for k in list(props.keys())[:8])
        lines.append(f"  · {sid}/{name}: {desc}{arg_hint}")
    return "\n".join(lines)


_MARKER_NAME_KEYS = ("tool", "name", "tool_name", "function_name")
_MARKER_ARG_KEYS = ("arguments", "args", "parameters", "params", "input")
_MARKER_FORMAT = '<<TOOL_CALL>>{"server_id":"...","tool":"...","arguments":{...}}<<END_TOOL_CALL>>'


def parse_tool_marker(raw: str, tools: list[dict[str, Any]] | None = None) -> tuple[str, str, dict[str, Any]]:
    """<<TOOL_CALL>> 里的 JSON → (server_id, tool, arguments)。解析不了抛 ValueError(信息给模型看)。

    约定格式是 {"server_id","tool","arguments"},但模型没被告知或记混时,常写成 OpenAI 的
    {"name","arguments"} / {"function":{"name","arguments"}}、或把清单里的 `server/tool` 整个塞进
    tool。以前只认 tool 字段 → 工具名为空 → 助手面板一排「未知工具」,模型收到的报错也不说缺什么,
    就一直重试(群反馈截图:ui_describe / ask_user_choice 参数都对,名字全丢)。
    """
    # 函数内导入,理由同 _openai_text_marker_loop
    from agents.gm.backends._dsml import resolve_tool_ref

    data = json.loads((raw or "").strip())
    if not isinstance(data, dict):
        raise ValueError("A tool call must be a JSON object")
    fn = data.get("function")
    if isinstance(fn, dict):
        data = {**fn, **{k: v for k, v in data.items() if k != "function"}}
    elif isinstance(fn, str) and "name" not in data:
        data = {**data, "name": fn}
    name = next((str(data[k]).strip() for k in _MARKER_NAME_KEYS
                 if isinstance(data.get(k), str) and data[k].strip()), "")
    if not name:
        raise ValueError(f"Missing tool name (the \"tool\" field). Format: {_MARKER_FORMAT}")
    args: Any = next((data[k] for k in _MARKER_ARG_KEYS if data.get(k) not in (None, "")), {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    server_id = str(data.get("server_id") or data.get("server") or "").strip()
    if not server_id:
        server_id, name = resolve_tool_ref(name, tools)
    else:
        for sep in ("/", "__"):
            if name.startswith(server_id + sep):
                name = name[len(server_id) + len(sep):]
                break
    return server_id, name, args


def _marker_retry_hint(exc: Exception) -> str:
    return f"【System】The previous tool call could not be executed: {exc}. Regenerate it as {_MARKER_FORMAT}, or drop the tool call."


def _openai_text_marker_loop(
    backend, system, messages, mcp_tools, max_iterations, max_tokens, mcp_call,
) -> Iterator[dict[str, Any]]:
    """task 71：不支持 native tools 的 OpenAI 兼容 provider 用 text marker。

    复用主循环的 <<TOOL_CALL>>{json}<<END_TOOL_CALL>> 协议——直接调
    GameMaster.respond_stream_with_tools 内联那段逻辑会循环依赖；这里把它
    单独抽出，让 backend 自己跑 text marker 路径。

    本函数 yields 同样的 text/tool_call/tool_result 事件，与 native 路径
    interchangeable。
    """
    # 函数内导入:agents.gm.backends 包初始化会反过来 import 本模块
    from agents.gm.backends._dsml import DSML_UNPARSED_ERROR, DsmlStreamFilter, resolve_tool_ref

    system_with_tools = system + _format_tools_for_prompt(mcp_tools)
    START = "<<TOOL_CALL>>"
    END = "<<END_TOOL_CALL>>"
    tail_keep = max(len(START), len(END)) - 1
    accumulated_text = ""

    for _iteration in range(max_iterations):
        buffer = ""
        in_tool = False
        tool_invoked = False
        dsml = DsmlStreamFilter()  # 模型没按 <<TOOL_CALL>> 写、改吐 DeepSeek 原生标记时兜底
        for raw_chunk in backend.stream(system_with_tools, messages, max_tokens=max_tokens):
            chunk = dsml.feed(raw_chunk)
            if not chunk:
                continue
            buffer += chunk
            while True:
                if not in_tool:
                    start_idx = buffer.find(START)
                    if start_idx < 0:
                        if len(buffer) > tail_keep:
                            emit = buffer[:-tail_keep]
                            buffer = buffer[-tail_keep:]
                            if emit:
                                accumulated_text += emit
                                yield {"type": "text", "text": emit}
                        break
                    pre = buffer[:start_idx]
                    if pre:
                        accumulated_text += pre
                        yield {"type": "text", "text": pre}
                    buffer = buffer[start_idx + len(START):]
                    in_tool = True
                    continue
                end_idx = buffer.find(END)
                if end_idx < 0:
                    break
                tool_json_raw = buffer[:end_idx]
                buffer = buffer[end_idx + len(END):]
                in_tool = False
                tool_invoked = True
                try:
                    server_id, tool_name, arguments = parse_tool_marker(tool_json_raw, mcp_tools)
                except Exception as exc:
                    yield {"type": "tool_error", "error": f"Failed to parse tool call: {exc}", "raw": tool_json_raw[:200]}
                    messages.append({"role": "assistant", "content": accumulated_text + START + tool_json_raw + END})
                    messages.append({"role": "user", "content": _marker_retry_hint(exc)})
                    accumulated_text = ""
                    break
                yield {"type": "tool_call", "server_id": server_id, "tool": tool_name, "arguments": arguments}
                try:
                    result = mcp_call(server_id, tool_name, arguments)
                except Exception as exc:
                    result = {"ok": False, "error": f"call_tool error: {exc}"}
                yield {
                    "type": "tool_result", "ok": bool(result.get("ok")),
                    "result": result.get("result"), "error": result.get("error"),
                }
                assistant_msg = accumulated_text + START + tool_json_raw + END
                messages.append({"role": "assistant", "content": assistant_msg})
                truncated_result = json.dumps(result, ensure_ascii=False)[:2000]
                messages.append({
                    "role": "user",
                    "content": (
                        f"【Tool result: {server_id}/{tool_name}】\n{truncated_result}\n\n"
                        f"Continue this turn's response based on the tool result (do not repeat the prose already written; you may keep narrating or append state write-backs)."
                    ),
                })
                accumulated_text = ""
                break
            if tool_invoked:
                break
        if not tool_invoked:
            buffer += dsml.finish()
            if dsml.calls and not in_tool:
                if buffer:
                    accumulated_text += buffer
                    yield {"type": "text", "text": buffer}
                    buffer = ""
                # 回放给模型时改写成规范的 <<TOOL_CALL>>,下一跳照着学,而不是继续吐 DSML
                marker_text = ""
                result_blocks = []
                for name, arguments in dsml.calls:
                    server_id, tool_name = resolve_tool_ref(name, mcp_tools)
                    yield {"type": "tool_call", "server_id": server_id, "tool": tool_name, "arguments": arguments}
                    try:
                        result = mcp_call(server_id, tool_name, arguments)
                    except Exception as exc:
                        result = {"ok": False, "error": f"call_tool error: {exc}"}
                    yield {
                        "type": "tool_result", "ok": bool(result.get("ok")),
                        "result": result.get("result"), "error": result.get("error"),
                    }
                    marker_text += START + json.dumps(
                        {"server_id": server_id, "tool": tool_name, "arguments": arguments},
                        ensure_ascii=False) + END
                    result_blocks.append(
                        f"【Tool result: {server_id}/{tool_name}】\n{json.dumps(result, ensure_ascii=False)[:2000]}")
                messages.append({"role": "assistant", "content": accumulated_text + marker_text})
                messages.append({
                    "role": "user",
                    "content": "\n\n".join(result_blocks)
                    + "\n\nContinue this turn's response based on the tool result (do not repeat the prose already written; you may keep narrating or append state write-backs).",
                })
                accumulated_text = ""
                continue
            if in_tool:
                yield {"type": "tool_error", "error": "Unclosed tool call", "raw": buffer[:200]}
                messages.append({"role": "assistant", "content": accumulated_text + START + buffer})
                messages.append({"role": "user", "content": "【System】The previous tool call was not closed. Output the complete marker again, or drop the call."})
                accumulated_text = ""
                continue
            if dsml.seen and not dsml.calls:
                # 与 native 循环(openai_compat.stream_with_mcp_loop)同款:DSML 块被扣下却没解析出调用
                # → 发 tool_error,别让空回合被分诊成「上游返空」。
                yield {"type": "tool_error", "error": DSML_UNPARSED_ERROR, "raw": ""}
            if buffer:
                yield {"type": "text", "text": buffer}
            return
    yield {"type": "text", "text": "\n\n[Tool-call limit reached for this reply (the limit counts calls within this one reply and resets with your next message); this turn has ended]"}
