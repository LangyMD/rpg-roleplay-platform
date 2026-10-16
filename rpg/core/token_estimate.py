"""core.token_estimate — language-aware rough token estimate (single source).

CJK text runs ~1.6 chars/token, Latin-script text ~4 chars/token. Callers that need a
budget in tokens (prompt truncation, cost previews) should use these helpers instead of a
hard-coded "Chinese density" ratio, so an English novel is not under-fed by ~2.5x.
"""
from __future__ import annotations

# Chars per token for CJK ideographs / kana / hangul and for everything else.
CJK_CHARS_PER_TOKEN = 1.6
LATIN_CHARS_PER_TOKEN = 4.0


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF        # CJK unified ideographs
        or 0x3400 <= o <= 0x4DBF     # ext A
        or 0x3040 <= o <= 0x30FF     # hiragana / katakana
        or 0xAC00 <= o <= 0xD7AF     # hangul
        or 0x3000 <= o <= 0x303F     # CJK punctuation
        or 0xFF00 <= o <= 0xFFEF     # full-width forms
    )


def cjk_ratio(text: str, sample: int = 4000) -> float:
    """Fraction of non-space chars (in a leading sample) that are CJK. Empty -> 0.0."""
    if not text:
        return 0.0
    chunk = text[:sample]
    n = cjk = 0
    for ch in chunk:
        if ch.isspace():
            continue
        n += 1
        if _is_cjk(ch):
            cjk += 1
    return (cjk / n) if n else 0.0


def is_cjk_text(text: str) -> bool:
    """True when the text is predominantly CJK (>= 30% of non-space chars)."""
    return cjk_ratio(text) >= 0.3


def estimate_tokens(text: str) -> int:
    """Rough token count: CJK chars / 1.6 + other chars / 4."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return int(cjk / CJK_CHARS_PER_TOKEN + other / LATIN_CHARS_PER_TOKEN)


def chars_per_token(text: str) -> float:
    """Average chars per token for this text (falls back to the Latin ratio when empty)."""
    if not text:
        return LATIN_CHARS_PER_TOKEN
    toks = estimate_tokens(text)
    return (len(text) / toks) if toks else LATIN_CHARS_PER_TOKEN


def chars_for_tokens(text: str, max_tokens: int) -> int:
    """How many chars of *text* fit in roughly *max_tokens* tokens."""
    return max(0, int(max_tokens * chars_per_token(text)))


def cjk_chars_to_budget(text: str, cjk_chars: int) -> int:
    """Convert a char budget tuned for Chinese text into one for *text*'s language.

    Legacy code caps prompt excerpts at N chars assuming Chinese density; for Latin text the
    same token budget holds ~2.5x more chars.
    """
    return chars_for_tokens(text, int(cjk_chars / CJK_CHARS_PER_TOKEN))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Head-truncate *text* to roughly *max_tokens* tokens (no ellipsis added)."""
    if not text:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    return text[: chars_for_tokens(text, max_tokens)]


def count_words(text: str) -> int:
    """Reader-facing length: CJK chars count one each, Latin words count one each."""
    if not text:
        return 0
    import re
    cjk = sum(1 for ch in text if _is_cjk(ch) and not (0x3000 <= ord(ch) <= 0x303F or 0xFF00 <= ord(ch) <= 0xFFEF))
    latin = re.sub(r"[　-〿぀-ヿ㐀-䶿一-鿿가-힯＀-￯]", " ", text)
    words = len(re.findall(r"[A-Za-z0-9À-ɏ]+(?:['’-][A-Za-z0-9À-ɏ]+)*", latin))
    return cjk + words
