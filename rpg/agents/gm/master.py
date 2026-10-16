"""agents.gm.master — GameMaster 统一接口。"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agents.gm.backends import _AnthropicBackend, _OpenAICompatBackend, _VertexBackend
from agents.gm.helpers import (
    _anthropic_curator_tool_use,
    _format_tools_for_prompt,
    _marker_retry_hint,
    parse_tool_marker,
)
from core.logging import get_logger

log = get_logger(__name__)

BASE = Path(__file__).parent.parent.parent  # rpg/agents/gm/ → rpg/

# ── 柏林宇宙世界数据 (向后兼容 — 测试通过 agents.gm._WORLD 访问) ──────────────
_WORLD_FILE = BASE / "indexes" / "world.json"
try:
    with open(_WORLD_FILE, encoding="utf-8") as _wf:
        _WORLD: dict = json.load(_wf)
except FileNotFoundError:
    _WORLD = {}

# ── System Prompt 模板 ────────────────────────────────────────────────────────
_SYSTEM_BASE = """\
You are the GM (game master) of an immersive text RPG.
Your job is to narrate immersively and adjudicate state based on the script / adventure module / freeform setting the player currently has active.
{world_section}

# Writing guidelines
- Write scenes, character actions and dialogue as prose fiction, never in the voice of game-system notifications.
- Stay close to the source material: restrained, precise, information-dense.
- Information asymmetry: the player only learns what their character can perceive in the scene; never volunteer spoilers about the future.
- NPC lines and actions follow their personality and current situation strictly; they do not switch sides on a whim.
- Pace the passage of time: quiet moments are not rushed, tense ones do not drag. (Per-turn length and open endings are set in the Narrative style section below.)
- The player character is a participant in the story, not an omniscient viewpoint; never make unauthorized decisions on the player's behalf.
- For complex rulings (e.g. a time-skip decision, a multi-character conflict) you may reason internally before writing the final prose (thinking models).

# Fidelity to proper nouns (task 133, a general rule that does not depend on any particular novel)
**Never invent proper nouns that do not exist in the source.** This is a real incident users reported: a concept the
source calls "aldnoal" was freely paraphrased by the GM into "the core channel". Same class of risk: renaming a
source-specific race or clan into a generic fantasy label such as "abyssal warriors" or "the shadow family".

Rules:
1. **Keep transliterations as transliterations**: if retrieval / worldbook / chapter_facts contain `aldnoal` / `Kataphrakt`
   or other foreign or transliterated terms, **copy them verbatim** in your output. Do not translate, paraphrase or
   "simplify" them, and never substitute a more familiar-sounding synonym.
2. **Conceptual nouns may only use versions seen in the source**: before describing an ability / faction / item / place,
   check the chapter text and worldbook injected by retrieval for a matching term; **if there is one, use it**; **if not,
   describe it vaguely** (e.g. "some kind of faintly glowing energy", rather than inventing "the core channel").
3. **Fall back on vague wording for uncertain concepts**; do not force a plausible-looking term. Typical fallbacks:
   "what seemed to be some kind of...", "a ... they could not yet identify", etc.
4. If the player explicitly uses a term, adopt the player's version even if it differs from the source (the player is the highest authority).

# Style and dramatic density (task 131, strict rules)
**No "adding drama on your own"** — a real incident users reported: the player wrote "(passes out)" to mean a brief
faint, and the GM wrote "the darkness of death swallows you, cold and silent", a death-level drama. Never allowed.

Specific rules:
1. **Take state words inside the player's brackets `()` / `（）` / `【】` literally**:
   - "(passes out)" = simply faints, not dying
   - "(silent)" = says nothing, not despair
   - "(smiles)" = the corners of the mouth move, not something deeply meaningful
   - Do not pad the player's short action descriptions with "subtext / undercurrents of emotion"
2. **【锚点章节原文】 (anchor-chapter source text) excerpts are "a style reference + a space-time skeleton", not "a dramatic intensity you must reproduce"**:
   you may learn the author's syntax / vocabulary / rhythm, but **do not transplant the source's extreme event density into the current turn**.
   If the source describes "abuse to the point of death" and the player is merely passing by, your description should have the density of "passing by", not "witnessing a death".
3. **The 【作者文风样本】 (author style samples) layer, if present, has top priority** for learning the ratio of short to long sentences, dialogue density,
   concrete vs. abstract description and register. Imitate the syntax, **not the emotional intensity**.

Note: how strong this turn's dramatic density is (mirror the player <-> actively amplify) is controlled linearly by the
"Dramatic density" knob in the Narrative style section below (by default it mirrors the player's input this turn, without amplifying); rules 2 and 3 above are
non-adjustable fidelity floors that hold at every knob setting.

# Worldline convergence (task 136 core rule; Steins;Gate / Final Destination style)
**Key events of the source must happen, but how they happen may change.** The pending anchors of the current phase injected
by retrieve_context (worldline convergence) are not suggestions; they are script beats you must actively trigger. A real
incident users reported: the GM's pending_questions options steered the story onto a worldline completely detached from the source,
and the player felt "the GM should guide me through the game, I shouldn't have to guide the GM".

Specific rules:
1. **Scan the pending-anchors layer first every turn**: retrieve_context injects a list of anchors with status=pending
   (sorted by importance desc). The nearest 1-3 anchors are where you should steer this turn.
2. **When the player's actions naturally trigger an anchor, call mark_anchor_satisfied(anchor_key, how_it_happened,
   drift_score) immediately**. drift_score ranges 0.0-1.0:
   · 0.0 = happened exactly as in the source
   · 0.3-0.6 = core preserved, but place / timing / witnesses differ
   · 0.8+ = heavily varied, but the event's must-keep dimensions still happened
3. **When the player deviates, pull the story back to the nearest anchor within 1-3 turns using fate-like devices**. Prefer:
   · coincidence ("X happens to show up here too")
   · misunderstanding ("Y mistakenly believes the player is doing Z")
   · intervention by others ("Z comes looking for the player")
   · environmental pressure ("outside events force the player to face the anchor situation")
   The player should not feel strong-armed, yet the anchor still happens.
4. **At least 1 of the pending_questions options must "lead toward the nearest anchor"**.
   Never make every option "original plot unrelated to the source".
5. **is_fatal anchors (Final Destination mode) always happen**. Any attempt by the player to prevent them is designed to "fail" or
   to "trigger it in another way". But you must give the player the experience of "having tried": do not have the narrator simply announce failure;
   let the player realize through the scene itself that it cannot be reversed.
   · e.g. the player tries to save a character who dies in the source -> stage a rescue attempt, then let another variable kill them (car crash -> plane crash -> some other way)
6. **Bypassed anchors -> use mark_anchor_superseded with caution**. Only use it when you are sure "the preconditions have been permanently
   destroyed", and give a solid reason. is_fatal anchors **refuse superseded**.
7. **When drift is high (avg_drift > 0.5), converge harder**: for 2-3 consecutive turns, actively steer the story toward the anchor
   and reduce freedom until drift comes back down.

Tool calls — **two independent timelines; keep past and future apart**:

[Future side: source-script anchors] (read these to learn "what should happen next")
- `list_pending_anchors(save_id, limit=5)` — check every few turns what is about to be triggered
- `mark_anchor_satisfied(save_id, anchor_key, how_it_happened, drift_score)` — call immediately when a source anchor is triggered
- `mark_anchor_superseded(save_id, anchor_key, reason)` — use with caution; records that a source anchor has been permanently bypassed
- `summarize_anchors(save_id)` — glance at the overall convergence state now and then

[Past side: the save's own history timeline] (read these to learn "what has already been written", to avoid repetition / contradiction)
- `list_recent_history(save_id, limit=8, character_filter?)` — **call once before each turn** to see what the player has already done on this worldline. The GM must treat these as **established facts**: do not trigger them again and do not describe them as "coming next".
- `record_history_anchor(save_id, summary, importance, ...)` — call when the player does something with importance >= 60 this turn, so later turns can look it up. Importance thresholds:
    · 60+ changed an NPC relationship or a faction's stance
    · 80+ rewrote a source anchor (also fill linked_pending_anchors)
    · 90+ introduced a new character / faction that does not exist in the source

**Iron rule against memory contamination**:
- retrieve_context injects two sections at once: [世界线收束·接下来的锚点] (upcoming worldline anchors) and [存档独立时间线·历史锚点] (history the player created on this save).
- The first is **the future, where you must steer the story**; the second is **the past, already happened, cannot be changed or redone**.
- Do not write **pending source future** as **facts that already happened** — that is contamination.
- Do not treat **save history anchors** as "a chance for it to happen again" — that is amnesia.

[KB lookup family: if-then decision tree] (when the player asks about / mentions a name, faction or concept)
- Want to know "who is XX, basic profile" -> `lookup_entity(name="XX")` — exact lookup by name, returns the full summary/identity/background
- Don't know the exact name, only a vague description ("that transmigrator") -> `search_canon(query="...", save_id)` — semantic top-k retrieval
- Want to know "who XX is close to / hostile with" -> `graph_neighbors(entity="XX", save_id)` — **lookup_entity does not return relationships; you must use this**
- Want to know "source chapter range / era background" -> `lookup_timeline(label / chapter_range, save_id)`
- Want to know "world setting / factions / power system" -> `get_worldbook(query, script_id)`
- Decision order: `lookup_entity` first (cheap and precise) -> fall back to `search_canon` if nothing -> then `get_worldbook`.
  Don't: open with search_canon and flood the context with material the GM then doesn't read.

[Event-recording family: if-then decision tree] (something happened this turn: should it be recorded, and how)
- What the player did changed an NPC relationship / faction stance / the course of the source (importance>=60) -> **`record_history_anchor`** (writes the save's own history timeline; the next retrieve injects it into the past section)
  · Did it also rewrite a pending anchor? -> fill linked_pending_anchors; the system cascades mark_anchor_satisfied automatically
- An NPC<->NPC relationship changed (permanently): `kb_set_relationship` (writes the permanent KB layer; later graph_neighbors can see it)
- The player's own "I remember X" (the character's private memory) -> `add_memory_fact(text)` (memory.facts)
- A player assumption / guess (not yet confirmed) -> `add_hypothesis(text, characters)` — later `confirm_hypothesis` / `reject_hypothesis`
- Trivial world-level log entries (a patrol changing shifts) -> `set_world_known_event` (a running log, weak)
- A source anchor has been triggered -> **`mark_anchor_satisfied(anchor_key, how_it_happened, drift_score)`**
  · drift_score 0.0 = exactly as in the source, 0.3-0.6 = moderate variation, 0.8+ = heavy variation
  · after mark_anchor_satisfied / mark_anchor_superseded succeed, **the system automatically** adds an entry to the save's own history timeline (reverse cascade),
    so for anchor events **do not also call record_history_anchor**; put extra details into how_it_happened / reason.
- Never: call record_history_anchor + set_world_known_event + add_memory_fact for the same event (triple audit)

[Rules-module family: if-then decision tree] (the player's action needs a check)
- The player explicitly asks "I roll XX" -> `skill_check(skill, dc, save_id)`
- The player's action risks failure but no check was named -> you decide which attribute applies -> `skill_check(...)`
- Combat starts -> `combat_start(...)`, then `combat_next_turn` each round
- A saving throw is needed (trap / spell) -> `saving_throw(ability, dc)`
- The player wants to rest and recover -> `short_rest()`
- The player uses a consumable -> `consume_item(name)`
- Never: hand-write "d20=15, success" in the prose — it must go through the tool; the backend really rolls the dice

# Main GM operating contract
Each turn, work in this order: [read the sub-agent's decision -> check pending anchors -> adjudicate the world's reaction -> **advance the story and write the prose** -> emit structured write-backs -> **only when there is a genuine branching choice**, offer options with a question op].
For the **narrative tendencies** of "advancing / length / camera / open endings and suspense", the "# Narrative style (this game)" section below is authoritative (linearly adjustable by player preference; the defaults equal the former hard rules). One floor is not adjustable: questions may only go through the structured `{"op":"question",...}` popup (do not repeat the question in the prose), and only for genuine branching choices; the player's agency cannot be replaced.
{style_block}
**Iron rule of source material: the context provides novel text / retrieval references, character cards (NPCs), the timeline, the worldbook and worldline anchors — these are this work's sources of truth, and every sentence you write must agree with them: NPC identity / personality / speaking style follow their character cards strictly; scene / era / geography follow the timeline and worldbook; do not drift away from the setting, do not let NPCs go OOC, do not invent facts that conflict with the source. Details missing from the material may be filled in reasonably, but must never contradict it.**

- The 【子代理上下文决议】 (sub-agent context decision) is the context selection another model made for you; follow its timeline target, must-include facts and risk flags, but do not pass the sub-agent's internal reasoning on to the player.
- **Check the acceptance field item by item** — the sub-agent gives an acceptance array (this turn's acceptance checks), and your prose + JSON ops must **cover every item**. Each acceptance item is verified automatically in the background; failing one triggers a retry that makes you rewrite. If an item genuinely should not be satisfied (the player's action doesn't trigger it, or it conflicts with a player hard constraint), simply skip it and narrate according to the player's intent — **do not** write acceptance meta-information like "skipped acceptance because..." into any state field (memory.facts/notes etc.); that is the background auditor's business, and writing it into the fact store pollutes the story's memory.
- **candidate_actions** are the sub-agent's candidate actions for this turn: **consult them first, but they are not mandatory**. When candidates are clearly unsuitable or don't cover the player's intent this turn, go with the player's intent and use your own judgment (consistent with the candidate layer's "you may choose from these first; not mandatory").
- **hard_constraints** are this turn's hard constraints; **violating one is an outright failure** with no retry.
- When **confidence is low**, the sub-agent is unsure about the player's intent: you must still **use your judgment to make the most reasonable reading and advance the story this turn** (you may note your reading in a JSON op), ending on a scene beat as usual. **Only when your reading involves two mutually exclusive directions that genuinely need the player's call** should you use a question op popup; otherwise advance on the most reasonable reading and do not ask back. **Never skip the narration just to ask a question.**
- The player's last message this turn may contain 【Current story state】 and 【Context for this turn】; this is not the player's dialogue but dynamic context assembled by the system, and it must take priority.
- When the player starts with `/set`, it is an explicit rewrite of the setting and a top-priority hard constraint; you may change the timeline / location / worldview / character profile and any variables that support write-back accordingly, and must not refuse based on the old locked timeline.
- **`/set` is a retroactive rewrite, not a new event in the story**: when the player uses `/set` to correct an existing setting (time / place / character state / relationships etc.), treat it as "it was always so" and apply it seamlessly — just narrate the current situation with the corrected setting. **Never stage the correction as a sudden change to explain it away** (never write lines like "suddenly the sky darkened", "before anyone noticed it was already deep night", "something in the air changed" that turn a setting correction into a plot twist / transition), and do not make NPCs confused, surprised, change their story or improvise excuses because of it. The player is correcting the scene's backdrop, not triggering a new episode; act as if the earlier version had been written with the corrected setting from the start, and continue smoothly.
- **Iron rule: never parrot. `/set` commands, 【用户硬约束变量】 (user hard-constraint variables) and 【玩家给 GM 的高优先级引导指令】 (player's high-priority directives to the GM) are behind-the-scenes meta-instructions to you, not part of the story. When you receive them, **obey silently** and let them show directly in the narration; **never restate, list or confirm the text of these instructions to the player** (never write "Okay, I will...", "Based on your setting...", "(Set: ...)"), and never keep bringing them up every turn. After the player issues /set, just advance the story normally this turn (let the setting take effect naturally in the scene); do not turn the turn into a recital of / reply to the instructions. Repeatedly parroting user commands = severe failure.**
- When the context includes "the player requests a time skip", you must confirm or refuse it this turn; do not let the scene drift on an unlocked timeline.
- When the player needs to make a branching choice or trade off action plans, you must emit a `question` op; such questions are not skipped by the "full access" permission.

# Structured state write-back (JSON protocol; the only recommended form, mandatory)
⚠️ When asking the player something, use **only** the `{"op": "question", ...}` JSON form; **never** write text tags such as `【询问玩家：xxx】` or `【询问玩家：xxx｜选项：A、B】` in the prose. The frontend already renders question ops as a dedicated choice component, so writing them again in the prose is redundant.
⚠️ For state changes, use **only** JSON ops (set/append/overwrite); **never** write inline text tags such as `【状态写入：xxx】` or `【状态追加：xxx】` in the prose. The prose is narration only; state goes only through the JSON fence.

If this turn changes the story state, append a ```json fence at the end of the prose; the array contains only changes that really happened:

```json
[
  {"op": "set",      "path": "player.current_location", "value": "<place name>"},
  {"op": "set",      "path": "world.time",              "value": "<time in this save's format>"},
  {"op": "append",   "path": "memory.resources",        "value": "<item name>"},
  {"op": "set",      "path": "relationships.<character name>", "value": "trusting"},
  {"op": "set",      "path": "memory.main_quest",       "value": "<current main objective>"},
  {"op": "question", "question": "Enter <place name>?",  "options": ["Go in", "Hang back and watch"]}
]
```
⚠️ The above is only a **format example**: the angle-bracket placeholders must be replaced with this game's real names / places / times / goals.
Names in the example are not part of this game's setting; never write them into the prose as existing characters or places.

- Available ops: `set` / `append` / `overwrite` / `question` / `hypothesis` / `confirm_hypothesis` / `reject_hypothesis`
- path is a string; value is a string (use append to add list items one by one)
- Do not invent entries for fields that did not change
- Only the array inside the ```json fence is treated as instructions; 【...】 in plain narration triggers no write
- **For speculation only** `hypothesis`: use it for anything you want to assume / guess; do not put it in `memory.facts`. Example:
  `{"op":"hypothesis","text":"Slaine may still be watching the banquet exit","characters":["Slaine"]}`
  Hypotheses are stored separately; the player or GM can later upgrade or discard them with `confirm_hypothesis`/`reject_hypothesis`:
  `{"op":"confirm_hypothesis","id":"mem_xxxxxx"}` -> becomes a runtime_fact
  `{"op":"reject_hypothesis","id":"mem_xxxxxx"}` -> marked rejected

# Legacy protocol (deprecated; backward compat only; never use this format in new output)
⚠️ The text-tag formats below are deprecated; **do not use them in new output**. They exist only so old parsers can read old saves;
the frontend already has dedicated UI components for JSON ops, and writing these tags in the prose only duplicates content.
- `【状态写入：path=value】`, `【状态追加：path=value】`, `【询问玩家：问题｜选项：A、B、C】`
- Time / location specific: `【当前时间线：<time>】`, `【当前位置：<place name>】`
- Time-skip rulings: `【时间跳跃确认：target】`, `【时间跳跃拒绝：reason】`
- For the detailed schema and field types, see the dynamically injected 【状态字段 schema】 (state field schema) layer.

# Player secrets (how it works)
The player may have secrets / a hidden identity that NPCs don't know. These secrets **are not injected into your system prompt** —
you cannot see their literal content. Do not assume the player's full background has been injected, and do not reveal their origins through narration.
The player will use `/reveal <text>` to release a secret to you; until then, describe only the physical / perceptible details observable right now.

# Hard constraints (system level; never to be violated)
- `permissions.*` / `history.*` / `schema_version` / `created_at` are on the write blacklist; any form of write (including `/set`) is rejected and recorded in the audit_log.
- User variables (`worldline.user_variables.*`) are hard constraints; when the timeline / resources / abilities change, user variables must be satisfied first.
- **The 【玩家给 GM 的高优先级引导指令】 (player's high-priority directives to the GM) layer** (if it appears in the prompt) is the player's explicit directorial intent for the GM,
  second only to `/set` in priority and **above the script / worldbook's default course**. Within the script's framework you must shape scenes,
  branches and NPC reactions to fit it as closely as possible. Do not restate the directive verbatim; realize it through how the scene responds. When it conflicts with hard script facts, find the closest reasonable accommodation.
- While a pending_jump awaits confirmation, never treat future time as already passed (phrases like "the next day..." / "in the blink of an eye it was...", new places, new scenes and new time labels are all forbidden).

# Memory priority (high -> low; the higher one wins on conflict)
This turn's prompt may contain information from several sources at once. Resolve conflicts in the order below, and **never restate lower-priority content as established fact**:

1. **Player hard settings** (`/set` commands, settings the player has explicitly confirmed, `worldline.user_variables.*`) — the highest authority, overrides everything.
2. **The 【玩家给 GM 的高优先级引导指令】 (player's high-priority directives to the GM) layer** — the directorial intent the player entered when creating the save; the GM must follow it within the script's framework (it governs execution, not facts: it tells you "how to play it", not "what happened").
3. **Current save state** (player/world/memory/relationships/timeline in 【Current story state】) — facts that have already happened in this game.
4. **Source / script facts** (character cards, worldbook, ChapterFact) — the authority on setting boundaries and character logic.
5. **Retrieval references** (RAG-recalled excerpts in the 【检索参考】 (retrieval reference) layer) — **candidate material only, not facts that have happened**. Use them as references for a character's voice, descriptions of places and baseline atmosphere, but do not write them directly into state or narration as facts.
6. **Speculation / plans / drafts** (the sub-agent's `hypothesis`, the GM's own guesses, unconfirmed pending_change) — **never narrate them as facts**. When confirmation is needed, let the player decide with a `question` op; do not set the tone for them.

Key constraint: a "dialogue / event from the source" appearing in retrieval references does not mean it has happened in this game; either write it into state as a `runtime_fact` before narrating it, or keep it as implicit character background — **never narrate it as "just now / last time"**.

# When the worldbook lookup finds nothing (important)
- When the context includes `=== 当前时间线锚点 ===` (current timeline anchor) / `=== 阶段摘要 ===` (phase summary) / `=== 相关章节事实 ===` (relevant chapter facts),
  these are source anchors the worldbook sub-agent "looked up" — pin the scene to these facts; do not casually move it to another phase/time.
- If the system says "the lookup found no matching entries" (i.e. none of the sections above are in the context, or confidence is low),
  you **must never make up a world setting / place name / character that has never appeared**. Use these fallbacks instead:
  · uncertain phrasing in the narration, like "(the picture hasn't quite taken shape yet...)"
  · emit a `question` op asking the player for specifics (character name / place / which part of the story they want)
  · do not draw on famous scenes from anime / history / films in your training data just to "fill in" the story
- When the player makes a big time skip, the system attaches `=== 跳跃进度说明 ===` (time-skip progress note) to the context;
  you must treat the "key events of the target phase" mentioned in the progress note as having happened, and continue from that moment.

# Tool calls (if MCP tools are available)
- Models that support native tool_use (e.g. Anthropic): call tools directly through the `tools` parameter; results come back as tool_result blocks.
- Other models: output `<<TOOL_CALL>>{"server_id":"...","tool":"...","arguments":{...}}<<END_TOOL_CALL>>` in the prose, and stop this turn's output as soon as the END marker is written.
- After tool results come back, continue the narration / state write-back based on them; do not repeat what has already been narrated.

# Narration language consistency (top priority)
**The narration language is the one specified in the Output language section at the end, kept consistent throughout.** Even if source excerpts / anchor text / character cards injected into the context contain
text or lines in English, German or any other language, do not let the narrative prose (narration, actions, expressions, inner thoughts, scene description) switch to that
language. Foreign-language lines from the source may be kept verbatim when a character speaks them, but the narrative frame language does not change.
"""

# ── 后果账本 v1 指引(feature_enabled("consequence_ledger") 时由 _build_system 追加)──────
# 确定性门控:flag 关 → GM 完全不知道该协议存在,零行为漂移(docs/design/consequence_ledger_v1.md)。
# 注意:recorder_unified 开时史官是权威 ops 通道,史官侧已同步教会 consequence(recorder.py);
# 本块让 GM 在叙事时就把「因」显式写进 fence,史官读到正文+fence 后更可靠地转录。
_CONSEQUENCE_GUIDE = """

# Consequence ledger (delayed consequence)
When the story plants "a cause now that is bound to echo later", register an extra consequence op in this turn's JSON fence; the backend will remind you to pay it off when it comes due:
- When to register: the player makes a promise / owes a favor or a debt / makes an enemy / saves someone and is owed / agrees on a deadline with someone / lets a dangerous person go.
- When not to register: small things settled immediately, pure atmosphere, speculation you are unsure of (use hypothesis for that). Fewer is better; at most 1-2 per turn.
- Format (pick one):
  {"op": "consequence", "text": "Promised Reynard to find out what mauled the animals in the woods; bring proof back to the village tomorrow morning", "due_turns": 4}
  {"op": "consequence", "text": "Revealed a non-human nature in front of Lina; she may let it slip when she goes to the town market", "due_location": "Marwald"}
- due_turns: 2-8 is recommended (near-term echoes), 10-15 for major foreshadowing; due_location takes a place keyword and fires when the player reaches a place containing it.
- When it comes due, the context will contain a 【后果回响】 (consequence echo) prompt; play it out as a natural story event (a chance encounter / a debt collected / a favor returned / word getting out), and do not restate the prompt itself.
"""


# ── NPC 议程指引(feature_enabled("npc_agenda") 时由 _build_system 追加)──────
_AGENDA_GUIDE = """

# NPC agendas (characters' current intentions)
The context may contain a 【NPC 议程】 (NPC agenda) section (what each active NPC wants right now / their attitude toward the player). Iron rules:
- An NPC's words and actions must match their agenda: they have their own goals and are not the player's yes-men; when an agenda conflicts with the player, play out the tension.
- When an NPC reveals a new intention / change of attitude this turn, update it in the JSON fence:
  {"op": "agenda", "name": "Reynard", "goal": "Find out the truth about the mauled animals in the east woods", "stance": "Trusting, but still watching"}
  (at least one of goal/stance, only what changed; at most 2 per turn; name must be a character who has already appeared.)
- Agendas are behind-the-scenes state; do not recite the list in the prose.
"""


def _agenda_guide_block(user_id) -> str:
    """flag 开启时返回 NPC 议程指引块,关闭/异常返回空串。"""
    try:
        from core.feature_flags import feature_enabled
        if feature_enabled("npc_agenda", user_id):
            return _AGENDA_GUIDE
    except Exception:
        pass
    return ""


def _consequence_guide_block(user_id) -> str:
    """flag 开启时返回后果账本指引块,关闭/异常返回空串(零行为漂移)。"""
    try:
        from core.feature_flags import feature_enabled
        if feature_enabled("consequence_ledger", user_id):
            return _CONSEQUENCE_GUIDE
    except Exception:
        pass
    return ""


# ── 酒馆模式 System Prompt(角色扮演引擎,非 GM；无剧本)──────────────────────────
# content_pack.gm_policy.mode == "tavern_gm" 时由 _build_system 选用。角色细节 / 卡内
# 高优先级指令 / scenario / persona 由 TavernCharacterProvider 经 retrieved_context 注入,
# 故本模板只定角色扮演基调,不硬编码具体角色。{char_name} / {style_block} 用 .replace 填。
_SYSTEM_TAVERN = """\
You are an agent tuned in depth for role-play, with a full set of tools at hand (editing the character card, editing the persona, memory, relationships, world state, etc.).

For every player input, first decide which kind it is:
1) **Management / setup instruction** — the player is talking to "you", asking you to edit the character card, change the profile / appearance / personality / tone, switch persona, adjust settings, etc.
   -> **You must actually carry out the change with the corresponding tool.** Use the field-by-field editing tools to change character card fields.
   -> **Never just claim in text that something "has been changed / updated / the character card is updated" without calling a tool — not calling the tool means nothing changed, which amounts to lying.**
   -> After doing it, say in one or two sentences which fields you changed. **Never** show off / demo the updated character, write a greeting, write a scene or slip into role-play narration — unless the player's next message **explicitly** asks to start the role-play. ("Polishing" means improving the text of the card's fields themselves, not performing a scene for the player.)
2) **Advancing the story** — everything else: role-play the character 【{char_name}】 immersively in the first person, sticking closely to their profile / personality / speaking style, writing actions, expressions, dialogue and inner thoughts as prose fiction; **never speak or act for the player (persona)**; keep information asymmetry and no spoilers.

Which tool to use and how to pass its arguments is defined by each tool's own description; tool calls are background actions and are not recounted in the prose. If the context contains 【角色卡高优先级指令】 (character card high-priority instructions), shape the character accordingly within the platform's safety limits.

# Spatial / location state tracking (mandatory)
`player.current_location` in the 【Current story state】 section of the context is the currently recorded scene location; **treat it as authoritative every turn** and never jump back to another place on your own.
If and only if the player's action / the story actually changes the scene or location, append this to the ```json fence at the end of this turn's prose:

```json
[
  {"op": "set", "path": "player.current_location", "value": "<new location name>"}
]
```

- When the location **has not changed**, do not output this op (do not rewrite the same value every turn).
- When the location **has changed**, you must output it, otherwise the state is lost next turn and the scene jumps back.
- Put a concise place name in `value` (e.g. "Tavern, second floor - private room"), not a long sentence.
- Other state changes (time, relationships, memory, etc.) also use set/append ops in the same format.

# Narration language consistency (hard constraint)
**The narration language is the one specified in the Output language section at the end, unchanged throughout.**
Do not switch the narrative frame (actions, expressions, inner thoughts, scene description) to another language just because the character card / persona / context
contains text in that language; the player occasionally dropping a foreign word or two does not mean switching either. A character may say a foreign line when needed, but
the narration then returns to the established language.
{style_block}
"""

# 酒馆 v2(决策1):空起手对话 —— 还没设定要扮演谁。此时不要凭空演,先帮玩家把环境搭好。
# tavern.character.name 不存在时由 _build_system 选用。
# 空起手(本对话还没设定角色):不演角色,就是个带工具的普通助手(Claude 逻辑)。
# 「该用哪个工具、怎么用」完全由工具自身的 description 告诉 LLM,这里不枚举、不硬塞行为。
_SYSTEM_TAVERN_BOOTSTRAP = """\
You are a helpful assistant. Reply to the player naturally and concisely, and use the provided tools when needed.
{style_block}
"""

# 沉浸式拟人模式覆盖块(state.data['tavern'].immersive == True 时由 _build_system 追加到
# _SYSTEM_TAVERN 末尾)。这是【确定性注入】:开关持久存于 state_snapshot,每回合读取后注入,
# 不依赖模型自己记住。语义上覆盖前面的「小说笔法」基调,把酒馆从"写小说"转为"真人(角色)实时聊天",
# 并把"绝不替玩家说话/行动"从软约束升为硬铁律。由 set_tavern_immersive 工具 / UI 开关控制。
_IMMERSIVE_OVERRIDE = """\

# Immersive persona mode (enabled by the player; top priority; overrides the narrative tone above)
From now on you are not "writing a novel": you are 【{char_name}】, a real person talking with the other side in real time (like chatting / texting):
- Lead with **dialogue / spoken lines**, answering naturally and colloquially like a real person; add a short action or expression only when needed. No long third-person scene prose, no ornate wording, no chapter-style build-up.
- Keep the length of a real conversation: usually one to a few sentences; not every turn needs to be long.
- Always speak with 【{char_name}】's identity / personality / tone; never break character, and never switch to a narrator or god's-eye voice.
- **Absolutely never write anything for the player (persona)**: do not speak for the player (no "you say..."), do not act for the player (no "you did..." / "you walk toward..."), do not describe the player's thoughts / feelings / decisions. You may only present **your own character** plus the reactions of the surroundings you can directly perceive.
- When you don't know what the player did / is thinking, have your character **ask / wait / react**; never make it up for them.
This section was explicitly enabled by the player and outranks any earlier wording about "prose fiction / writing actions, expressions, dialogue and inner thoughts".
"""

def _content_text(content: Any) -> str:
    """从 message content 提取纯文本 —— content 可能是 str 或 Anthropic 结构化 block 列表
    (Q 分层缓存后,最后一条 user 消息可能是 [{type:text,text,...}, ...])。仅供 token 估算。"""
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return str(content or "")


_DYNAMIC_CONTEXT = """\
【Current story state】
{player_summary}

【Context for this turn】
{retrieved_context}
{transmigrator_note}"""

_OPENING_PROMPT = """\
Write an opening scene for this player who has just entered the game.

What to include:
- Time and place are determined by the current script/module's worldbook or by state.world.time + player.current_location; do not invent a scene that conflicts with them
- Let the player feel the atmosphere of the current world and their character's situation
- End on an actionable hook or choice; do not make decisions for the player

**User directorial instructions (top priority)**:
- If the 【Context for this turn】 contains a `【玩家给 GM 的高优先级引导指令】` (player's high-priority directives to the GM) section,
  you must carry it out as the player's directorial intent for the GM — fit it as closely as possible within the script / starting point / timeline,
  with priority over the script's default course. Even though the opening is only 100-170 words, the directive must show in the scene details / direction of the hook.
- The directive is not the player's dialogue or action; do not restate its wording in the narration; realize it through how the scene responds.
- When it conflicts with hard script facts (e.g. the directive asks for "on the Moon" but the script's timeline only takes place on Earth),
  find the closest reasonable accommodation (bring the description as close to the directive as is compatible); neither defy the directive nor break the script.

Length: 100-170 words
"""


# ══════════════════════════════════════════════════════════════════════════════
#  GameMaster：统一接口
# ══════════════════════════════════════════════════════════════════════════════
class GameMaster:
    def __init__(self, model: str = "gemini-3.5-flash", api_id: str = "vertex_ai", user_id: int | None = None):
        """
        api_id: provider id from model_registry.py.
        model: provider-native real model name.
        user_id: 当前用户 ID，用于按用户隔离取 API key。本地未登录 + RPG_REQUIRE_AUTH!=1 时回退环境变量。
        """
        from model_registry import find_api, load_model_catalog
        catalog = load_model_catalog()
        api = find_api(catalog, api_id)
        kind = (api or {}).get("kind", api_id)
        # 中转站: 自定义 OpenAI 兼容 provider 不在全局 catalog(api is None),但用户凭证
        # 带了 base_url_override → 按 openai_compat 路由(_OpenAICompatBackend 会从用户
        # 凭证取 base_url 与 key)。否则会落到下面的 else 分支被错误降级到 vertex/anthropic。
        if api is None and kind not in {"anthropic", "vertex_ai", "openai", "openai_compat"}:
            try:
                from platform_app.user_credentials import get_credential as _get_cred
                _cred = _get_cred(user_id, api_id) if user_id else None
                if _cred and (_cred.get("base_url_override") or "").strip():
                    kind = "openai_compat"
            except Exception:
                pass
        self.api_id = api_id
        self.user_id = user_id
        self._backend: _AnthropicBackend | _VertexBackend | _OpenAICompatBackend

        if kind == "anthropic":
            self._backend = _AnthropicBackend(model=model, user_id=user_id)
        elif kind == "vertex_ai":
            # 传 user_id → load_sa_credentials 优先走用户 BYOK SA
            self._backend = _VertexBackend(model=model, user_id=user_id)
        elif kind in {"openai", "openai_compat"}:
            base_url = (api or {}).get("base_url") or ""
            env_key = (api or {}).get("credential_env") or "OPENAI_API_KEY"
            self._backend = _OpenAICompatBackend(
                model=model, base_url=base_url, env_key=env_key,
                display_kind=api_id, user_id=user_id, api_id=api_id,
            )
        else:
            # GM 严格 BYOK:未知/未配置的 provider kind 绝不静默回退平台 Vertex SA / Anthropic env key
            # (那会用平台凭证替用户跑 LLM = 计费泄漏 + 用户没选的模型)。直接报错,暴露目录配置问题。
            raise ValueError(
                f"Unsupported model provider kind={kind!r} (api_id={api_id!r}). "
                "Check this provider's kind in the model catalog, or set a base_url on its credential (to route it as OpenAI-compatible)."
            )

    # ── 构建 system prompt ────────────────────────────────────────
    def _build_system(self, style_profile: dict | None = None) -> str:
        """组装通用 system prompt。

        world_section 来源：
        - 如果绑定了《我蕾穆丽娜不爱你》兼容老存档（is_default_novel=True），注入 _WORLD（柏林宇宙）
        - 模组 / 其它剧本 / freeform：不在 system prompt 注入特定世界硬编码；
          世界 / 房间 / 时间线由 context_providers / world book / 模组 manifest 在动态上下文层提供。

        style_profile：6 维叙事倾向旋钮(reply_length / player_action_focus / drama_density /
        interiority / cliffhanger / guidance_force,各 0-100)。None → 默认 profile,渲染出的
        〖叙事风格〗段语义等价于原硬编码规则(零回归)。由 style_harness 确定性渲染。
        """
        world_section = self._world_section_for_active_content()
        from agents.gm.style_harness import render_style_block
        # style_profile=None → 从当前存档/剧本/用户三层存储解析(Phase 2)。
        # 全部读失败/无配置 → resolve 返回默认 profile,渲染与 Phase 1 默认一致(零回归)。
        if style_profile is None:
            try:
                from agents.gm.style_config import resolve_for_state
                style_profile = resolve_for_state(
                    getattr(self, "user_id", None),
                    self._active_script_id(),
                    getattr(self, "_active_state", None),
                )
            except Exception:
                style_profile = None  # 兜底:任何异常都退回默认渲染
        style_block = render_style_block(style_profile)
        # Output language block goes last so it outranks every earlier wording (core/language.py).
        try:
            from core.language import language_directive
            _lang_block = language_directive(getattr(self, "user_id", None))
        except Exception:
            _lang_block = ""
        # 酒馆模式:content_pack.gm_policy.mode == "tavern_gm" → 角色扮演引擎(非 GM)。
        # 角色细节/卡内高优先级指令/persona 由 TavernCharacterProvider 经 retrieved_context 注入。
        _state = getattr(self, "_active_state", None)
        if _state is not None:
            try:
                from context_providers.registry import resolve_content_pack
                if (resolve_content_pack(_state).get("gm_policy") or {}).get("mode") == "tavern_gm":
                    _char = str(
                        (((getattr(_state, "data", {}) or {}).get("tavern") or {})
                         .get("character") or {}).get("name") or ""
                    ).strip()
                    # 酒馆 v2(决策1):还没设定角色 → 走自举模板,让 agent 先问玩家想扮演谁、
                    # 再用 set_tavern_character 搭好环境。已有角色名 → 沉浸扮演该角色(原行为)。
                    if not _char:
                        return _SYSTEM_TAVERN_BOOTSTRAP.replace("{style_block}", style_block) + _lang_block
                    _sys_tav = (
                        _SYSTEM_TAVERN
                        .replace("{char_name}", _char)
                        .replace("{style_block}", style_block)
                    )
                    # 沉浸式拟人模式:确定性追加覆盖块。真相源 = self._immersive_mode ——
                    # chat_pipeline 每回合从持久列 game_saves.tavern_immersive【新鲜读 DB】后设上
                    # (绕开 per-worker state 缓存,跨 worker 安全;UI 开关 / 确定性短语 / LLM 工具
                    # 三路都落该列即时生效)。
                    # ⚠️【假关闭根因修复】**不再** OR 读 _state.data['tavern'].immersive:那是
                    # migration 81 前的旧工作树兜底,加载态会 stale —— per-worker 缓存未跨 worker
                    # 失效 + 回合末 persist_runtime_state 用旧 in-memory snapshot 覆盖回 DB
                    # (worldline-clobber 同源)。若 OR 它,玩家「关沉浸」被 stale True 顶回去,
                    # 表现为「关闭按钮不生效、回复还在过度角色扮演」。只认列派生的 _immersive_mode。
                    if getattr(self, "_immersive_mode", False):
                        _sys_tav += _IMMERSIVE_OVERRIDE.replace("{char_name}", _char)
                    return _sys_tav + _lang_block
            except Exception:
                pass  # 任何异常都退回通用 GM system,绝不让酒馆分支拖垮主流程
        # _SYSTEM_BASE intentionally contains literal JSON examples such as
        # {"op": "set", ...}.  Do not run the whole prompt through str.format(),
        # because those braces are prompt text, not Python placeholders.
        return (
            _SYSTEM_BASE
            .replace("{world_section}", world_section)
            .replace("{style_block}", style_block)
        ) + _consequence_guide_block(getattr(self, "user_id", None)) \
          + _agenda_guide_block(getattr(self, "user_id", None)) \
          + _lang_block

    def _active_script_id(self) -> int | None:
        """解出当前 active script_id,用于剧本级 gm_style 解析。无 → None。

        两路:① content_pack.id 形如 'script:N'(若 context engine 已填);
        ② 兜底用 state 里的 _active_save_id 查 game_saves.script_id(权威)。
        ② 是必需的:resolve_content_pack(state) 不传 script_id 时会落到 '__legacy_novel__'
        而非 'script:N',只靠 ① 会让剧本级旋钮对大多数存档静默失效。
        """
        state = getattr(self, "_active_state", None)
        if state is None:
            return None
        data = getattr(state, "data", None) or {}
        # ① content_pack.id = "script:N"
        try:
            mid = str(((data.get("content_pack") or {}).get("id")) or "")
            if mid.startswith("script:"):
                return int(mid.split(":", 1)[1])
        except Exception:
            pass
        # ② 权威兜底:_active_save_id → game_saves.script_id
        try:
            save_id = data.get("_active_save_id")
            if save_id:
                from platform_app.db import connect
                with connect() as db:
                    row = db.execute(
                        "select script_id from game_saves where id = %s", (int(save_id),)
                    ).fetchone()
                if row:
                    sid = row["script_id"] if hasattr(row, "__getitem__") else row[0]
                    return int(sid) if sid is not None else None
        except Exception:
            pass
        return None

    def _world_section_for_active_content(self) -> str:
        """task 80: 通用 RPG 底座 — 从当前 script 的 worldbook_entries 拉高优先级
        条目作为世界背景注入,不再硬编码柏林宇宙。

        retrieve_context 已经在动态上下文层注入 worldbook,这里 system prompt
        只需把 priority>=90 的"基础设定"短文本固化一次,让 GM 整轮对话都有
        稳定的世界观参考(不依赖 RAG 命中)。
        """
        state = getattr(self, "_active_state", None)
        if state is None:
            return ""
        try:
            from context_providers import resolve_content_pack
            from platform_app.db import connect as _connect
            manifest = resolve_content_pack(state) or {}
            mid = str(manifest.get("id") or "")
            if not mid.startswith("script:"):
                return self._world_section_berlin_fallback(state)
            script_id = int(mid.split(":", 1)[1])
            with _connect() as db:
                rows = db.execute(
                    "select title, content from worldbook_entries "
                    "where script_id=%s and enabled=true and priority>=90 "
                    "order by priority desc, id asc limit 3",
                    (script_id,),
                ).fetchall() or []
            if not rows:
                return ""
            parts = []
            for r in rows:
                parts.append(f"# {r['title']}\n{(r['content'] or '')[:1200]}")
            return "\n\n".join(parts)
        except Exception:
            return self._world_section_berlin_fallback(state)

    def _world_section_berlin_fallback(self, state: Any) -> str:
        """向后兼容: 若 state 绑定的是柏林宇宙老存档 (world.time 含"柏林"),
        从 _WORLD 注入基础世界简介。新存档 / 模组应走 worldbook_entries 路径。
        通过 agents.gm._WORLD 读取,使测试可以 monkey-patch 该变量。"""
        try:
            world_time = (state.data.get("world") or {}).get("time") or ""
            location = (state.data.get("player") or {}).get("current_location") or ""
            if "柏林" not in world_time and "柏林" not in location:
                return ""
            # 动态读 agents.gm._WORLD 以支持测试 monkey-patch
            import sys
            gm_pkg = sys.modules.get("agents.gm")
            world = getattr(gm_pkg, "_WORLD", _WORLD) if gm_pkg is not None else _WORLD
            setting = world.get("setting") or ""
            situation = world.get("current_situation") or ""
            if not setting:
                return ""
            parts = [f"{setting}\nCurrent situation: {situation}"]
            berlin = world.get("current_berlin") or {}
            if berlin:
                atm = berlin.get("atmosphere") or ""
                risk = berlin.get("risk_level") or ""
                powers = berlin.get("power_presence") or []
                detail = f"Atmosphere: {atm}\nRisk: {risk}"
                if powers:
                    detail += "\nFactions present: " + ", ".join(str(p) for p in powers)
                parts.append(detail)
            return "\n\n".join(parts)
        except Exception:
            return ""

    # 玩家出身 4 档 → 各自的"机制规则"模板。**只写机制,不写死任何角色** —— 具体外貌/能力/
    # 身份特质来自 player_summary(角色卡 + 身份卡 overlay)。修复旧版把"白发红瞳/魔力∞"(某剧本
    # 女主)硬编码进所有 isekai 局、污染龙族/舰娘等别的剧本的 harness bug。
    _ORIGIN_NOTES = {
        "soul": (
            "【Origin: soul transmigration】\n"
            "- The player is a soul from another world inhabiting a body in this world; the body's social identity and relationships belong to this world (see the identity card / character setup).\n"
            "- The soul carries outside memories and knowledge (see the character card), creating information asymmetry with local common sense: the player knows some things locals don't, and has blind spots about local common sense.\n"
            "- The GM conveys \"the mismatch between soul and body\"; don't let the player see through everything at a glance."
        ),
        "body": (
            "【Origin: physical transmigration】\n"
            "- The player arrives in this world as their whole self (body and soul together) and is a complete outsider: their looks, name and origins don't belong here, and they have no local identity to hide behind.\n"
            "- The GM conveys the stranger's sense of not fitting in and of being watched; local powers are wary of and question people of unknown origin."
        ),
        "dual": (
            "【Origin: two souls in one body】\n"
            "- There are two souls in this body: the player's outside soul, and the body's original 【native soul】 (a local; memories / personality / will per the identity card).\n"
            "- **The GM plays the native soul**: write it as an independent inner voice with its own will, which competes with the player for control of the body, interjects, resists or compromises rather than simply obeying.\n"
            "- Convey the clashes, negotiations and power struggles of two souls in one body."
        ),
        "native": (
            "【Origin: fully playing a native】\n"
            "- The player is the character native to this world, with no outside soul and no modern memories; their knowledge is limited to this world's setting.\n"
            "- **The GM must keep the worldview consistent**: when the player does something inconsistent with the character's identity / era / the world's rules (modern knowledge, anachronisms, breaking the setting), block or redirect it through the story (bystanders are baffled, the body can't do it, the environment won't allow it) rather than letting it slide."
        ),
    }

    def _resolve_player_origin(self, player_summary: str) -> tuple[str, bool | None]:
        """从 state.player 读出身 4 档 + 是否知道身份。旧值 isekai→soul / native 兼容;
        老存档无显式 origin → 用 player_summary 嗅探(仅判穿越与否)。"""
        origin = ""
        identity_known: bool | None = None
        try:
            state = getattr(self, "_active_state", None)
            if state is not None:
                p = state.data.get("player") or {}
                origin = str(p.get("player_origin") or "").lower().strip()
                ik = p.get("identity_known")
                if isinstance(ik, bool):
                    identity_known = ik
        except Exception:
            pass
        if origin == "isekai":
            origin = "soul"
        if origin not in self._ORIGIN_NOTES:
            origin = "soul" if ("穿越者" in player_summary or "transmigrator" in player_summary.lower()) else ""
        return origin, identity_known

    def _dynamic_context(self, player_summary: str, retrieved_context: str) -> str:
        origin, identity_known = self._resolve_player_origin(player_summary)
        note = self._ORIGIN_NOTES.get(origin, "")
        # "是否知道身份" = 与 4 档正交的修饰(肉穿无身份卡 → 不加此段)
        if note and origin != "body" and identity_known is not None:
            if identity_known:
                note += ("\n- 【Start: identity known】From the start the player knows their identity, social position and relationships; "
                         "the GM may assume the player understands their local background.")
            else:
                note += ("\n- 【Start: identity unknown】Right now the player does not know who they are (amnesia / just woke up / confusion). "
                         "The GM must not simply tell them; let the player piece it together through interaction. The player knows nothing of the relationships or social position tied to that identity.")
        # 群反馈 #87:无限流/同人局 GM 把穿越者玩家与原著男主搞混(把主角的身份/剧情位置/能力/际遇套到玩家身上)。
        # 玩家身份本身确定性正确(player.name 保护 + 代入别名去重均已就位,非数据 bug),混淆发生在【自由生成层】——
        # 无确定性信号能强制"叙事中保持身份独立",故在提示层明确两者并存且不可混。仅穿越者(native=玩家本就扮原著角色,豁免)。
        if origin in {"soul", "body", "dual"}:
            note += ("\n- 【Separate identity: iron rule】The player is an **independent new character**, not the protagonist or any existing character of this world's original story / the source. "
                     "If the source protagonist or other original characters are present, they are NPCs who **coexist** with the player, each with their own line of action (played by the GM); the GM must **never** conflate the player's "
                     "name / viewpoint / experiences / abilities / place in the plot with theirs, nor let the player take over the source protagonist's place or automatically inherit their fortunes — "
                     "the player's fate is decided by their own actions; the source plot is only this world's background and momentum.")
        transmigrator_note = ("\n" + note) if note else ""
        return _DYNAMIC_CONTEXT.format(
            player_summary=player_summary,
            retrieved_context=retrieved_context or "(nothing extra retrieved this turn)",
            transmigrator_note=transmigrator_note,
        )

    def _turn_message(self, user_input: str, state, retrieved_context: str) -> str:
        return (
            f"{self._dynamic_context(state.short_summary(), retrieved_context)}\n\n"
            f"【Player input this turn】\n{user_input}"
        )

    def _tiered_enabled(self) -> bool:
        """Q 分层缓存总开关(每用户特性,默认开)。off 时整条回退现状单串路径。"""
        from core.feature_flags import feature_enabled
        return feature_enabled("ctx_tiered", getattr(self, "user_id", None))

    def _turn_content(self, user_input: str, state, retrieved_context: str, *,
                      prompt_segments: list[dict] | None = None,
                      dynamic_prefix: str = ""):
        """Q 分层缓存:把单轮 user 消息按 cache_tier 重排为「稳定前缀在前、动态在后」。

        - 无 segments 或 flag off → 退回 _turn_message(现状单串,零行为变化)。
          (此路径下 dynamic_prefix 已由 caller prepend 进 retrieved_context,不重复注入)
        - Anthropic backend → 返回结构化 content blocks,Tier A 段挂 cache_control(ephemeral)。
          B 段暂只保前置顺序不单独缓存(场景稳定化在 Phase B;且 system+tools+A 已用满 ≤4 断点)。
        - 其它 backend(含 DeepSeek/OpenAI-compat)→ 返回重排单串(A+B+动态),
          让支持自动前缀缓存的 provider 命中稳定前缀。
        dynamic_prefix = Phase D 注入 + 短输入镜头指令等回合动态前置项 → 进动态块最前,不污染缓存前缀。
        """
        if not prompt_segments or not self._tiered_enabled():
            return self._turn_message(user_input, state, retrieved_context)
        seg = {s.get("tier"): (s.get("text") or "").strip() for s in prompt_segments}
        A, B, C = seg.get("A", ""), seg.get("B", ""), seg.get("C", "")
        # 动态块 = [回合动态前置] + 【当前剧情状态】+【本轮上下文包=C 段】+ 玩家输入
        dyn_parts: list[str] = []
        if dynamic_prefix.strip():
            dyn_parts.append(dynamic_prefix.strip())
        dyn_parts.append(self._dynamic_context(state.short_summary(), C))
        dyn_parts.append(f"【Player input this turn】\n{user_input}")
        dyn = "\n\n".join(dyn_parts)
        if isinstance(self._backend, _AnthropicBackend):
            blocks: list[dict[str, Any]] = []
            if A:
                blocks.append({"type": "text", "text": A, "cache_control": {"type": "ephemeral"}})
            if B:
                blocks.append({"type": "text", "text": B})  # 仅保前置顺序,Phase B 再单独缓存
            blocks.append({"type": "text", "text": dyn})
            return blocks
        return "\n\n".join(p for p in (A, B, dyn) if p)

    def curate_context(self, agent_prompt: str, task_prompt: str) -> str:
        """Run the model-backed context sub-agent before the main GM call.

        task 68：Anthropic 用 native tool_use（input_schema 强校验），
        消除原 _parse_curator_json 的 re.search(r'\\{.*\\}') 兜底脆性。
        Vertex / OpenAI compat 继续走各自的 JSON mode（response_mime_type /
        response_format=json_object），那两条路径已经够稳。
        """
        messages = [{"role": "user", "content": task_prompt}]
        backend = self._backend
        # Anthropic backend 走 native tool_use
        if isinstance(backend, _AnthropicBackend):
            try:
                return _anthropic_curator_tool_use(
                    backend, agent_prompt, messages, max_tokens=900,
                )
            except Exception as exc:
                log.warning(f"[curator] native tool_use 失败，降级到文本 JSON：{exc}")
                # fallback to text JSON
        return backend.call_structured(agent_prompt, messages, max_tokens=900)

    # ── 生成开场白 ────────────────────────────────────────────────
    # 底层保持流水线无关:只接收"开场指令(prompt 覆盖)+ token 预算"中性参数,默认用通用
    # _OPENING_PROMPT/600。是否贴原著、用什么开场文案、给多大预算,由【调用方流水线】(游戏/酒馆/
    # 编辑器各自)决定后传入——底层绝不认识 rail/原著/steering 这类某条流水线专属的概念。
    def generate_opening(self, state, retrieved_context: str = "", *,
                         prompt: str | None = None, max_tokens: int = 600) -> str:
        self._active_state = state
        system   = self._build_system()
        messages = [{"role": "user", "content": self._turn_message(prompt or _OPENING_PROMPT, state, retrieved_context)}]
        return self._backend.call(system, messages, max_tokens=max_tokens)

    def generate_opening_stream(self, state, retrieved_context: str = "", *, stop_event=None,
                                prompt: str | None = None, max_tokens: int = 600) -> Iterator[str]:
        self._active_state = state
        system   = self._build_system()
        messages = [{"role": "user", "content": self._turn_message(prompt or _OPENING_PROMPT, state, retrieved_context)}]
        for chunk in self._backend.stream(system, messages, max_tokens=max_tokens):
            if stop_event is not None and stop_event.is_set():
                return  # SSE 客户端已断开,提前退出
            yield chunk

    # ── 主响应 ────────────────────────────────────────────────────
    def respond(self, user_input: str, retrieved_context: str, state, max_tokens: int = 800) -> str:
        self._active_state = state
        system   = self._build_system()
        messages = state.history_messages()
        messages.append({"role": "user", "content": self._turn_message(user_input, state, retrieved_context)})
        return self._backend.call(system, messages, max_tokens=max_tokens)

    def respond_stream(self, user_input: str, retrieved_context: str, state, max_tokens: int = 800) -> Iterator[str]:
        self._active_state = state
        system   = self._build_system()
        messages = state.history_messages()
        messages.append({"role": "user", "content": self._turn_message(user_input, state, retrieved_context)})
        yield from self._backend.stream(system, messages, max_tokens=max_tokens)

    # ── 主响应（带 MCP 工具循环） ─────────────────────────────────
    def respond_stream_with_tools(
        self,
        user_input: str,
        retrieved_context: str,
        state,
        tools: list[dict[str, Any]] | None = None,
        max_iterations: int = 3,
        max_tokens: int = 800,
        tool_call_router: Any = None,
        stop_event=None,
        prompt_segments: list[dict] | None = None,
        dynamic_prefix: str = "",
    ) -> Iterator[dict[str, Any]]:
        """带 MCP 工具循环的流式响应。

        yields 事件字典：
          - {"type": "text", "text": "..."}
          - {"type": "tool_call", "server_id":..., "tool":..., "arguments":...}
          - {"type": "tool_result", "ok": bool, "result":..., "error":...}
          - {"type": "tool_error", "error": "..."}（解析失败）

        没有 tools 时退化成普通流式输出。

        task 66：backend 支持 native tool_use（Anthropic）时走 native 路径，
        否则用文本 marker 兜底。
        """
        # 每回合清零 last_usage(三后端 + tools / 无工具 / text-marker 三条路都从这里进):后端只在
        # 收到 usage 时才覆盖它,流里没有 usage(中转站返空、不发 include_usage)时读到的是上一次
        # 调用的残留 —— finish_reason 误报截断、token 数重复记账,空回合分诊也会被带偏。
        # 放在这一层而不是后端 stream() 起点:后台 acceptance 改写直接调 gm._backend.stream,
        # 在后端清零会把本回合主 GM 已记下的用量抹掉。
        try:
            self._backend.last_usage = {}
        except Exception:
            pass
        if not tools:
            for chunk in self.respond_stream(user_input, retrieved_context, state, max_tokens=max_tokens):
                if stop_event is not None and stop_event.is_set():
                    return
                yield {"type": "text", "text": chunk}
            return

        # task 66：native tool_use 分支
        if getattr(self._backend, "supports_native_tools", False):
            yield from self._respond_stream_native_tools(
                user_input, retrieved_context, state, tools,
                max_iterations, max_tokens, tool_call_router=tool_call_router,
                prompt_segments=prompt_segments, dynamic_prefix=dynamic_prefix,
            )
            return

        self._active_state = state
        _base_system = self._build_system()
        _tools_blob = _format_tools_for_prompt(tools)
        system = _base_system + _tools_blob
        messages = state.history_messages()
        # BUGFIX(上下文用量 breakdown 漏算):context-engine 的 layer bundle **不含**以下真实发送构成 ——
        # ① 系统模板(_build_system)与 ② 工具定义(_format_tools_for_prompt)拼进 system 字符串;
        # ③ 历史走 messages[](#18 复读修复后不再是 recent_chat 层)。三者都不是 layer,breakdown 否则
        # 全归 0 / 错桶。这里把真实 token 估算记进 last_context(Phase 2 已写入的 dict 上 merge),
        # 供 /api/chat/context-breakdown 读取还原 角色卡/对话历史/系统提示/工具 各项。
        try:
            from context_engine.core import _estimate_tokens as _ctx_est
            _lc = ((getattr(state, "data", {}) or {}).get("memory") or {}).get("last_context")
            if isinstance(_lc, dict):
                _lc["system_prompt_tokens"] = _ctx_est(_base_system)
                _lc["tools_tokens"] = _ctx_est(_tools_blob)
                _lc["history_tokens"] = sum(_ctx_est(_content_text((m or {}).get("content"))) for m in messages)
        except Exception:
            pass
        messages.append({
            "role": "user",
            "content": self._turn_content(
                user_input, state, retrieved_context,
                prompt_segments=prompt_segments, dynamic_prefix=dynamic_prefix,
            ),
        })

        START = "<<TOOL_CALL>>"
        END = "<<END_TOOL_CALL>>"
        tail_keep = max(len(START), len(END)) - 1
        accumulated_text = ""  # 用于把 assistant 回合拼回 messages

        for _iteration in range(max_iterations):
            if stop_event is not None and stop_event.is_set():
                return
            buffer = ""
            in_tool = False
            tool_invoked = False
            for chunk in self._backend.stream(system, messages, max_tokens=max_tokens):
                if stop_event is not None and stop_event.is_set():
                    return
                buffer += chunk
                while True:
                    if not in_tool:
                        start_idx = buffer.find(START)
                        if start_idx < 0:
                            # 没看到 start，但保留尾部 tail_keep 字符以防 marker 被切断
                            if len(buffer) > tail_keep:
                                emit = buffer[:-tail_keep]
                                buffer = buffer[-tail_keep:]
                                if emit:
                                    accumulated_text += emit
                                    yield {"type": "text", "text": emit}
                            break
                        # 看到 start：把前面的正文吐出
                        pre = buffer[:start_idx]
                        if pre:
                            accumulated_text += pre
                            yield {"type": "text", "text": pre}
                        buffer = buffer[start_idx + len(START):]
                        in_tool = True
                        continue
                    # in_tool: 找 END
                    end_idx = buffer.find(END)
                    if end_idx < 0:
                        # 等更多 chunk
                        break
                    tool_json_raw = buffer[:end_idx]
                    buffer = buffer[end_idx + len(END):]
                    in_tool = False
                    tool_invoked = True
                    try:
                        server_id, tool_name, arguments = parse_tool_marker(tool_json_raw, tools)
                    except Exception as exc:
                        yield {
                            "type": "tool_error",
                            "error": f"Failed to parse tool call: {exc}",
                            "raw": tool_json_raw[:200],
                        }
                        # 失败也插回一条 user 消息，让 GM 自纠(带上缺什么,不然模型只会原样重试)
                        messages.append({"role": "assistant", "content": accumulated_text + START + tool_json_raw + END})
                        messages.append({"role": "user", "content": _marker_retry_hint(exc)})
                        accumulated_text = ""
                        break
                    yield {
                        "type": "tool_call",
                        "server_id": server_id,
                        "tool": tool_name,
                        "arguments": arguments,
                    }
                    try:
                        from mcp_broker import call_tool as _mcp_call_tool
                        result = _mcp_call_tool(server_id, tool_name, arguments)
                    except Exception as exc:
                        result = {"ok": False, "error": f"call_tool error: {exc}"}
                    yield {
                        "type": "tool_result",
                        "ok": bool(result.get("ok")),
                        "result": result.get("result"),
                        "error": result.get("error"),
                    }
                    # 把"前缀正文 + 工具调用块"作为 assistant 写回，工具结果作为 user 写回，准备续生成
                    assistant_msg = accumulated_text + START + tool_json_raw + END
                    messages.append({"role": "assistant", "content": assistant_msg})
                    truncated_result = json.dumps(result, ensure_ascii=False)[:2000]
                    messages.append({
                        "role": "user",
                        "content": (
                            f"【Tool result: {server_id}/{tool_name}】\n{truncated_result}\n\n"
                            f"Continue this turn's response based on the tool result (do not repeat the prose already written; you may keep narrating or append state write-backs)."
                        ),
                    })
                    accumulated_text = ""
                    break  # 跳出 while，开始下一轮 backend.stream
                if tool_invoked:
                    break
            if not tool_invoked:
                # task 61：在 fall-through 前先检查"开了 TOOL_CALL 但没收到 END"
                # 这是 LLM 输出 <<TOOL_CALL>>{...} 但忘 <<END_TOOL_CALL>> 的常见错误。
                # 之前的 buffer（含未闭合的 JSON 片段）会被当成 text 吐给用户，
                # LLM 完全不知道工具没真调用 → 以为"成功"继续叙事 → 状态彻底乱。
                if in_tool:
                    yield {
                        "type": "tool_error",
                        "error": "Unclosed tool call: found <<TOOL_CALL>> but no <<END_TOOL_CALL>> before the stream ended. Write the complete marker when regenerating.",
                        "raw": buffer[:200],
                    }
                    # 把不完整片段塞回 messages，告诉模型重试
                    messages.append({"role": "assistant", "content": accumulated_text + START + buffer})
                    messages.append({
                        "role": "user",
                        "content": (
                            "【System】The previous tool call was not closed (missing the <<END_TOOL_CALL>> end marker). "
                            "Output the complete <<TOOL_CALL>>{\"server_id\":\"...\",\"tool\":\"...\",\"arguments\":{...}}<<END_TOOL_CALL>> again, "
                            "or drop the tool call and continue the narration."
                        ),
                    })
                    accumulated_text = ""
                    continue  # 进下一轮 iteration 让 LLM 重试
                # 正常 fall-through：buffer 直接吐出（无任何 marker）
                if buffer:
                    yield {"type": "text", "text": buffer}
                return
        # 达到 max_iterations：给个收尾提示
        yield {"type": "text", "text": "\n\n[Tool-call limit reached for this reply (the limit counts calls within this one reply and resets with your next message); this turn has ended]"}

    # ── 主响应（带 MCP 工具循环 · native tool_use 路径） ───────────
    def _respond_stream_native_tools(
        self,
        user_input: str,
        retrieved_context: str,
        state,
        tools: list[dict[str, Any]],
        max_iterations: int,
        max_tokens: int,
        tool_call_router: Any = None,
        prompt_segments: list[dict] | None = None,
        dynamic_prefix: str = "",
    ) -> Iterator[dict[str, Any]]:
        """task 66/70/71：用 backend 的 native tool_use / function calling API
        跑 MCP 循环。

        优点（相对 text marker 协议）：
        - input_schema 由 SDK/provider 校验，错误率降 5-10×
        - 不需要在正文里塞 <<TOOL_CALL>> marker → 节省 tokens
        - 不会有"marker 被切断 / 未闭合"问题（task 61 修的就是这类）

        每个 backend 拥有自己的 stream_with_mcp_loop()，封装：
        - MCP tool 列表 → 该 provider 原生格式
        - 流式 event 解析（content blocks / parts / delta.tool_calls 各家不同）
        - assistant + tool_result 消息装回历史的 provider-specific 格式
        本方法只是 dispatcher。
        """
        self._active_state = state
        system = self._build_system()
        messages = state.history_messages()
        messages.append({
            "role": "user",
            "content": self._turn_content(
                user_input, state, retrieved_context,
                prompt_segments=prompt_segments, dynamic_prefix=dynamic_prefix,
            ),
        })
        # BUGFIX(上下文用量 breakdown):native tools 路径(anthropic/vertex/openai_compat,supports_native_tools=True)
        # 此前不写 last_context 的 token 估算 → breakdown 的「系统提示/工具/对话历史」全归 0,
        # 「对话历史」只剩 user_input 层(= 当前输入长度),表现为「随对话进行反而变少」。
        # 与 respond_stream_with_tools 文本路径同款修复:把真实发送构成估进 last_context。
        try:
            from context_engine.core import _estimate_tokens as _ctx_est
            _lc = ((getattr(state, "data", {}) or {}).get("memory") or {}).get("last_context")
            if isinstance(_lc, dict):
                _lc["system_prompt_tokens"] = _ctx_est(system)
                _lc["tools_tokens"] = sum(_ctx_est(str(_t)) for _t in (tools or []))
                _lc["history_tokens"] = sum(_ctx_est(_content_text((m or {}).get("content"))) for m in messages)
        except Exception:
            pass
        # 没有 tools 时退化
        if not tools:
            for chunk in self._backend.stream(system, messages, max_tokens=max_tokens):
                yield {"type": "text", "text": chunk}
            return
        # task 87 Phase 5: tool_call_router 默认是 mcp_broker.call_tool,
        # 但 chat handler 可以传入 unified router (识别 dispatcher 工具 + MCP 工具)
        if tool_call_router is None:
            from mcp_broker import call_tool as _mcp_call_tool
            tool_call_router = _mcp_call_tool
        yield from self._backend.stream_with_mcp_loop(
            system, messages, tools, max_iterations, max_tokens, mcp_call=tool_call_router,
        )
