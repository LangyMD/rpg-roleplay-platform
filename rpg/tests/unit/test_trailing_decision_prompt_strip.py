"""沉浸感确定性兜底:剥掉结尾旁白向玩家显式提问下一步的句子(中 / 英),绝不动台词。"""
import pytest

from chat_pipeline.persist import _is_trailing_decision_prompt, _strip_trailing_decision_prompts


@pytest.mark.parametrize("line", [
    "你接下来打算怎么做？",
    "请你做出选择。",
    "What do you do?",
    "So, what will you do next?",
    "What’s your next move?",
    "It’s your move.",
    "The choice is yours.",
    "Over to you.",
])
def test_decision_prompts_detected(line):
    assert _is_trailing_decision_prompt(line)


@pytest.mark.parametrize("line", [
    "“What do you do?” she asks.",
    '"你接下来打算怎么做？"她问。',
    "How do you feel about it, she wondered?",
    "It is your turn to speak, the herald announced.",
    "The door creaks open.",
])
def test_dialogue_and_narration_untouched(line):
    assert not _is_trailing_decision_prompt(line)


def test_strip_keeps_body_and_never_empties():
    assert _strip_trailing_decision_prompts("The rain falls.\n\nWhat do you do?") == "The rain falls."
    assert _strip_trailing_decision_prompts("What do you do?") == "What do you do?"
