"""text-marker 降级路径:工具旁白铁律注入(prompt 加固,非确定性保证)。

text-marker(Vertex / OpenAI 兼容等无 native tool_use 的 backend)易在工具调用之间
用自然语言旁白工具执行(「角色已创建」「一切就绪」),污染沉浸正文。_format_tools_for_prompt
在工具清单前加一条「正文只写故事、不解说幕后」的铁律。本测试只断言铁律确实进了 prompt。
"""
from agents.gm.helpers import _format_tools_for_prompt

_TOOLS = [
    {"server_id": "rpg", "name": "set_tavern_character", "description": "切换扮演角色",
     "schema": {"properties": {"name": {}}, "required": ["name"]}},
]


def test_no_tools_returns_empty():
    assert _format_tools_for_prompt([]) == ""


def test_tool_list_still_present():
    out = _format_tools_for_prompt(_TOOLS)
    assert "MCP tools available this turn" in out
    assert "set_tavern_character" in out


def test_no_narration_rule_injected():
    out = _format_tools_for_prompt(_TOOLS)
    # 铁律段落 + 关键反例措辞都在
    assert "prose iron rule" in out
    assert "character created" in out
    assert "all set" in out
    # 明确「不要旁白工具执行过程」的语义
    assert "never narrate" in out
