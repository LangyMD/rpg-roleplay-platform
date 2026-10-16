"""command_tools_script_write §注册表(拆包 2026-07-14,纯机械搬家零行为变化)。

register_script_write_tools:script 级「直写库」写工具注册(章节/世界书/NPC卡/锚点/canon,
严格 owner 闸)。逐字保留原注册表;executor 从各职责子模块导入。
"""
from __future__ import annotations

from tools_dsl.command_dispatcher import ToolSpec, get_registry

from ._helpers import _SCRIPT_WRITE_ORIGINS
from .anchors import _t_create_anchor, _t_delete_anchor, _t_update_anchor
from .canon import _t_upsert_canon_entity
from .chapters import (
    _t_create_script_chapter,
    _t_get_chapter_text,
    _t_import_document_as_chapters,
    _t_preview_document_split,
    _t_read_uploaded_document,
    _t_search_manuscript,
    _t_update_script_chapter,
)
from .extract import _t_delegate_writing_task
from .npc_cards import _t_create_npc_card, _t_update_npc_card
from .worldbook import (
    _t_delete_worldbook_entry,
    _t_upsert_worldbook_entries,
    _t_upsert_worldbook_entry,
)


def _write_entity_crud_specs() -> list:
    return [
        ToolSpec(
            name="update_script_chapter",
            description=(
                "Update the text / title / volume title of one chapter of the script (overwrites the whole chapter text; destructive). "
                "chapter_index is required; pass at least one of title/content/volume_title. "
                "Before changing anything, tell the user clearly which chapter you will change and to what."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "chapter_index": {"type": "integer", "description": "Chapter number (1-based)"},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "The full chapter text (overwrites the existing text)"},
                    "volume_title": {"type": "string"},
                },
                "required": ["chapter_index"],
            },
            executor=_t_update_script_chapter,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=True,
        ),
        ToolSpec(
            name="upsert_worldbook_entry",
            description=(
                "Create or update a worldbook entry. With entry_id = update that entry; without it = create one (creating needs title). "
                "keys/regex_keys/character_filter/scene_filter are string arrays. "
                "Before changing anything, tell the user clearly what you will change."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer", "description": "Present = update, absent = create"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "priority": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                    "keys": {"type": "array", "items": {"type": "string"}},
                    "regex_keys": {"type": "array", "items": {"type": "string"}},
                    "character_filter": {"type": "array", "items": {"type": "string"}},
                    "scene_filter": {"type": "array", "items": {"type": "string"}},
                    "token_budget": {"type": "integer"},
                    "sticky_turns": {"type": "integer"},
                    "cooldown_turns": {"type": "integer"},
                    "probability": {"type": "number"},
                    "insertion_position": {"type": "string"},
                },
                "required": ["title"],
            },
            executor=_t_upsert_worldbook_entry,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="upsert_worldbook_entries",
            description=(
                "Create/update worldbook entries in a batch - use this when creating/changing several entries at once (one call saves them all); "
                "do not call upsert_worldbook_entry one by one (in review mode only the first of those succeeds). "
                "entries is an array of entries; each item has the same fields as upsert_worldbook_entry (title when creating, entry_id when updating). "
                "**At most 6 entries per call**: with too many, the whole call exceeds the output length, gets truncated and fails; split more than 6 across several calls."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "description": "Array of worldbook entries (<= 50); each item: title when creating, entry_id when updating",
                        "items": {
                            "type": "object",
                            "properties": {
                                "entry_id": {"type": "integer", "description": "Present = update, absent = create"},
                                "title": {"type": "string"},
                                "content": {"type": "string"},
                                "priority": {"type": "integer"},
                                "enabled": {"type": "boolean"},
                                "keys": {"type": "array", "items": {"type": "string"}},
                                "regex_keys": {"type": "array", "items": {"type": "string"}},
                                "character_filter": {"type": "array", "items": {"type": "string"}},
                                "scene_filter": {"type": "array", "items": {"type": "string"}},
                                "token_budget": {"type": "integer"},
                                "sticky_turns": {"type": "integer"},
                                "cooldown_turns": {"type": "integer"},
                                "probability": {"type": "number"},
                                "insertion_position": {"type": "string"},
                            },
                        },
                    },
                },
            },
            executor=_t_upsert_worldbook_entries,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="update_npc_card",
            description=(
                "Update an NPC character card in the script. card_id is required (get the id with list_script_npcs first). "
                "Pass only the fields to change (the rest are kept). avatar_path is not accepted (avatars use a dedicated endpoint). "
                "Before changing anything, tell the user clearly what you will change."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "card_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "full_name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "identity": {"type": "string"},
                    "appearance": {"type": "string"},
                    "personality": {"type": "string"},
                    "speech_style": {"type": "string"},
                    "current_status": {"type": "string"},
                    "secrets": {"type": "string"},
                    "background": {"type": "string"},
                    "sample_dialogue": {"type": "array"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "importance": {"type": "integer"},
                    "first_revealed_chapter": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["card_id"],
            },
            executor=_t_update_npc_card,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="update_anchor",
            description=(
                "Update a timeline anchor. anchor_id is required. keywords is a string array. "
                "Before changing anything, tell the user clearly what you will change."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "anchor_id": {"type": "integer"},
                    "story_phase": {"type": "string"},
                    "story_time_label": {"type": "string"},
                    "chapter_min": {"type": "integer"},
                    "chapter_max": {"type": "integer"},
                    "sample_title": {"type": "string"},
                    "sample_summary": {"type": "string"},
                    "confidence": {"type": "number"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["anchor_id"],
            },
            executor=_t_update_anchor,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="create_anchor",
            description=(
                "[Add] a timeline anchor to the script - use it when a continuation introduces a brand-new event/milestone that is not in the canon timeline. "
                "Required: story_time_label (milestone name) + chapter_min/chapter_max (the approximate chapters of the event); "
                "story_phase is optional. New anchors are marked with source editor, so timeline rebuilds will not delete them. "
                "To change an existing anchor use update_anchor (do not create duplicates with this tool)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "story_time_label": {"type": "string", "description": "Name of the new event / milestone"},
                    "chapter_min": {"type": "integer", "description": "Approximate starting chapter of the event"},
                    "chapter_max": {"type": "integer", "description": "Approximate ending chapter of the event"},
                    "story_phase": {"type": "string", "description": "Phase it belongs to (optional)"},
                    "sample_title": {"type": "string"},
                    "sample_summary": {"type": "string"},
                    "confidence": {"type": "number"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["story_time_label", "chapter_min", "chapter_max"],
            },
            executor=_t_create_anchor,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="create_script_chapter",
            description=(
                "Add a new chapter at the [end] of the script. title is required; content is optional (the new chapter's text; it can be left empty and written later). "
                "Use it when a continuation produces a brand-new chapter. To change an existing chapter use update_script_chapter."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "New chapter title"},
                    "content": {"type": "string", "description": "New chapter text (optional)"},
                    "volume_title": {"type": "string", "description": "Volume name (optional)"},
                },
                "required": ["title"],
            },
            executor=_t_create_script_chapter,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="create_npc_card",
            description=(
                "[Create] an NPC character card for the script. name is required; the other fields (identity/appearance/personality/"
                "background/aliases/importance/first_revealed_chapter, etc.) are optional. You can draw on other scripts or the story text "
                "to create new characters. To change an existing card use update_npc_card (list_script_npcs first). Duplicate names are rejected (use update instead)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Character name (required)"},
                    "full_name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "identity": {"type": "string"},
                    "appearance": {"type": "string"},
                    "personality": {"type": "string"},
                    "speech_style": {"type": "string"},
                    "current_status": {"type": "string"},
                    "secrets": {"type": "string"},
                    "background": {"type": "string"},
                    "sample_dialogue": {"type": "array"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "importance": {"type": "integer"},
                    "first_revealed_chapter": {"type": "integer"},
                },
                "required": ["name"],
            },
            executor=_t_create_npc_card,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="delete_worldbook_entry",
            description=(
                "Delete a worldbook entry. entry_id is required (get the id with list_worldbook_entries first). Irreversible; confirm with the user before deleting."
            ),
            input_schema={
                "type": "object",
                "properties": {"entry_id": {"type": "integer"}},
                "required": ["entry_id"],
            },
            executor=_t_delete_worldbook_entry,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=True,
        ),
        ToolSpec(
            name="delete_anchor",
            description=(
                "Delete a timeline anchor. anchor_id is required (get the id with list_anchors first). Irreversible; confirm with the user before deleting. "
                "Canon skeleton anchors (source=novel) may be regenerated by a timeline rebuild after deletion."
            ),
            input_schema={
                "type": "object",
                "properties": {"anchor_id": {"type": "integer"}},
                "required": ["anchor_id"],
            },
            executor=_t_delete_anchor,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=True,
        ),
    ]


def _write_document_manuscript_specs() -> list:
    return [
        ToolSpec(
            name="read_uploaded_document",
            description=(
                "Read a segment (offset/limit slices) of a staged document the user [dropped in]. A doc_id is provided after the user drops in a txt/md file. "
                "Use it to carry out instructions based on the document (e.g. 'create characters / rewrite based on this'). The original text is not in the context; read it with this tool."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "offset": {"type": "integer", "description": "Starting character offset (default 0)"},
                    "limit": {"type": "integer", "description": "Number of characters to read (default 6000, max 20000)"},
                },
                "required": ["doc_id"],
            },
            executor=_t_read_uploaded_document,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="preview_document_split",
            description=(
                "Preview: how many chapters, with which titles, the user's dropped-in document [deterministically] splits into by rule (read-only, nothing saved). "
                "split_rule: auto (default) / chapter_cn (Chinese '第N章' headings) / chapter_en (Chapter N) / number_dot (1.) / custom (with custom_pattern). "
                "Show the preview to the user first; after they confirm, save with import_document_as_chapters."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "split_rule": {"type": "string"},
                    "custom_pattern": {"type": "string"},
                },
                "required": ["doc_id"],
            },
            executor=_t_preview_document_split,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="import_document_as_chapters",
            description=(
                "[Deterministically] split the user's dropped-in document into chapters and write them to the current script. mode=append (default, append at the end) / "
                "replace (clear the existing chapters, then import; use with care). Preferably run preview_document_split first so the user can confirm chapter count/titles. "
                "Purely deterministic splitting (no LLM tokens); suitable for importing a passage, chapter or whole book."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "split_rule": {"type": "string"},
                    "custom_pattern": {"type": "string"},
                    "mode": {"type": "string", "enum": ["append", "replace"]},
                },
                "required": ["doc_id"],
            },
            executor=_t_import_document_as_chapters,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=True,
        ),
        ToolSpec(
            name="delegate_writing_task",
            description=(
                "[Delegate] a piece of writing / a specific task to a sub-model the user configured themselves (BYOK) - e.g. use a stronger model, "
                "or one better at a certain style, to write a passage of a chapter. You can specify model (api_id+model) explicitly; otherwise the user's writing/default model is used. "
                "[Only models the user configured themselves; no platform fallback]; a failed call returns the reason explicitly. "
                "The output is a [draft]: confirm with the user before saving it with update_script_chapter/create_script_chapter. "
                "context can hold reference text (e.g. excerpts of adjacent chapters)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The delegated writing task (the more specific the better)"},
                    "api_id": {"type": "string", "description": "Sub-model provider (optional; empty = default writing model)"},
                    "model": {"type": "string", "description": "Sub-model name (optional)"},
                    "context": {"type": "string", "description": "Reference context / adjacent text (optional)"},
                    "max_tokens": {"type": "integer", "description": "Output length limit (default 2500)"},
                },
                "required": ["task"],
            },
            executor=_t_delegate_writing_task,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="get_chapter_text",
            description=(
                "Read a chapter's [full text] (the chapter's source content). Before fixing anchors / checking lore / using it as writing reference, "
                "read the real text with this - do not rely only on summaries that may be polluted (summary/sample_summary). "
                "chapter_index is required; read long chapters in segments with offset (the result tells you the next offset). Read-only; available to the owner/subscribers."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "chapter_index": {"type": "integer", "description": "Chapter number"},
                    "offset": {"type": "integer", "description": "Starting character offset (for reading long chapters in segments; default 0)"},
                    "max_chars": {"type": "integer", "description": "Maximum characters in this segment (default 12000, max 20000)"},
                },
                "required": ["chapter_index"],
            },
            executor=_t_get_chapter_text,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="search_manuscript",
            description=(
                "Full-text search: search all of the script's chapter texts for a word / phrase / regex and return the hits as [chapter number + title + context snippet + character offset]. "
                "This is the core tool for 'read before you write, never contradict the rest of the book' - when reviewing for repetition, checking whether earlier chapters already established some lore, finding a character's/"
                "item's last appearance, or checking whether foreshadowing paid off, locate it with this first, then read closely with get_chapter_text(chapter_index, offset=@value). "
                "Default is case-insensitive substring matching; regex=true uses Python regex; narrow with chapter_min/chapter_max. Read-only; available to the owner/subscribers."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Word / phrase to search for; a regex when regex=true"},
                    "regex": {"type": "boolean", "description": "Whether to match as a regex (default false = substring)"},
                    "chapter_min": {"type": "integer", "description": "Only search this chapter number and later (optional)"},
                    "chapter_max": {"type": "integer", "description": "Only search this chapter number and earlier (optional)"},
                    "max_results": {"type": "integer", "description": "Maximum number of hits to list (default 30, max 100)"},
                    "context_chars": {"type": "integer", "description": "Characters of context before and after each hit (default 60)"},
                },
                "required": ["query"],
            },
            input_examples=(
                {"query": "gravity control"},
                {"query": "Mitt Torret", "chapter_min": 1, "chapter_max": 20},
            ),
            executor=_t_search_manuscript,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="upsert_canon_entity",
            description=(
                "Create or update a canon entity (by logical_key). Changing an existing entity requires logical_key "
                "(look it up with list_canon_entities first); creating one requires name and type, and logical_key may be omitted - "
                "it is then generated from the name and type and returned in the result. type can only be character / faction / "
                "organization / location / item / concept. aliases is a string array; attrs is an open object. "
                "Before changing anything, tell the user clearly what you will change."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "logical_key": {"type": "string"},
                    "name": {"type": "string"},
                    "full_name": {"type": "string"},
                    "type": {"type": "string"},
                    "summary": {"type": "string"},
                    "identity": {"type": "string"},
                    "background": {"type": "string"},
                    "entity_subtype": {"type": "string"},
                    "parent_logical_key": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "attrs": {"type": "object"},
                    "first_revealed_chapter": {"type": "integer"},
                    "public_knowledge": {"type": "boolean"},
                    "importance": {"type": "integer"},
                },
                "required": [],
            },
            executor=_t_upsert_canon_entity,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
    ]


def register_script_write_tools() -> None:
    registry = get_registry()
    specs: list[ToolSpec] = [*_write_entity_crud_specs(), *_write_document_manuscript_specs()]
    for spec in specs:
        if not registry.has(spec.name):
            registry.register(spec)


