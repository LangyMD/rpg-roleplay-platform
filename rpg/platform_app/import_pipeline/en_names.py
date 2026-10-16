"""import_pipeline/en_names.py — 英文小说高频人名候选(确定性,零 LLM)。

中文路径(stages_core._stage_entities)靠 2-3 字 n-gram;英文书走这里:
  · 候选 = 大写开头的专名序列(可带敬称前缀:Mr. Darcy / Lady Catherine de Bourgh);
  · 句首大写词有歧义 → 单词候选只认「句中大写出现 ≥ N 次且小写形式少见」的词;
  · 停用词表挡掉 I / The / Chapter / 星期月份 / 国籍形容词等;
  · 敬称形归一(Mr → Mr.),所有格 's 剥掉;
  · 单独出现的名(Darcy)若唯一归属某个多词候选(Mr. Darcy 远多于 Fitzwilliam Darcy)→ 计数并入,
    归属不唯一(Bennet ∈ Mr./Mrs./Jane Bennet)→ 丢掉(宁漏勿误,不合并异人)。
输出与中文路径同形:[{"name", "count"}],按次数降序。最终是否人名由 _stage_cards 的 LLM 判定。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

HONORIFICS: tuple[str, ...] = (
    "Mr", "Mrs", "Ms", "Miss", "Mx", "Dr", "Sir", "Dame", "Lady", "Lord", "Madam", "Madame",
    "Mme", "Mlle", "Monsieur", "Mademoiselle", "Master", "Mistress", "Captain", "Capt",
    "Colonel", "Col", "General", "Gen", "Major", "Lieutenant", "Lt", "Sergeant", "Sgt",
    "Admiral", "Commander", "Professor", "Prof", "Father", "Brother", "Sister", "Mother",
    "Aunt", "Uncle", "King", "Queen", "Prince", "Princess", "Duke", "Duchess", "Count",
    "Countess", "Baron", "Baroness", "Earl", "Saint", "St", "Reverend", "Rev", "Inspector",
    "Detective", "Officer", "Doctor", "Senator", "President", "Emperor", "Empress",
)
# 带点缩写的规范形(Mr → Mr.)
_ABBREV = {"Mr", "Mrs", "Ms", "Mx", "Dr", "Capt", "Col", "Gen", "Lt", "Sgt", "Prof", "St",
           "Rev", "Mme", "Mlle"}

# 名字中间允许的小写连接词(de Bourgh / van Helsing / bin Laden)
_PARTICLES = ("de", "van", "von", "der", "den", "du", "da", "di", "del", "della", "le", "la",
              "al", "bin", "ibn", "y", "zu", "ter")

STOPWORDS: frozenset[str] = frozenset({
    # pronouns / determiners / function words
    "I", "Me", "My", "Mine", "Myself", "We", "Us", "Our", "Ours", "You", "Your", "Yours", "He",
    "Him", "His", "Himself", "She", "Her", "Hers", "Herself", "It", "Its", "Itself", "They",
    "Them", "Their", "Theirs", "The", "A", "An", "This", "That", "These", "Those", "There",
    "Here", "Then", "Than", "Thus", "So", "And", "But", "Or", "Nor", "For", "Yet", "If",
    "When", "While", "Where", "Why", "How", "What", "Which", "Who", "Whom", "Whose",
    "Whatever", "Whoever", "Because", "Although", "Though", "As", "At", "By", "In", "On",
    "Of", "Off", "Out", "Up", "Down", "To", "Into", "Onto", "From", "With", "Without",
    "Within", "About", "Above", "After", "Again", "Against", "All", "Almost", "Also",
    "Always", "Am", "Among", "Any", "Anyone", "Anything", "Are", "Be", "Been", "Before",
    "Being", "Below", "Between", "Both", "Can", "Could", "Did", "Do", "Does", "Done",
    "Each", "Either", "Else", "Even", "Ever", "Every", "Everyone", "Everything", "Few",
    "First", "Last", "Next", "Had", "Has", "Have", "Having", "Is", "Was", "Were", "Will",
    "Would", "Shall", "Should", "May", "Might", "Must", "Just", "Still", "Only", "Not",
    "No", "Yes", "Yeah", "Oh", "Ah", "Ahh", "Aye", "Nay", "Hey", "Hello", "Hi", "Well",
    "Now", "Once", "One", "Two", "Three", "Ten", "Some", "Someone", "Something", "Such",
    "Very", "Too", "Perhaps", "Maybe", "Indeed", "Never", "Nothing", "Nobody", "None",
    "Please", "Thank", "Thanks", "Sorry", "Okay", "Ok", "Good", "Great", "Dear", "Poor",
    "Let", "Look", "See", "Come", "Go", "Get", "Got", "Said", "Says", "Say", "Tell", "Told",
    "Like", "Yet", "Upon", "Over", "Under", "Through", "Since", "Until", "Till", "Whether",
    "Instead", "However", "Meanwhile", "Besides", "Still", "Soon", "Later", "Today",
    "Tonight", "Tomorrow", "Yesterday", "Morning", "Evening", "Night", "Day",
    # book structure
    "Chapter", "Chapters", "Part", "Book", "Volume", "Vol", "Prologue", "Epilogue",
    "Interlude", "Section", "Act", "Scene", "Appendix", "Contents", "Preface", "Foreword",
    "Introduction", "Afterword", "Author", "Note", "End", "Fin", "Copyright",
    # titles alone (as a bare word they are not a name)
    "Mr", "Mrs", "Ms", "Miss", "Dr", "Sir", "Madam", "Lord", "Lady", "Master", "Captain",
    "King", "Queen", "Prince", "Princess", "God", "Lord's", "Heaven", "Hell",
    # days / months / seasons
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "June", "July", "August", "September",
    "October", "November", "December", "Spring", "Summer", "Autumn", "Fall", "Winter",
    "Christmas", "Easter",
    # nationalities / languages (always capitalized, never a character)
    "English", "British", "French", "German", "Spanish", "Italian", "Russian", "American",
    "Chinese", "Japanese", "Korean", "Irish", "Scottish", "Scots", "Welsh", "Dutch",
    "Greek", "Roman", "Latin", "Indian", "African", "European", "Asian", "Christian",
    "Catholic", "Protestant", "Jewish", "Muslim", "Englishman", "Frenchman",
})
_STOP_LOWER = frozenset(w.lower() for w in STOPWORDS)

_WORD = r"[A-Z][A-Za-z'’\-]*[a-z][A-Za-z'’\-]*"
_HON = r"(?:" + "|".join(sorted(HONORIFICS, key=len, reverse=True)) + r")\.?"
_SEQ_RE = re.compile(
    r"(?<![A-Za-z'’\-])"
    r"(?:(?P<hon>" + _HON + r")\s+)?"
    r"(?P<body>" + _WORD + r"(?:\s+(?:(?:" + "|".join(_PARTICLES) + r")\s+)?" + _WORD + r")*)"
)
_LOWER_WORD_RE = re.compile(r"(?<![A-Za-z])[a-z][a-z'’\-]*")
# 句首判定:前一个非空白字符是句末标点 / 开引号 / 换行 / 文首
_SENT_BREAK = set('.!?"“”‘\'\n:;—([…*_#')


def _is_sentence_initial(text: str, pos: int) -> bool:
    i = pos - 1
    while i >= 0 and text[i] in " \t\r":
        i -= 1
    if i < 0:
        return True
    return text[i] in _SENT_BREAK


def _norm_hon(h: str) -> str:
    h = h.rstrip(".")
    return h + "." if h in _ABBREV else h


def _strip_possessive(s: str) -> str:
    return re.sub(r"['’]s?$", "", s)


def english_name_candidates(text: str, *, min_count: int = 3, limit: int = 60,
                            existing_names: set[str] | None = None) -> list[dict[str, Any]]:
    """英文正文 → 高频专名候选 [{"name","count"}],按次数降序,最多 limit 个。"""
    if not text:
        return []
    lower_counts: Counter[str] = Counter(m.group(0) for m in _LOWER_WORD_RE.finditer(text))
    all_counts: Counter[str] = Counter()
    mid_counts: Counter[str] = Counter()
    honorific_forms: set[str] = set()

    for m in _SEQ_RE.finditer(text):
        hon = m.group("hon")
        words = m.group("body").split()
        start = m.start()
        initial = _is_sentence_initial(text, start)
        if hon is None:
            # 剥掉开头的停用词("The Netherfield" / "Then Elizabeth")
            while words and words[0] in STOPWORDS:
                words = words[1:]
                initial = False  # 剥掉之后剩下的部分不在句首
            if not words:
                continue
        words = [w for w in words]
        words[-1] = _strip_possessive(words[-1])
        if not words[-1] or words[-1][0].islower():
            continue
        # 去掉结尾停用词("Elizabeth Then" 不会出现,但 "Darcy I" 之类的残片要防)
        while words and words[-1] in STOPWORDS:
            words = words[:-1]
        if not words:
            continue
        body = " ".join(words)
        if hon is not None:
            hn = _norm_hon(hon)
            # "Miss Bennet" 里的 Miss 是敬称;但单独的 "Lord" 已在停用词里
            name = f"{hn} {body}"
            honorific_forms.add(name)
            all_counts[name] += 1
            mid_counts[name] += 1  # 敬称打头必是专名,句首也算
            continue
        all_counts[body] += 1
        if not initial:
            mid_counts[body] += 1

    accepted: dict[str, int] = {}
    for name, cnt in all_counts.items():
        if cnt < min_count:
            continue
        words = name.split()
        if name in honorific_forms:
            accepted[name] = cnt
            continue
        if len(words) == 1:
            w = words[0]
            if w in STOPWORDS or w.lower() in _STOP_LOWER:
                continue
            mid = mid_counts.get(name, 0)
            # 句中大写至少 2 次,且小写形式不比句中大写形式常见(will / hope / rose 这类常用词出局)
            if mid < 2 or lower_counts.get(w.lower(), 0) > mid:
                continue
            accepted[name] = cnt
        else:
            if any(w.lower() in _STOP_LOWER for w in words if w not in _PARTICLES):
                continue
            if mid_counts.get(name, 0) < 1:
                continue
            accepted[name] = cnt

    # 单词名并入唯一归属的多词候选(Darcy → Mr. Darcy);归属不唯一则丢弃(Bennet)
    multi = [n for n in accepted if len(n.split()) >= 2]
    for name in [n for n in list(accepted) if len(n.split()) == 1]:
        owners = [m for m in multi if name in m.split()]
        if not owners:
            continue
        owners.sort(key=lambda m: -accepted[m])
        top = owners[0]
        second = accepted[owners[1]] if len(owners) > 1 else 0
        # 唯一明显归属:最强候选 ≥ 2x 次强;且该单词不是多个敬称形的共同姓氏
        hon_owners = [m for m in owners if m in honorific_forms]
        if accepted[top] >= 2 * second and len(hon_owners) <= 1:
            accepted[top] += accepted.pop(name)
        elif len(owners) >= 2:
            accepted.pop(name)

    # 敬称形与无敬称多词形指同一人时(Lady Catherine de Bourgh / Catherine de Bourgh)保留敬称形
    for name in list(accepted):
        if name in honorific_forms:
            bare = name.split(" ", 1)[1]
            if bare in accepted and len(bare.split()) >= 2:
                accepted[name] += accepted.pop(bare)

    out = [{"name": n, "count": c} for n, c in accepted.items()]
    out.sort(key=lambda x: (-x["count"], x["name"]))
    out = out[:limit]
    for n in (existing_names or set()):
        if n and not any(x["name"] == n for x in out):
            out.append({"name": n, "count": text.count(n)})
    return out
