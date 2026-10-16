"""chapter_fact_indexer deterministic pass on English text.

Spaces are word boundaries in Latin text: sentence cleaning / evidence must not delete them,
sentence splitting must use ". " boundaries, and story_time_label must strip English
chapter prefixes. Sample text is original filler, not from any novel.
"""
from __future__ import annotations

from chapter_fact_indexer import (
    _clean_sentence,
    _evidence,
    _extract_events,
    _good_summary_lead,
    _good_title,
    _sentence_truncate,
    _sentences,
    _story_time_label,
    _summary_from_events,
)

_TEXT = (
    "The storm broke over the hills at night and nobody slept. "
    "\"Run to the mill!\" Mara shouted to everyone near the gate. "
    "Mr. Harrow discovered the broken lock and told Mara about the stranger.\n\n"
    "By morning the road was gone."
)


def test_sentences_keep_spaces_and_split_on_periods():
    sents = _sentences(_TEXT)
    assert "The storm broke over the hills at night and nobody slept." in sents
    assert "Mara shouted to everyone near the gate." in sents
    # honorific abbreviations are not sentence ends
    assert any(s.startswith("Mr. Harrow discovered") for s in sents)
    assert all("  " not in s and " " in s for s in sents)


def test_clean_sentence_and_evidence_keep_word_boundaries():
    assert _clean_sentence("  The   old\nmill  ") == "The old mill"
    assert _clean_sentence("她 转身 说道。") == "她转身说道。"  # CJK unchanged
    ev = _evidence(_TEXT, "Harrow")
    assert "Harrow discovered the broken lock" in ev


def test_english_events_scored():
    sents = _sentences(_TEXT)
    events = _extract_events(sents, [_TEXT], {"Mara": "Mara", "Mr. Harrow": "Mr. Harrow"}, [], [])
    assert events and "discovered" in events[0]["event"]
    assert events[0]["participants"] == ["Mara", "Mr. Harrow"]


def test_truncate_on_english_sentence_or_word_boundary():
    long = "The road ran north past the mill. " * 12
    out = _sentence_truncate(long, cap=120)
    assert out.endswith("mill.") and len(out) <= 120
    no_period = "word " * 80
    out2 = _sentence_truncate(no_period, cap=120)
    assert not out2.endswith("wor") and out2.endswith("word")


def test_summary_join_uses_english_punctuation():
    s = _summary_from_events([{"event": "Mara ran"}, {"event": "Harrow followed."}], [])
    assert s == "Mara ran. Harrow followed."


def test_story_time_label_english():
    assert _good_title("Chapter Twelve: The Storm") == "The Storm"
    assert _good_title("CHAPTER IV") == ""
    assert _good_title("Chapter 12") == ""
    assert _good_summary_lead("Mara found the letter under the floor. Then she ran.") == \
        "Mara found the letter under the floor"
    assert _story_time_label(7, "Chapter 7", "", "") == "ch7 节点"
    assert _story_time_label(7, "Chapter Seven", "", "Mara leaves the valley at dawn.") == \
        "Mara leaves the valley at dawn"
