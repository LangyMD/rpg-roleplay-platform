"""kb.section_markers intro helpers: the English producer format and the legacy Chinese
rows (old chapter_facts / save_anchor_states) must both be recognised by every consumer."""
from __future__ import annotations

from kb.section_markers import (
    character_intro_name,
    format_intro_event,
    format_participant,
    intro_subject,
    is_intro_summary,
    is_scene_intro,
    participant_name,
)


def test_english_producer_round_trips():
    for etype, name in (("character", "Alice Grey"), ("location", "Akiba Shelter"),
                        ("item", "D20"), ("concept", "Pale Blood"), ("faction", "The Order"),
                        ("other", "Thing")):
        text = format_intro_event(name, etype) + ": some hint"
        assert is_intro_summary(text)
        assert intro_subject(text) == name
        assert is_scene_intro(text) == (etype == "location")
    assert character_intro_name(format_intro_event("Alice Grey", "character")) == "Alice Grey"
    assert character_intro_name(format_intro_event("Akiba", "location")) is None


def test_legacy_chinese_rows_still_match():
    assert is_intro_summary("爱丽丝(character)首次登场")
    assert intro_subject("爱丽丝(character)首次登场: 提示") == "爱丽丝"
    assert intro_subject("concept「苍白之血」首次引入") == "苍白之血"
    assert intro_subject("场景秋叶原避难所首次出现") == "秋叶原避难所"
    assert is_scene_intro("场景秋叶原避难所首次出现")
    assert not is_scene_intro("爱丽丝(character)首次登场")
    assert character_intro_name("爱丽丝（character）首次登场") == "爱丽丝"
    assert not is_intro_summary("将军战死沙场")


def test_participant_items_both_forms():
    assert format_participant("Alice") == "Alice takes part"
    assert participant_name("Alice Grey takes part") == "Alice Grey"
    assert participant_name("蕾穆丽娜 参与") == "蕾穆丽娜"
    assert participant_name("the outcome: killed") is None
