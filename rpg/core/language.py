"""core.language — output-language single source of truth for every LLM prompt.

Resolution order for the language the models should write in:
    user preference `narration_language`  >  env `RPG_NARRATION_LANGUAGE`  >  "en"

The directive returned by `language_directive()` is appended deterministically to the
GM / tavern system prompt and to every structured agent call (`agents._harness.call_agent_json`),
so the output language never depends on a prompt "remembering" it.
"""
from __future__ import annotations

import os

DEFAULT_LANGUAGE = "en"

# code -> English display name used inside prompts
_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "zh-CN": "Simplified Chinese",
}

_ALIASES: dict[str, str] = {
    "en": "en", "en-us": "en", "en-gb": "en", "english": "en",
    "zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN", "chinese": "zh-CN",
}

PREF_KEY = "narration_language"


def normalize_language(code: object) -> str | None:
    """Map a loose language code to a supported one; unknown → None."""
    if not isinstance(code, str):
        return None
    return _ALIASES.get(code.strip().lower())


def default_language() -> str:
    return normalize_language(os.environ.get("RPG_NARRATION_LANGUAGE", "")) or DEFAULT_LANGUAGE


def narration_language(user_id: int | None = None) -> str:
    """Language the models should write in for this user. Never raises."""
    if user_id is not None:
        try:
            from core.request_cache import get_user_prefs_cached
            lang = normalize_language(get_user_prefs_cached(int(user_id)).get(PREF_KEY))
            if lang:
                return lang
        except Exception:
            pass
    return default_language()


def language_name(code: str | None) -> str:
    return _LANGUAGE_NAMES.get(normalize_language(code) or DEFAULT_LANGUAGE, "English")


def language_directive(user_id: int | None = None) -> str:
    """Top-priority output-language block for narrative (GM / tavern) system prompts."""
    name = language_name(narration_language(user_id))
    return (
        "\n\n# Output language (highest priority)\n"
        f"Write ALL narration, dialogue, descriptions, questions and any other prose in {name}, "
        "for the whole session, regardless of the language of these instructions, the retrieved "
        "source text, character cards or worldbook entries. Keep proper nouns exactly as they "
        "appear in the source material. A character may utter a single foreign line when the "
        f"story calls for it, but the narrative itself stays in {name}.\n"
    )


def agent_language_directive(user_id: int | None = None) -> str:
    """Output-language line for structured (JSON) agent micro-tasks."""
    name = language_name(narration_language(user_id))
    return (
        "\n\nOutput language: write every free-text value (names you invent, labels, summaries, "
        f"descriptions, reasons) in {name}. Keep JSON keys, enum values, ids and quoted source "
        "text exactly as specified or as they appear in the input."
    )
