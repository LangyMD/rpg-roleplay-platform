"""English novel import: _stage_entities must find proper-noun name candidates.

The Chinese path only takes 2-3 CJK char n-grams, so an English book used to get zero
NPC cards. en_names.english_name_candidates is the deterministic English path.
The sample text below is original (written for this test), not taken from any novel.
"""
from __future__ import annotations

from platform_app.import_pipeline.en_names import english_name_candidates

_PARA = (
    "Chapter One\n\n"
    "The rain had not stopped for three days when Mr. Harrow came to Ashgrove. "
    "He stood at the gate while Clara Venn watched him from the window. "
    "\"Will he stay?\" asked her sister. Clara did not answer. "
    "Later that evening Mr. Harrow spoke with Captain Oduya about the road to Kestrel Bay. "
    "Clara thought Harrow looked tired, and Captain Oduya agreed. "
    "On Monday the whole of Ashgrove talked about Mr. Harrow, and Mrs. Venn sent a note. "
    "Mr. Venn laughed at his wife. The weather was grey. Then Clara walked to the village. "
    "She will hope for better days, she told Tobin, who only shrugged. "
    "Tobin was the miller's boy, and Tobin knew every path near Ashgrove. "
    "In August the English soldiers marched past, and Clara Venn waved.\n\n"
)
SAMPLE = _PARA * 4


def _names(text=SAMPLE, **kw):
    return {c["name"]: c["count"] for c in english_name_candidates(text, **kw)}


def test_finds_people_and_merges_honorifics():
    names = _names()
    assert "Mr. Harrow" in names
    assert "Captain Oduya" in names
    assert "Clara Venn" in names or "Clara" in names
    assert "Tobin" in names
    # bare surname folds into its unique honorific form
    assert "Harrow" not in names
    assert names["Mr. Harrow"] >= 4 * 4


def test_filters_stopwords_sentence_initial_words_and_common_words():
    names = _names()
    for junk in ("The", "He", "She", "Chapter", "One", "Monday", "August", "English",
                 "Then", "Later", "Will", "In", "On"):
        assert junk not in names, junk


def test_ambiguous_shared_surname_is_not_merged():
    # Venn belongs to Clara Venn, Mrs. Venn and Mr. Venn -> must not be folded into one of them
    names = _names()
    assert "Venn" not in names
    assert "Mrs. Venn" in names and "Mr. Venn" in names


def test_min_count_and_limit():
    assert _names(_PARA, min_count=50) == {}
    out = english_name_candidates(SAMPLE, limit=2)
    assert len(out) == 2
    assert out[0]["count"] >= out[1]["count"]


def test_existing_names_are_kept():
    names = _names(existing_names={"Old Pell"})
    assert "Old Pell" in names


def test_empty_text():
    assert english_name_candidates("") == []


# ── pipeline wiring: _stage_entities picks the English path, _stage_cards writes cards ──
from unittest import mock  # noqa: E402

from platform_app.import_pipeline import stages_core, stages_llm  # noqa: E402
from platform_app.import_pipeline.control import JobController  # noqa: E402


class _Ctl(JobController):
    def __init__(self):
        super().__init__("job-en")

    def update(self, **fields):
        pass

    def is_cancelled(self):
        return False

    def add_usage(self, *a, **k):
        pass


def _fake_connect(rows):
    cur = mock.MagicMock()
    cur.execute.return_value.fetchall.return_value = rows
    cur.execute.return_value.fetchone.return_value = {"id": 7}
    cm = mock.MagicMock()
    cm.__enter__.return_value = cur
    return mock.MagicMock(return_value=cm)


def test_stage_entities_uses_english_path_and_cards_are_written():
    rows = [{"content": SAMPLE, "name": "x", "aliases": [], "chapter_index": 1,
             "chapter": 1, "summary": "", "characters": []}]
    with mock.patch.object(stages_core, "connect", _fake_connect(rows)):
        ents = stages_core._stage_entities(_Ctl(), 12, 1)
    got = {e["name"] for e in ents}
    assert {"Mr. Harrow", "Captain Oduya", "Tobin"} <= got

    written = []

    def _call(api, model, system, prompt, *a, **k):
        assert "actual character" in prompt
        head = prompt.split("\n", 1)[0]
        if "Ashgrove" in head or "Bay" in head:
            return '{"is_character": false}', {"input_tokens": 1, "output_tokens": 1}
        return '{"is_character": true, "identity": "a villager"}', {"input_tokens": 1, "output_tokens": 1}

    with mock.patch.object(stages_llm, "connect", _fake_connect(rows)), \
         mock.patch.object(stages_llm, "_resolve_extractor_llm", return_value=("relay", "m")), \
         mock.patch("agents._harness.call_agent_json_guarded", side_effect=_call), \
         mock.patch("platform_app.usage.compute_cost", return_value=0.0), \
         mock.patch("platform_app.knowledge.upsert_character_card",
                    side_effect=lambda uid, sid, card: written.append(card["name"])):
        n = stages_llm._stage_cards(_Ctl(), 1, 12, ents)
    assert n >= 3
    assert "Mr. Harrow" in written and "Ashgrove" not in written
