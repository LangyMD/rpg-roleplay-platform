"""反馈 #106:助手侧栏里原样出现 DeepSeek 的工具调用标记。

用户贴回的原文(下面 _FEEDBACK_106)是走样过的 DSML:竖线成对、标签名前有空格、
最外层丢了 function_ 前缀。工具名 `dispatcher/list_worldbook_entries` 是照抄 text-marker
工具清单的 `server/tool` 写法 —— 说明当时走的是降级路径,而助手的 system 里从没写过
<<TOOL_CALL>> 里该装什么。

断言三件事:
1. 解析器认得走样形态、也认得官方规范形态,逐字符切流也不漏标记;
2. native 循环与 text-marker 循环都把 DSML 当成真工具调用执行,正文里一个标记都不外发;
3. text-marker 的工具清单自带调用格式。
"""
import json

from agents.gm.backends._dsml import DsmlStreamFilter, parse_invokes, resolve_tool_ref
from agents.gm.backends.openai_compat import _OpenAICompatBackend
from agents.gm.helpers import _format_tools_for_prompt, _openai_text_marker_loop

_FEEDBACK_106 = (
    '<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="dispatcher/list_worldbook_entries"> '
    '<｜｜DSML｜｜ parameter name="script_id">5</｜｜DSML｜｜ parameter> '
    '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>'
)
_OFFICIAL = (
    "<｜DSML｜function_calls>\n"
    '<｜DSML｜invoke name="get_weather">\n'
    '<｜DSML｜parameter name="city" string="true">杭州</｜DSML｜parameter>\n'
    '<｜DSML｜parameter name="days" string="false">3</｜DSML｜parameter>\n'
    "</｜DSML｜invoke>\n"
    "</｜DSML｜function_calls>"
)


def _run_filter(text: str, step: int) -> tuple[str, DsmlStreamFilter]:
    f = DsmlStreamFilter()
    out = "".join(f.feed(text[i:i + step]) for i in range(0, len(text), step))
    return out + f.finish(), f


# ── 一、解析 ───────────────────────────────────────────────────────────────────
def test_parses_the_mangled_form_from_feedback_106():
    assert parse_invokes(_FEEDBACK_106) == [("dispatcher/list_worldbook_entries", {"script_id": 5})]


def test_parses_official_form_with_string_flags():
    assert parse_invokes(_OFFICIAL) == [("get_weather", {"city": "杭州", "days": 3})]


def test_string_true_keeps_digits_as_text():
    block = '<｜DSML｜invoke name="t"><｜DSML｜parameter name="n" string="true">007</｜DSML｜parameter></｜DSML｜invoke>'
    assert parse_invokes(block) == [("t", {"n": "007"})]


def test_stream_split_anywhere_never_leaks_markup():
    text = "先查一下。\n" + _FEEDBACK_106 + "\n查完了。"
    for step in (1, 2, 3, 7, 50, len(text)):
        out, f = _run_filter(text, step)
        assert "DSML" not in out and "｜" not in out, f"step={step} 漏出标记: {out!r}"
        assert "先查一下。" in out and "查完了。" in out
        assert f.calls == [("dispatcher/list_worldbook_entries", {"script_id": 5})]


def test_plain_angle_brackets_pass_through():
    out, f = _run_filter("血量 <30 时撤退,a<b 也照常输出", 1)
    assert out == "血量 <30 时撤退,a<b 也照常输出"
    assert not f.calls and not f.seen


def test_truncated_invoke_is_dropped_not_leaked():
    """max_tokens 截在 invoke 中间:不执行半截调用,也不把残渣吐给用户。"""
    out, f = _run_filter('好的。<｜DSML｜function_calls><｜DSML｜invoke name="x"><｜DSML｜parameter name="a">1', 4)
    assert out == "好的。"
    assert f.calls == []


def test_resolve_tool_ref_forms():
    tools = [{"server_id": "srv", "name": "get_weather"}]
    assert resolve_tool_ref("dispatcher/list_worldbook_entries", tools) == ("dispatcher", "list_worldbook_entries")
    assert resolve_tool_ref("srv__get_weather", tools) == ("srv", "get_weather")
    assert resolve_tool_ref("get_weather", tools) == ("srv", "get_weather")
    assert resolve_tool_ref("nope", tools) == ("", "nope")


# ── 二、两条循环端到端 ─────────────────────────────────────────────────────────
class _D:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _content_stream(text: str, step: int = 5):
    for i in range(0, len(text), step):
        last = i + step >= len(text)
        yield _D(usage=None, choices=[_D(
            delta=_D(reasoning_content=None, content=text[i:i + step], tool_calls=None),
            finish_reason="stop" if last else None)])


def test_native_loop_executes_dsml_and_hides_it():
    b = object.__new__(_OpenAICompatBackend)
    b.api_id, b.model_name, b.user_id = "relay_ds", "deepseek-flash", 1
    b.last_usage = {}
    b._tuning_kwargs = lambda _t: {}
    b._capture_usage = lambda *a, **k: None
    sent: list[list[dict]] = []

    def _create(**kw):
        sent.append([dict(m) for m in kw["messages"]])
        if len(sent) == 1:
            return _content_stream("我查一下天气。" + _OFFICIAL)
        return _content_stream("杭州晴。")

    b._create = _create
    calls = []
    events = list(b.stream_with_mcp_loop(
        system="s", messages=[{"role": "user", "content": "天气"}],
        mcp_tools=[{"server_id": "srv", "name": "get_weather", "schema": {"type": "object", "properties": {}}}],
        max_iterations=3, max_tokens=256,
        mcp_call=lambda sid, tool, args: calls.append((sid, tool, args)) or {"ok": True, "result": "晴"},
    ))
    text = "".join(e["text"] for e in events if e["type"] == "text")
    assert "DSML" not in text and "｜" not in text
    assert text == "我查一下天气。杭州晴。"
    assert calls == [("srv", "get_weather", {"city": "杭州", "days": 3})]
    assistant = [m for m in sent[1] if m.get("role") == "assistant"][-1]
    assert assistant["tool_calls"][0]["function"]["name"] == "srv__get_weather"
    assert assistant["content"] == "我查一下天气。", "回放给模型的正文不该再带 DSML"


def test_text_marker_loop_executes_dsml_and_teaches_canonical_marker():
    replies = iter([["好,", "我先看看世界书。", _FEEDBACK_106[:40], _FEEDBACK_106[40:]], ["共 3 条。"]])
    seen_messages: list[list[dict]] = []

    class _B:
        def stream(self, system, messages, max_tokens):
            seen_messages.append([dict(m) for m in messages])
            yield from next(replies)

    calls = []
    events = list(_openai_text_marker_loop(
        _B(), "sys", [{"role": "user", "content": "看看世界书"}],
        [{"server_id": "dispatcher", "name": "list_worldbook_entries",
          "schema": {"properties": {"script_id": {"type": "integer"}}}}],
        3, 256,
        lambda sid, tool, args: calls.append((sid, tool, args)) or {"ok": True, "result": "3 条"},
    ))
    text = "".join(e["text"] for e in events if e["type"] == "text")
    assert "DSML" not in text and "｜" not in text
    assert "我先看看世界书。" in text and "共 3 条。" in text
    assert calls == [("dispatcher", "list_worldbook_entries", {"script_id": 5})]
    replay = [m for m in seen_messages[1] if m["role"] == "assistant"][-1]["content"]
    assert "<<TOOL_CALL>>" in replay and "DSML" not in replay
    payload = json.loads(replay.split("<<TOOL_CALL>>", 1)[1].split("<<END_TOOL_CALL>>", 1)[0])
    assert payload == {"server_id": "dispatcher", "tool": "list_worldbook_entries", "arguments": {"script_id": 5}}


# ── 三、工具清单自带格式 ───────────────────────────────────────────────────────
def test_tool_list_carries_call_format():
    out = _format_tools_for_prompt([{"server_id": "dispatcher", "name": "list_worldbook_entries"}])
    assert "【Tool call format】" in out
    assert '"server_id"' in out and '"arguments"' in out and "<<END_TOOL_CALL>>" in out
    assert "DSML" in out  # 明确告诉模型别用它原生那套
