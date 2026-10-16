"""kb/en_terms.py — English keyword terms for the deterministic (no-embedder) recall paths.

The CJK recall paths slide 2/3-char n-grams over runs of Han characters; English text has
none, so before this module English queries recalled nothing. Here English is split on word
boundaries, lowercased, filtered against a small stopword list and naively de-pluralised, so
"Conrad's swords" and "conrad sword" land on the same terms.

Pure functions, zero IO. Shared by kb/episodic.py and retrieval/sources.py (single seam:
change tokenisation here, both recall paths follow).
"""
from __future__ import annotations

import re

# Letters/digits plus inner apostrophes/hyphens ("o'brien", "half-elf").
_EN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:['’-][A-Za-z0-9]+)*")
_SENTENCE_END = re.compile(r"[.!?。！？]\s*$")

MIN_TERM_LEN = 3

# Function words + narrative filler that appear in any corpus and carry no episodic signal.
EN_STOPWORDS = frozenset("""
a about above after again against all also am an and any are aren't as at be because been
before being below between both but by can can't cannot could couldn't did didn't do does
doesn't doing don't down during each else even ever every few for from further get gets got
had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him
himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself just let let's
like me might more most must mustn't my myself no nor not now of off on once only or other
ought our ours ourselves out over own same shall shan't she she'd she'll she's should shouldn't
so some such than that that's the their theirs them themselves then there there's these they
they'd they'll they're they've this those though through to too under until up upon us very
was wasn't we we'd we'll we're we've were weren't what what's when when's where where's which
while who who's whom why why's will with won't would wouldn't yes yet you you'd you'll you're
you've your yours yourself yourselves
one two thing things something anything nothing everything someone anyone everyone
say says said tell told ask asked know knew known think thought want wanted see saw seen look
looked looking go goes going went gone come came coming make made take took back still really
maybe perhaps okay ok yeah well just again already never always sometimes
time way place right left little much many lot
remember recall talk talked talking happen happened
player gm
""".split())


def english_stem(word: str) -> str:
    """Lowercase + naive possessive/plural stripping. Deliberately minimal (no -ing/-ed):
    over-stemming merges unrelated words, and recall here prefers misses over false hits."""
    w = word.lower().replace("’", "'")
    if w.endswith("'s"):
        w = w[:-2]
    elif w.endswith("'"):
        w = w[:-1]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 4 and (w.endswith("ches") or w.endswith("shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def english_terms(text: str) -> dict[str, bool]:
    """Query-side terms: {stem: looks_like_proper_noun}.

    A word counts as a proper noun when it is capitalised and not the first word of a
    sentence (sentence-initial capitals carry no signal). Stopwords and terms shorter than
    MIN_TERM_LEN are dropped."""
    out: dict[str, bool] = {}
    s = text or ""
    for m in _EN_WORD.finditer(s):
        raw = m.group(0)
        if raw.lower().replace("’", "'") in EN_STOPWORDS:
            continue
        stem = english_stem(raw)
        if len(stem) < MIN_TERM_LEN or stem in EN_STOPWORDS:
            continue
        before = s[:m.start()]
        tail = before.rstrip(" \t")
        sentence_initial = (not tail.strip()) or bool(_SENTENCE_END.search(tail)) \
            or tail.endswith(("\n", '"', "“", ":", "*"))
        proper = raw[:1].isupper() and not sentence_initial
        out[stem] = out.get(stem, False) or proper
    return out


def english_term_set(text: str) -> set[str]:
    """Corpus-side terms: every non-stopword stem in the text (used for membership tests)."""
    out: set[str] = set()
    for m in _EN_WORD.finditer(text or ""):
        stem = english_stem(m.group(0))
        if len(stem) >= MIN_TERM_LEN and stem not in EN_STOPWORDS:
            out.add(stem)
    return out


def is_english_term(term: str) -> bool:
    return bool(term) and term.isascii()


def find_english_term(text: str, term: str) -> int:
    """Character offset of the first word in `text` whose stem is `term`; -1 if none."""
    for m in _EN_WORD.finditer(text or ""):
        if english_stem(m.group(0)) == term:
            return m.start()
    return -1
