"""kb/section_markers.py — context section headers that code (not just the model) looks up.

Single source for markers that are produced in one module and split/matched in another.
The legacy Chinese forms are kept so text rendered before the English switch (caches, logs
replayed in tests, old saves) is still recognised.
"""
from __future__ import annotations

# "Worldline convergence · upcoming anchors" block: produced by retrieval/assemble.py,
# split out by context_engine.core._split_anchor_pending, re-attached by kb/recall.py.
ANCHOR_PENDING_MARKER = "=== Worldline Convergence · Upcoming Anchors ==="
LEGACY_ANCHOR_PENDING_MARKER = "=== 世界线收束·接下来的锚点 ==="
ANCHOR_PENDING_MARKERS = (ANCHOR_PENDING_MARKER, LEGACY_ANCHOR_PENDING_MARKER)


# ── "first appearance" anchor summaries ──────────────────────────────────────
# Produced by platform_app/import_pipeline/stages_core.py (entity -> intro event text),
# consumed by agents/anchor_seed_agent.py (intro dedup), gm_serving/anchor_reconcile.py
# (deterministic arrival) and context_providers/novel.py (pending NPC names).
# Old chapter_facts / save_anchor_states rows hold the Chinese forms; every matcher accepts both.
import re as _re

INTRO_MARKERS = ("首次登场", "首次引入", "首次出现", "first appears", "first introduced")
SCENE_PREFIXES = ("场景", "Scene ")
_QUOTED_RE = _re.compile(r"[「『\"“]([^」』\"”]+)[」』\"”]")


def format_intro_event(name: str, etype: str) -> str:
    """English intro-event text for an entity first revealed in a chapter."""
    if etype == "character":
        return f"{name} (character) first appears"
    if etype == "location":
        return f'Scene "{name}" first appears'
    if etype in ("concept", "item", "faction"):
        return f'{etype} "{name}" first introduced'
    return f"{name} first appears"


def is_intro_summary(summary: str) -> bool:
    s = summary or ""
    return any(mk in s for mk in INTRO_MARKERS)


def is_scene_intro(summary: str) -> bool:
    return (summary or "").lstrip().startswith(SCENE_PREFIXES)


def intro_subject(summary: str) -> str | None:
    """Subject name of an intro summary (title part before any ':' hint), or None.

    Accepts: concept「X」首次引入 / item "X" first introduced / Scene "X" first appears /
    场景X首次出现 / X(character)首次登场 / X (character) first appears / X first appears."""
    s = (summary or "").split(":", 1)[0].split("：", 1)[0].strip()
    m = _QUOTED_RE.search(s)
    if m:
        return m.group(1).strip()
    m = _re.match(r"^场景(.+?)首次", s) or _re.match(r"^Scene\s+(.+?)\s+first\b", s)
    if m:
        return m.group(1).strip()
    m = _re.match(r"^(.+?)\s*[（(]", s)
    if m:
        return m.group(1).strip()
    m = _re.match(r"^(.+?)\s*(?:首次|first (?:appears|introduced))", s)
    return m.group(1).strip() if m else None


_CHARACTER_INTRO_RE = _re.compile(
    r"^([^(（]+?)\s*[（(]character[)）]\s*(?:首次登场|first appears)")


def character_intro_name(summary: str) -> str | None:
    """Name from a "X (character) first appears" / "X(character)首次登场" summary."""
    m = _CHARACTER_INTRO_RE.match(summary or "")
    return m.group(1).strip() if m else None


# must_preserve participant items: "<name> takes part" (legacy "<name> 参与").
def format_participant(name: str) -> str:
    return f"{name} takes part"


_PARTICIPANT_RE = _re.compile(r"^(.+?)\s+(?:参与|takes part)")


def participant_name(item: str) -> str | None:
    m = _PARTICIPANT_RE.match(str(item or "").strip())
    return m.group(1).strip() if m else None
