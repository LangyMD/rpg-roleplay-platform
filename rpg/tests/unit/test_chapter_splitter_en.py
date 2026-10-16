"""English chapter splitting: CHAPTER IV / Chapter One / Chapter 1: Title / Part / Prologue.

Sample prose is generated filler (not from any novel).
"""
from __future__ import annotations

import re

import pytest

from chapter_splitter import ChapterSplitter
from ingest.adaptive_split import (
    EN_HEADING_LINE,
    EN_PART_LINE,
    adaptive_split,
    extract_seq,
    parse_en_number,
)

_SENT = ("The lantern swung in the wind while the travelers argued about the road ahead, "
         "and nobody wanted to be the first to admit that they were lost. ")


def _body(n_sentences: int = 40) -> str:
    return "\n\n".join(_SENT * 4 for _ in range(n_sentences // 4))


def _book(headings: list[str]) -> str:
    return "\n\n".join(f"{h}\n\n{_body()}" for h in headings)


_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
_WORDS = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
          "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
          "Eighteen", "Nineteen", "Twenty", "Twenty-One", "Twenty-Two", "Twenty-Three"]


@pytest.mark.parametrize("line", [
    "CHAPTER IV", "Chapter IV.", "chapter xii", "Chapter One", "CHAPTER TWENTY-THREE",
    "Chapter Twenty Three", "Chapter 1: The Storm", "Chapter 7. A Letter", "Chapter 12",
    "Chapter the First", "Chapter One Hundred and Five", "Prologue", "EPILOGUE",
    "Epilogue: Ten Years Later", "# Chapter 3", "Chapter 3 - Homecoming", "Interlude",
])
def test_heading_line_matches(line):
    assert re.match(EN_HEADING_LINE, line), line


@pytest.mark.parametrize("line", [
    "Chapter one of my life was over.", "Chapter did not matter.", "Prologues are boring",
    "Part of me wanted to stay.", "The chapter ended.", "chapter mild weather",
])
def test_body_sentences_do_not_match(line):
    assert not re.match(EN_HEADING_LINE, line), line


@pytest.mark.parametrize("line", ["PART ONE", "Part II", "Book Three: The Return", "Volume 2"])
def test_part_lines(line):
    assert re.match(EN_PART_LINE, line)


@pytest.mark.parametrize("tok,val", [
    ("IV", 4), ("xii", 12), ("XLIX", 49), ("One", 1), ("twenty-three", 23),
    ("Twenty Three", 23), ("one hundred and five", 105), ("the First", 1), ("17", 17),
])
def test_parse_en_number(tok, val):
    assert parse_en_number(tok) == val


def test_extract_seq_english_titles():
    assert extract_seq("CHAPTER IV") == 4
    assert extract_seq("Chapter Twenty-Three: Night") == 23
    assert extract_seq("Chapter 9: 1999") == 9
    assert extract_seq("第十二章 风起") == 12  # Chinese unchanged


@pytest.mark.parametrize("headings", [
    [f"CHAPTER {r}" for r in _ROMAN],
    [f"Chapter {w}" for w in _WORDS],
    [f"Chapter {i}: Title Number {i}" for i in range(1, 16)],
    [f"chapter {i}" for i in range(1, 16)],
])
def test_english_book_splits_with_high_confidence(headings):
    text = _book(headings)
    chapters, report = ChapterSplitter().split_chapters_with_report(text)
    assert len(chapters) == len(headings)
    assert [c["title"] for c in chapters] == headings
    assert report["confidence"] >= 0.8, report
    # 「字数」for English = words, not characters
    assert report["average_words"] == pytest.approx(len(_body().split()), rel=0.05)


def test_english_confidence_comparable_to_numeric():
    numeric = _book([f"Chapter {i}" for i in range(1, 13)])
    roman = _book([f"CHAPTER {r}" for r in _ROMAN])
    words = _book([f"Chapter {w}" for w in _WORDS[:12]])
    sp = ChapterSplitter()
    c_num = sp.split_chapters_with_report(numeric)[1]["confidence"]
    c_rom = sp.split_chapters_with_report(roman)[1]["confidence"]
    c_wrd = sp.split_chapters_with_report(words)[1]["confidence"]
    assert abs(c_rom - c_num) <= 0.05 and abs(c_wrd - c_num) <= 0.05
    _, rep_r = adaptive_split(roman)
    _, rep_n = adaptive_split(numeric)
    assert rep_r["score_breakdown"]["seq_continuity"] == rep_n["score_breakdown"]["seq_continuity"]


def test_prologue_epilogue_and_parts():
    heads = ["Prologue"] + [f"Chapter {i}" for i in range(1, 9)] + ["Epilogue: After"]
    text = "PART ONE\n\n" + _book(heads)
    chapters, _ = ChapterSplitter().split_chapters_with_report(text)
    titles = [c["title"] for c in chapters]
    assert titles[0] == "Prologue" and titles[-1] == "Epilogue: After"
    assert "Chapter 8" in titles


def test_explicit_rule_chapter_en_is_case_insensitive():
    text = _book([f"CHAPTER {r}" for r in _ROMAN[:6]])
    chapters = ChapterSplitter().split_chapters(text, split_rule="chapter_en")
    assert [c["title"] for c in chapters] == [f"CHAPTER {r}" for r in _ROMAN[:6]]


def test_english_default_titles_are_english():
    text = ("Some front matter that is long enough to become a preface. " * 10) + "\n\n" + _book(
        [f"Chapter {i}" for i in range(1, 6)])
    chapters, report = ChapterSplitter().split_chapters_with_report(text)
    assert chapters[0]["title"] == "Preface"
    assert report["mode_label"].isascii()
