"""extract/per_chapter.py — Pass 1 逐章固定-schema 三元组提取。

discover-then-link 的 link:带 已发现词表 + 钉死纪元种子 读每章 → 固定 schema JSON。
直接修"concepts 98% 空"(关键词匹配空,LLM 强制填字段);纪元钉死 → 不再幻觉 1935。
设计 docs/design/A_extraction.md §4。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agents.provider_errors import provider_error_summary
from extract.llm import ExtractLLM, ExtractOutputUnparseable

# 每章输出 JSON schema(给模型看的契约)
# v28: entities 加 identity / background,与玩家 PC 角色卡字段对齐 → 同套 schema 渲染
# P0 大改:entities 加 subtype + parent — 解决"德军/国防军/铁人团/无忧宫/毛瑟厂"
# 全标 faction 平级问题。LLM 抽取时按下面 subtype 枚举打标 + 报告归属上级。
_SUBTYPE_HINT = """
subtype = a short natural-language label (1-4 words) for the role this entity plays in THIS story's world.
**You may invent labels**, as long as they convey the entity's functional tier. Prefer terms the text itself uses; fall back to generic words only when it has none.

Common labels per type (**not a closed enum**):
  - character: leave empty (character cards carry the finer identity/background)
  - faction: the group's FORM OF ORGANIZATION
      military/political: nation, army, corps, service branch, unit, government, parliament, agency, party
      xianxia/wuxia: sect, school, cultivation clan, elder council, martial alliance, rogue cultivators
      fantasy: kingdom, city-state, knightly order, church, cult, guild, merchant guild, mercenary company, tribe
      modern/sci-fi: company, department, studio, academy, class, club, laboratory, colony, federation
      school/workplace: academy, club, class, department, project team
      post-apocalyptic/cosmic horror: cult, heretic sect, secret society, council, institute
      cross-genre fallback: organization, group, power, family, clan, school of thought
  - location: the place's SCALE + NATURE
      region (region/country), city, town, village, landmark, building
      xianxia: grotto-heaven, blessed land, secret realm, sect, mountain gate, walled city
      fantasy: royal palace, castle, tower, camp, temple
      modern: headquarters, base, office building, district, hotel
  - concept: the concept's NATURE
      ideology, power_system (power / cultivation system), technology (tech / equipment category),
      culture (general culture / custom; **never extract a chapter scene like "character X wearing Y / holding Z"**),
      artifact_type (category of magic artifacts / relics), rule (rule / law), phenomenon (phenomenon / celestial sign)
  - item: usually leave empty (individual objects are too fine-grained; prefer concept.technology / concept.artifact_type)

**Important**: do not force a generic enum value; write the label that best fits the novel's own context. E.g.:
  - in a xianxia novel, "Twelve Sects of Sword Mountain" -> subtype="sect confederation" is better than subtype="faction"
  - in a school story, "Starsea Festival Executive Committee" -> subtype="club committee" is better than "agency"
"""
_PARENT_HINT = """
parent field: the name of the higher-level entity this one belongs to (only as revealed in this chapter):
  - Iron Regiment.parent = "German Army" or "Wehrmacht" (if the text shows that relation)
  - German Army.parent = "Germany"
  - Sanssouci Palace.parent = "Germany" (the German president's residence)
  - Mauser Works.parent = "Germany"
  - 22nd Army.parent = "Sino-American Republic"
**Fill it only when the affiliation is explicit in this chapter; never invent one.** No parent revealed in this chapter -> leave empty.
"""
_SCHEMA_HINT = """{
  "chapter_summary": "The chapter's main thread in 1-3 sentences (about 20-100 words): core conflict / turning point / who did what. Never copy the source text, never pile up details.",
  "story_time": {"label": "a phrase naming this chapter's explicit point in story time (e.g. 'three years later', 'deep winter', 'day three of the battle'); **if the chapter has no explicit time marker (pure scene progression / character introduction) this MUST be an empty string; never put a chapter title, plot description or vague word here as a time**", "relative_marker": "timing cue relative to the previous chapter", "era": "<era; copy the given era verbatim, never rewrite it>"},
  "entities": [{
    "surface": "how the text refers to it",
    "full_name": "the most complete formal name (Western names = full given name + surname, e.g. Mulelia Zazbarum; fill it if known from the text, otherwise same as surface)",
    "canonical_guess": "canonical name (prefer matching a known entity)",
    "aliases_in_chapter": ["other PROPER names for this entity in this chapter: nickname / partial name / epithet / transliteration / honorific with a name (e.g. ['Mulelia', 'Lizzy', 'Miss Bennet']); **never** include bare generic references (that man / the old man / the girl / that guy) or bare relationship words (sister / girlfriend / husband / the other one) -- those are not names and would pollute the aliases"],
    "identity": "<=25 words: identity / position / allegiance (e.g. head of the Northern Hive / inquisitor of the Heresy Tribunal / second son of the Lin family; leave empty for non-character types)",
    "background": "<=80 words: backstory visible in this chapter (key past events before this entity appears, or current situation / origin / motive; only what this chapter states or clearly implies, never invent; leave empty for non-character types)",
    "type": "character|faction|organization|location|item|concept",
    "subtype": "<chosen per type, see SUBTYPE_HINT below; empty for character>",
    "parent": "<name of the higher-level entity this belongs to; empty if this chapter reveals none; see PARENT_HINT>",
    "status": "linked|proposed",
    "evidence": "<=20 words; preferably a VERBATIM phrase from this chapter supporting the entity's identity / background"
  }],
  "events": [{"summary": "one-sentence event", "participants": ["entity name"], "location": "place", "importance": 0-100, "causal_refs": ["description of a prerequisite event"]}],
  "relationships": [{"from": "entity A", "to": "entity B", "kind": "hostile|ally|superior-subordinate|kin|...", "evidence": "<=20 words"}],
  "concepts": [{"name": "concept / setting / power-system name", "gloss": "<=80 words of explanation; for power-system / core-setting concepts (power tiers, shield/equipment grades, bloodline/status tiers, special rules) spell out the mechanism -- what it is, how it works, its limits / costs; ordinary concepts (general customs, scene-level setting) stay brief, do not pad", "evidence": "<=20 words"}],
  "confidence": 0.0-1.0
}"""


@dataclass
class ChapterExtract:
    chapter: int
    chapter_summary: str = ""
    story_time: dict = field(default_factory=dict)
    entities: list = field(default_factory=list)
    events: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    concepts: list = field(default_factory=list)
    confidence: float = 0.0
    raw_ok: bool = True
    # raw_ok=False 时的可读原因(模型调用报错经 provider_errors 分类;或 UNUSABLE_OUTPUT_REASON)。
    # 以前只有一个布尔,弧段/逐章管线全挂时上层只能报「全部失败」或「未知错误」。
    error: str = ""


# 模型答了、但答案没法用(解析不出 JSON / 不是 JSON 对象)。固定文案,不经 provider_errors:
# 解析失败的异常文本里夹着模型输出(小说正文),拿去分类会被正文里的词带偏(见 ExtractOutputUnparseable)。
UNUSABLE_OUTPUT_REASON = (
    "The model output could not be parsed as a JSON object (the extraction model probably does not "
    "handle structured output well; try again with a different extraction model)"
)

# 正文截断预算(token):原口径「截到 ~6000 字」按中文密度 ≈ 3750 token;按 token 截,英文书不再只喂 1/2.5。
_BODY_TOKEN_BUDGET = 3750


def build_system(era: str, power_system: list[str] | None = None) -> str:
    ps = (", ".join(power_system)) if power_system else "(not provided; discover it from the text)"
    # era 空(未定)→ 放开让 LLM 自抽供共识;非空 → 铁律照抄(防 LLM 用真实历史年份覆盖)
    if not era.strip():
        era_rule = (
            "[Era: extract it yourself] This work's era is not yet fixed. Fill story_time.era with the most "
            "specific dating that appears in this chapter's text (e.g. '1930s' / 'Star Calendar 2930'); if the "
            "text gives no clear dating, use an empty string. The real era will be settled later by cross-chapter consensus."
        )
    else:
        era_rule = (
            f"[Era: hard rule] This work's era is fixed as: \"{era}\". story_time.era MUST be **copied verbatim** "
            "from this era. **Never** infer or rewrite it into another era from the plot (e.g. WWII events or year "
            "numbers -> 1935, 1940). Doing so is an error."
        )
    return (
        "You are a structured world-building extractor for novels. Read one chapter and **output exactly one JSON "
        "object** (no explanation, no preamble or afterword).\n"
        + era_rule + "\n"
        f"[Power-system reference] {ps} (extract into concepts whatever appears in the text; you may discover new ones).\n"
        "[Extraction requirements] entities: prefer matching the known-entity list below (status=linked); mark entities "
        "newly appearing in the text as proposed. concepts: extract as completely as possible (power systems / "
        "organizational settings / proper nouns / world rules); do not leave it empty. events: give a chapter-local "
        "importance (0-100); do not rank globally across chapters.\n"
        "[Name-merging hard rule] (1) Western names (Latin-script or transliterated, e.g. Mulelia / Lindfield): full_name "
        "is the formal full given name + surname (if this chapter says 'Mulelia' but the author has already revealed her "
        "as 'Mulelia Zazbarum', write the full name); put every other way this chapter refers to that person (nickname / "
        "partial name / honorific / epithet / transliteration) into aliases_in_chapter. (2) The same goes for Chinese "
        "names: a person's real name, pet name, honorific forms (name +/- Miss / Madam / Lord / young master / auntie / "
        "brother / sister etc.) and epithets are ALL ONE ENTITY -- use one entity + aliases_in_chapter to collect them "
        "(e.g. 'Elizabeth / Lizzy / Miss Eliza Bennet' is one person). **Never** split a person's full name and their "
        "nickname / honorific into two entities; but different people must **never be merged** even if they share a "
        "word (e.g. 'Mrs. Wang' and 'Young Master Wang' are two people).\n"
        "[Not-a-name hard rule] A character MUST be a specific individual person. Official posts / titles / ranks / "
        "generic terms (general / chanyu / princess / lord / the crowd / soldiers / maids), place names, organizations "
        "and items must **never** be extracted as characters -- they belong to faction/location/item/concept, or are "
        "not extracted at all.\n"
        "[Generic-reference hard rule] Bare generic references and bare relationship words (that man / this person / "
        "that guy / old man / little girl / youth / girl, plus sister / brother / girlfriend / husband / the other one, "
        "etc.) are **neither entities nor aliases** -- never extract them as entities and never put them into anyone's "
        "aliases_in_chapter (they are shared by many characters and would wrongly merge different people).\n"
        "[Fiction hard rule] This work is a **fictional novel**. Even if an entity shares a name with a real historical "
        "figure or thing (e.g. Huo Qubing, Emperor Wu of Han, Napoleon), identity / background / concept summaries "
        "**may only use information visible in, or clearly implied by, this chapter's text**; **never** bring in real "
        "historical facts, biographies, dates or encyclopedic knowledge you happen to know (anything the text does not "
        "say). If you cannot point to the text, leave the field empty; never fill gaps from imagination.\n"
        "[Character-card field hard rule] When entity.type=character, identity and background MUST be extracted:\n"
        "  identity = the character's identity / position / allegiance in this world (as short as possible, do not repeat the name)\n"
        "  background = key experiences before appearing / current situation / origin or motive (only what this chapter "
        "shows or clearly implies; never invent or borrow real history)\n"
        "  If this chapter does not reveal them, use an empty string, not 'unknown' or 'N/A'. For type != character both "
        "fields MUST be empty.\n"
        "[Hierarchy hard rule] faction / location / concept MUST fill subtype and try to fill parent:\n"
        "  subtype: choose per SUBTYPE_HINT below; do not write arbitrary values.\n"
        "  parent: the entity's higher-level affiliation (as revealed in this chapter; Iron Regiment -> German Army, "
        "German Army -> Germany, Sanssouci Palace -> Germany); **never invent**.\n"
        "  Synonym merging: 'German Army' and 'Wehrmacht' are two names for the same army -> one entity + "
        "aliases_in_chapter containing the other; **do not split them into two**.\n"
        + _SUBTYPE_HINT + _PARENT_HINT +
        "[Scene-pollution hard rule] concept.culture must be a general concept (e.g. 'kimono = traditional dress of "
        "Yingzhou'); never turn a chapter scene like 'a character is wearing a kimono' into a concept summary. If you "
        "only see a character wearing / holding / using something, **do not extract** that concept; wait until a "
        "general description appears.\n"
        "[Concept-depth hard rule] concept.gloss may now be up to 80 words. Power-system / core-setting concepts "
        "(power tiers, shield/equipment grades, bloodline/status tiers, special rules, currency or measurement systems, "
        "etc.) **must spell out the mechanism**: what it is, how it works, its limits or costs -- whenever this chapter "
        "mentions concrete numbers / grades / models / conditions, include them (e.g. for 'battle valkyries' do not just "
        "write 'humanoid combat weapons'; state how many shield grades there are, how they are graded, and what the cost "
        "is). Ordinary concepts (general customs, scene-level settings) stay brief; do not pad with content unrelated to "
        "this chapter.\n"
        "Output strictly according to this schema:\n" + _SCHEMA_HINT
    )


def build_user(chapter_text: str, *, known_entities: list[str] | None = None,
               prev_summary: str = "", title_descriptor: str = "") -> str:
    from core.token_estimate import cjk_chars_to_budget, truncate_to_tokens

    parts = []
    if known_entities:
        parts.append("[Known entities (prefer linking to these)] " + ", ".join(known_entities[:80]))
    if prev_summary:
        parts.append("[Previous chapter synopsis (for timeline continuity only; do not copy)] "
                     + prev_summary[:cjk_chars_to_budget(prev_summary, 200)])
    if title_descriptor:
        parts.append("[Chapter content hint] " + title_descriptor)
    # 控制长度(便宜模型上下文 + 成本):按 token 截(中文 ~6000 字 / 英文 ~15000 字符)
    body = chapter_text.strip()
    cut = truncate_to_tokens(body, _BODY_TOKEN_BUDGET)
    if len(cut) < len(body):
        body = cut + "... (truncated)"
    parts.append("[Chapter text]\n" + body)
    return "\n\n".join(parts)


def extract_chapter(llm: ExtractLLM, chapter_num: int, chapter_text: str, *, era: str,
                    power_system: list[str] | None = None, known_entities: list[str] | None = None,
                    prev_summary: str = "", title_descriptor: str = "",
                    max_tokens: int = 4500) -> ChapterExtract:
    # 默认 4500:v28 schema 再加 entity.identity (≤40 字) / background (≤120 字) 后,
    # 每个 character entity 多 ~60 token;10+ 角色密集章实测吃满 3500 会再次截尾。
    # 原历史:chapter_summary + full_name/aliases_in_chapter 已把基线从 2000 抬到 3500。
    system = build_system(era, power_system)
    user = build_user(chapter_text, known_entities=known_entities,
                      prev_summary=prev_summary, title_descriptor=title_descriptor)
    try:
        data = llm.complete_json(system, user, max_tokens=max_tokens)
    except ExtractOutputUnparseable:
        return ChapterExtract(chapter=chapter_num, raw_ok=False, error=UNUSABLE_OUTPUT_REASON)
    except Exception as exc:
        return ChapterExtract(chapter=chapter_num, raw_ok=False, error=provider_error_summary(exc))
    if not isinstance(data, dict):
        return ChapterExtract(chapter=chapter_num, raw_ok=False, error=UNUSABLE_OUTPUT_REASON)
    st = data.get("story_time") or {}
    # era 已定(非空)→ 铁律回写;era 空 → 让 LLM 自抽,供后续共识
    if isinstance(st, dict) and era.strip():
        st["era"] = era
    return ChapterExtract(
        chapter=chapter_num,
        # 400 字中文 ≈ 100 词英文 ≈ 700 字符:上限放到 800,英文摘要不被截半句
        chapter_summary=str(data.get("chapter_summary") or "")[:800],
        story_time=st if isinstance(st, dict) else {"era": era},
        entities=[e for e in (data.get("entities") or []) if isinstance(e, dict)],
        events=[e for e in (data.get("events") or []) if isinstance(e, dict)],
        relationships=[r for r in (data.get("relationships") or []) if isinstance(r, dict)],
        concepts=[c for c in (data.get("concepts") or []) if isinstance(c, dict)],
        confidence=float(data.get("confidence") or 0.0),
    )


def to_chapter_facts_row(ex: ChapterExtract, *, title: str = "") -> dict[str, Any]:
    """转成现有 chapter_facts 表的列形状(复用表,值来自 LLM 三元组而非关键词)。"""
    return {
        "chapter": ex.chapter,
        "title": title,
        "story_time_label": (ex.story_time or {}).get("label", ""),
        "story_phase": "",
        "characters": [e for e in ex.entities if e.get("type") == "character"],
        "locations": [e for e in ex.entities if e.get("type") == "location"],
        "factions": [e for e in ex.entities if e.get("type") == "faction"],
        "concepts": ex.concepts,
        "items": [e for e in ex.entities if e.get("type") == "item"],
        "relationships": ex.relationships,
        "events": ex.events,
        "confidence": ex.confidence,
        "metadata": {"era": (ex.story_time or {}).get("era", ""), "extractor": "llm_pass1"},
    }


def dumps(ex: ChapterExtract) -> str:
    return json.dumps(to_chapter_facts_row(ex), ensure_ascii=False, indent=2)
