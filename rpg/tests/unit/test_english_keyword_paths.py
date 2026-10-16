"""English support for the deterministic (no-LLM) keyword paths:
episodic recall, the retrieval LIKE path, movement/combat intent parsing, time-confirm guard."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kb.en_terms import english_stem, english_term_set, english_terms  # noqa: E402
from kb.episodic import (  # noqa: E402
    _excerpt_around_match,
    _query_grams,
    _score_events,
    merge_and_rank,
)


def _ev(i, summary, location="", participants=None):
    return {"id": i, "summary": summary, "location": location,
            "participants": participants or []}


_EN_EVENTS = [
    _ev(1, "You asked the cloaked merchant in Dawnbrook about the crest; he mentioned the old ferryman.",
        "Dawnbrook", ["cloaked merchant"]),
    _ev(2, "You helped Henriette carry firewood and accidentally showed inhuman strength.",
        "Dawnbrook", ["Henriette"]),
    _ev(3, "In the middle of the swamp you pulled a black metal artifact from the roots of a crooked willow.",
        "Swamp", []),
    _ev(4, "You partnered with Conrad, who laid down three conditions.", "Stonebridge Ford", ["Conrad"]),
    _ev(5, "Scouting the swamp at night, you disturbed something huge beneath the water.", "Swamp", []),
]


# ── tokenisation ─────────────────────────────────────────────────────

def test_english_stem_plurals_and_possessives():
    assert english_stem("Swords") == "sword"
    assert english_stem("Conrad's") == "conrad"
    assert english_stem("ladies") == "lady"
    assert english_stem("boxes") == "box"
    assert english_stem("glass") == "glass"


def test_english_terms_drop_stopwords_and_flag_proper_nouns():
    t = english_terms("Will Henriette remember what I did for her?")
    assert "henriette" in t and t["henriette"] is True
    assert "what" not in t and "her" not in t and "remember" not in t
    # sentence-initial capital is not a proper-noun signal
    assert english_terms("Firewood was heavy.")["firewood"] is False


def test_query_grams_include_english_and_keep_cjk():
    g = _query_grams("Where is Conrad? 康拉德在哪")
    assert "conrad" in g and "康拉德" in g
    assert _query_grams("ok go!") == set()


def test_corpus_term_set_is_case_insensitive():
    assert {"conrad", "condition"} <= english_term_set("Conrad laid down CONDITIONS")


# ── episodic scoring ─────────────────────────────────────────────────

def test_english_proper_noun_recalls_event():
    scored = _score_events("Does Henriette still trust me?", _EN_EVENTS)
    assert scored and scored[0][1]["id"] == 2


def test_english_lone_common_word_does_not_recall():
    # a single lowercase common word (weight 2) is below the floor, like a lone CJK bigram
    assert _score_events("firewood", _EN_EVENTS) == []


def test_english_two_rare_words_recall():
    scored = _score_events("that crooked willow artifact", _EN_EVENTS)
    assert scored and scored[0][1]["id"] == 3


def test_english_matching_is_whole_word_not_substring():
    events = [_ev(1, "The concatenation of runes glowed."), _ev(2, "Nothing here."),
              _ev(3, "A quiet day."), _ev(4, "Rain."), _ev(5, "Wind.")]
    assert _score_events("the Cat is hungry, cat food", events) == []


def test_english_frequent_term_filtered_by_df():
    # "swamp" appears in 2/5 -> still rare; but in a corpus where it is everywhere it is dropped
    events = [_ev(i, f"Day {i} in the swamp with Marla") for i in range(1, 9)]
    assert _score_events("The swamp and Marla", events) == []


def test_english_excerpt_anchors_on_word():
    text = ("x " * 300) + "Then Fiona handed you the silver pocket watch. " + ("y " * 300)
    ex = _excerpt_around_match(text, "Fiona's silver watch", window=40)
    assert "Fiona" in ex and ex.startswith("…")


def test_merge_and_rank_history_english():
    history = [{"role": "user", "content": "I give Bartholomew the brass key."},
               {"role": "assistant", "content": "Bartholomew pockets the brass key with a nod."}]
    history += [{"role": "user", "content": f"filler {i}"} for i in range(14)]
    out = merge_and_rank("Where did the key go? Ask Bartholomew.", [], history, k=2)
    assert out and out[0]["kind"] == "history" and "Bartholomew" in out[0]["text"]


# ── retrieval LIKE path ──────────────────────────────────────────────

def test_retrieval_keyword_tokens_english_and_cjk():
    from retrieval.sources import _keyword_score, _keyword_tokens
    toks = _keyword_tokens("What did Conrad say about the swords? 康拉德")
    assert {"conrad", "sword", "康拉德", "康拉"} <= toks
    assert "the" not in toks and "what" not in toks
    assert _keyword_score(toks, "CONRAD drew two swords.") == 2
    assert _keyword_score(toks, "concatenated swordfish") == 0


# ── movement / combat intent ─────────────────────────────────────────

def test_english_movement_intent():
    from rules_bridge.intent import _has_movement_intent
    assert _has_movement_intent("I head north along the rusted rails")
    assert _has_movement_intent("I sneak into the main shaft")
    assert not _has_movement_intent("I listen carefully at the door")
    assert _has_movement_intent("沿外侧锈轨往东")


def test_english_direction_to_exit():
    from rules_bridge.intent import _direction_to_exit
    room = {"exits": [
        {"to": "main_shaft", "label": "Main shaft (down)"},
        {"to": "outer_track", "label": "Outer rusted track, east"},
    ]}
    assert _direction_to_exit("I follow the rusted track", room) == "outer_track"
    assert _direction_to_exit("I head east", room) == "outer_track"
    assert _direction_to_exit("I climb down into the shaft", room) == "main_shaft"
    assert _direction_to_exit("I wait here", room) is None
    cn_room = {"exits": [{"to": "outer", "label": "外侧锈轨(东)"}]}
    assert _direction_to_exit("沿外侧锈轨往东", cn_room) == "outer"


def _module_state(*, encounter_active=False, enemies=None):
    class _S:
        pass
    s = _S()
    s.data = {
        "scene": {"module_id": "m", "current_room": {"enemies": []}},
        "encounter": {"active": encounter_active,
                      "combatants": [dict(e, side="enemy") for e in (enemies or [])]},
    }
    return s


def test_english_combat_intent_gates():
    from rules_bridge import classify_combat_intent
    block = classify_combat_intent("I draw my sword and attack", _module_state())
    assert block and block["kind"] == "no_target_combat"
    s = _module_state(encounter_active=True, enemies=[{"id": "g", "name": "Goblin"}])
    block = classify_combat_intent("I back away and keep shooting my bow", s)
    assert block and block["kind"] == "combat_pending_question"
    assert "Goblin" in block["question"]
    assert classify_combat_intent("I disengage and step back", s) is None
    assert classify_combat_intent("I light a fire and look around", _module_state()) is None


def test_english_suggest_move_and_skill():
    from rules_bridge.suggest import suggest_rule_actions
    s = _module_state()
    s.data["scene"] = {"current_room": {"exits": [{"to": "crypt", "label": "Crypt stairs (down)"}]},
                       "location_id": "hall"}
    acts = suggest_rule_actions("I sneak down the stairs toward the crypt", s)
    kinds = {(a["kind"], a.get("skill")) for a in acts}
    assert ("skill_check", "stealth") in kinds
    assert any(a["kind"] == "move" and a["to"] == "crypt" for a in acts)


# ── time confirm guard ───────────────────────────────────────────────

def test_english_time_confirm_signals():
    from state.time_ops import _gm_is_asking_for_time_confirm
    assert _gm_is_asking_for_time_confirm("Do you want to skip ahead to the festival? Please confirm.", [])
    assert _gm_is_asking_for_time_confirm("", ["Time jump confirm: pending"])
    assert not _gm_is_asking_for_time_confirm("The sun sets over the harbour.", [])


# ── /set English directives ──────────────────────────────────────────

def test_english_set_location_and_time_extraction():
    from state.extractors import _extract_location_override, _extract_set_time_targets
    assert _extract_location_override("location = The Rusty Anchor tavern") == "The Rusty Anchor tavern"
    assert _extract_location_override("current location: north gate") == "north gate"
    assert _extract_location_override("当前位置改为北港") == "北港"
    assert _extract_set_time_targets("set the time to the next morning") == ["the next morning"]
    assert _extract_set_time_targets("it is time for bed") == []
    assert _extract_set_time_targets("时间改为三日后的子夜") == ["三日后的子夜"]


def test_english_path_aliases():
    from state.path_ops import _clean_path
    assert _clean_path("Location") == "player.current_location"
    assert _clean_path("current objective") == "memory.current_objective"
    assert _clean_path("位置") == "player.current_location"
    assert _clean_path("player.name") == "player.name"
