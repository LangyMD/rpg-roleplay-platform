"""群反馈截图(与 #106 同一位用户):助手面板一排工具调用全是「失败 · 未知工具」,工具名为空,
参数却都对(ui_describe 的 intent、ask_user_choice 的 question/options…)。用户以为缺了工具要装。

根因同 #106:降级路径没告诉模型 <<TOOL_CALL>> 里的字段名,模型写成了 OpenAI 习惯的
{"name", "arguments"}。arguments 对上了,解析器只认 tool 字段 → 工具名空 → 路由报「未知工具」,
回给模型的也只有这四个字,于是原样重试。

断言:常见写法都能解析;真缺工具名时报错说清缺什么、并给出格式;native 路径拿到空名也不去路由。
"""
import json

import pytest

from agents.gm.backends.openai_compat import _OpenAICompatBackend
from agents.gm.helpers import _openai_text_marker_loop, parse_tool_marker

_TOOLS = [
    {"server_id": "dispatcher", "name": "ui_describe"},
    {"server_id": "dispatcher", "name": "ask_user_choice"},
]


@pytest.mark.parametrize("payload", [
    {"server_id": "dispatcher", "tool": "ui_describe", "arguments": {"intent": "世界书"}},
    {"name": "ui_describe", "arguments": {"intent": "世界书"}},                       # OpenAI 习惯
    {"tool": "dispatcher/ui_describe", "arguments": {"intent": "世界书"}},            # 照抄清单写法
    {"name": "dispatcher__ui_describe", "parameters": {"intent": "世界书"}},          # native 编码 + parameters
    {"function": {"name": "ui_describe", "arguments": "{\"intent\": \"世界书\"}"}},   # 嵌套 + 字符串参数
    {"server_id": "dispatcher", "tool": "dispatcher/ui_describe", "args": {"intent": "世界书"}},
])
def test_common_shapes_resolve_to_same_call(payload):
    assert parse_tool_marker(json.dumps(payload, ensure_ascii=False), _TOOLS) == (
        "dispatcher", "ui_describe", {"intent": "世界书"})


def test_missing_name_says_what_is_missing():
    with pytest.raises(ValueError) as ei:
        parse_tool_marker('{"arguments": {"query": "灵气世界总纲"}}', _TOOLS)
    assert "tool name" in str(ei.value) and '"tool"' in str(ei.value)


def test_non_object_rejected():
    with pytest.raises(ValueError):
        parse_tool_marker('["ui_describe"]', _TOOLS)


def test_text_marker_loop_runs_name_style_call():
    """截图同款:模型用 name 字段调 ask_user_choice → 这次必须真执行,而不是「未知工具」。"""
    call = {"name": "ask_user_choice", "arguments": {
        "question": "这条「修行难度」补注怎么落库?", "options": ["追加到 #4 末尾", "替换 #4"],
        "allow_free_text": True}}
    replies = iter([["好。<<TOOL_CALL>>" + json.dumps(call, ensure_ascii=False) + "<<END_TOOL_CALL>>"], ["等你选。"]])

    class _B:
        def stream(self, system, messages, max_tokens):
            yield from next(replies)

    seen = []
    events = list(_openai_text_marker_loop(
        _B(), "sys", [{"role": "user", "content": "补一条"}], _TOOLS, 3, 256,
        lambda sid, tool, args: seen.append((sid, tool)) or {"ok": True, "result": "ok"},
    ))
    assert seen == [("dispatcher", "ask_user_choice")]
    assert not [e for e in events if e["type"] == "tool_error"]


def test_text_marker_loop_missing_name_feeds_back_actionable_hint():
    replies = iter([['<<TOOL_CALL>>{"arguments":{"query":"灵气世界总纲"}}<<END_TOOL_CALL>>'], ["好的。"]])
    sent = []

    class _B:
        def stream(self, system, messages, max_tokens):
            sent.append([dict(m) for m in messages])
            yield from next(replies)

    list(_openai_text_marker_loop(_B(), "sys", [{"role": "user", "content": "查"}], _TOOLS, 3, 256,
                                  lambda *a: {"ok": True}))
    hint = sent[1][-1]["content"]
    assert "tool name" in hint and "<<TOOL_CALL>>" in hint


def test_native_loop_does_not_route_empty_name():
    class _D:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def _stream(tool_call):
        tc = _D(index=0, id="c1", function=_D(name=None, arguments='{"intent":"x"}'))
        if tool_call:
            yield _D(usage=None, choices=[_D(delta=_D(reasoning_content=None, content=None, tool_calls=[tc]),
                                             finish_reason="tool_calls")])
        else:
            yield _D(usage=None, choices=[_D(delta=_D(reasoning_content=None, content="好。", tool_calls=None),
                                             finish_reason="stop")])

    b = object.__new__(_OpenAICompatBackend)
    b.api_id, b.model_name, b.user_id = "relay_x", "m", 1
    b.last_usage = {}
    b._tuning_kwargs = lambda _t: {}
    b._capture_usage = lambda *a, **k: None
    n = []
    b._create = lambda **kw: (n.append(1), _stream(len(n) == 1))[1]
    routed = []
    events = list(b.stream_with_mcp_loop(
        system="s", messages=[{"role": "user", "content": "hi"}],
        mcp_tools=[{"server_id": "dispatcher", "name": "ui_describe", "schema": {"type": "object", "properties": {}}}],
        max_iterations=3, max_tokens=64,
        mcp_call=lambda *a: routed.append(a) or {"ok": True},
    ))
    assert routed == []
    err = [e for e in events if e["type"] == "tool_result"][0]["error"]
    assert "no tool name" in err
