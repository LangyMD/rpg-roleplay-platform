"""command_tools_kb.py — Phase D · GM 知识库查询/写工具(走 dispatcher)。

查询(读规范层 kb_canon + 活态层 kb_*,进度过滤防剧透):
  lookup_entity / search_canon / lookup_timeline / graph_neighbors
写(世界树 delta,写 kb_* 行打 born_commit,= 世界知识 blob→行级):
  kb_upsert_entity / kb_record_event / kb_set_relationship / kb_set_worldline_var

全部 scope="user",executor(user_id, args),自管连接,校验存档归属。
设计 docs/design/D_gm_serving.md §2/§3/§7/§8。
"""
from __future__ import annotations

import json

from tools_dsl.command_dispatcher import ToolSpec, get_registry

_KB_READ_ORIGINS = frozenset({"ui_button", "api_direct", "console_assistant", "llm_chat", "llm_set"})
_KB_WRITE_ORIGINS = frozenset({"ui_button", "api_direct", "console_assistant", "llm_chat", "llm_chat_json_op"})


def _sanitize_kb_text(s, limit: int = 2000) -> str:
    """SEC(M-3/M-16): KB 自由文本(summary/note)会被 lookup_entity/graph_neighbors 读回进 GM
    上下文。中和 【】 状态写入标签 + 限长,防 llm_chat 写对抗指令做储存型注入 / 存储放大。"""
    from context_engine.helpers import _neutralize_state_write_tags as _neu
    return _neu(str(s or ""))[:limit]


# ── helpers ──────────────────────────────────────────────────────────────────
def _save_ctx(db, save_id: int, user_id: int) -> dict | None:
    """取存档上下文:script_id / active commit_id / 进度 / 元知识模式。"""
    row = db.execute(
        "select script_id, active_commit_id, state_snapshot from game_saves where id=%s and user_id=%s",
        (save_id, user_id),
    ).fetchone()
    if not row:
        return None
    # 酒馆 v2(R2):酒馆存档 script_id 列为 NULL,但若玩家绑定了剧本
    # (state_snapshot.tavern.bound_script_id),用该剧本 id 让 KB 读工具可查原著。
    if not row.get("script_id"):
        snap = row.get("state_snapshot")
        if isinstance(snap, dict):
            tv = snap.get("tavern") if isinstance(snap.get("tavern"), dict) else {}
            bsid = (tv or {}).get("bound_script_id")
            if bsid:
                row = dict(row)
                row["script_id"] = int(bsid)
    # 进度 + 元知识:从 game_sessions 设置取(无则默认严格进度=1 / none)
    # 关键:绝不返 progress_chapter=None,_reveal_clause 会因此放行全部实体导致剧透
    sess = db.execute(
        "select turn, worldline, model_name from game_sessions where save_id=%s", (save_id,)
    ).fetchone()
    progress = 1
    mode = "none"
    if sess and isinstance(sess.get("worldline"), dict):
        wl = sess["worldline"]
        raw = wl.get("progress_chapter")
        progress = int(raw) if isinstance(raw, (int, float)) and raw >= 1 else 1
        mode = wl.get("foreknowledge_mode") or "none"
    # pin 重定向:存档若挂在 pinned/floating 引用剧本上,KB 读取走 pin 目标剧本的数据。
    # 仅影响【读取】(本 ctx 喂的全是 KB lookup 工具);存档归属/写入另走原 script_id。
    from platform_app.knowledge._pin import effective_kb_script_id
    return {"script_id": effective_kb_script_id(db, row["script_id"]),
            "commit_id": row["active_commit_id"],
            "progress_chapter": progress, "mode": mode,
            "save_id": int(save_id)}  # P4:供 reveal_clause_v2 前沿门控(flag off 时不生效)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── 查询工具 ─────────────────────────────────────────────────────────────────
def _t_lookup_entity(user_id: int, args: dict) -> str:
    from kb import canon_repo, live_repo
    from platform_app.db import connect
    save_id = _int(args.get("save_id"))
    name = (args.get("name") or args.get("logical_key") or "").strip()
    if not save_id or not name:
        return "Failed: save_id and name are required"
    with connect() as db:
        ctx = _save_ctx(db, save_id, user_id)
        if not ctx:
            return "Failed: no access to this save"
        # 先查活态(玩家版优先),再规范
        live = {}
        if ctx["commit_id"]:
            for e in live_repo.read_entities(db, save_id, ctx["commit_id"]):
                if e["logical_key"] == name or e["name"] == name:
                    live = e
                    break
        canon = canon_repo.lookup_canon_entity(
            db, ctx["script_id"], name,
            progress_chapter=ctx["progress_chapter"], mode=ctx["mode"], save_id=ctx["save_id"],
        )
        if not live and not canon:
            # 按 name 模糊找规范
            cands = canon_repo.read_canon_entities(
                db, ctx["script_id"], progress_chapter=ctx["progress_chapter"], mode=ctx["mode"],
                limit=200, save_id=ctx["save_id"])
            canon = next((c for c in cands if c["name"] == name or name in (c.get("aliases") or [])), None)
        if not live and not canon:
            return f"Entity '{name}' not found (it may not have been revealed yet at the current progress)"
        # harness 兜底: 当 canon 的 summary/identity/background 都空(LLM 抽 item/concept
        # 类时常见 — 只填 name 没填释义),从 documents 表反查 name 命中段拼 source_excerpts。
        # 避免 GM 拿到 {name:"D20", summary:""} 时按训练数据脑补成 d&d 骰子。
        source_excerpts: list[str] = []
        if canon:
            text_fields = [
                canon.get("summary"), canon.get("identity"),
                canon.get("background"), canon.get("personality"),
            ]
            has_release = any(s and str(s).strip() for s in text_fields)
            if not has_release:
                # 限制 progress_chapter 内搜,防剧透
                first_ch = canon.get("first_revealed_chapter") or 1
                ch_max = min(int(ctx["progress_chapter"] or first_ch), int(first_ch) + 2)
                source_excerpts = _excerpt_from_documents(
                    db, ctx["script_id"], name,
                    aliases=canon.get("aliases") or [],
                    chapter_min=int(first_ch), chapter_max=int(ch_max),
                    max_excerpts=3, window_chars=200,
                )
        result = {
            "name": name, "canon": canon, "live_override": live or None,
            "source_excerpts": source_excerpts,  # 空数组也明确返回 — GM 知道工具尽力了
            "_note": "source_excerpts are +/-200-character snippets around matches of name in the source text, used as fallback factual grounding when the canon summary is empty" if source_excerpts else None,
        }
        return json.dumps(result, ensure_ascii=False, default=str)


def _excerpt_from_documents(
    db, script_id: int, name: str, *, aliases: list,
    chapter_min: int, chapter_max: int,
    max_excerpts: int = 3, window_chars: int = 200,
) -> list[str]:
    """从 documents.content 搜 name(+aliases)命中段,返回 ±window_chars 字符片段。

    限定章节范围 — first_revealed_chapter..+2,防止把后续剧情泄露给 GM。
    幂等纯函数,不动 DB。
    """
    try:
        terms = [name] + [a for a in (aliases or []) if isinstance(a, str) and a]
        rows = db.execute(
            "select sc.chapter_index, d.content from documents d "
            "join script_chapters sc on sc.id = d.chapter_id "
            "where d.script_id=%s and sc.chapter_index between %s and %s "
            "order by sc.chapter_index asc",
            (script_id, chapter_min, chapter_max),
        ).fetchall() or []
        out: list[str] = []
        for r in rows:
            content = r["content"] or ""
            for term in terms:
                idx = content.find(term)
                if idx < 0:
                    continue
                start = max(0, idx - window_chars)
                end = min(len(content), idx + len(term) + window_chars)
                snippet = content[start:end].strip()
                marker = f"[Chapter {r['chapter_index']} excerpt]"
                out.append(f"{marker} {snippet}")
                if len(out) >= max_excerpts:
                    return out
                break  # 一个 doc 只取首次命中
        return out
    except Exception:
        return []


def _t_search_canon(user_id: int, args: dict) -> str:
    from extract.embed import search_canon_by_vector
    from platform_app.db import connect
    from platform_app.knowledge.embedding import embed_query
    save_id = _int(args.get("save_id"))
    query = (args.get("query") or "").strip()
    k = min(int(args.get("k") or 6), 15)
    if not save_id or not query:
        return "Failed: save_id and query are required"
    with connect() as db:
        ctx = _save_ctx(db, save_id, user_id)
        if not ctx:
            return "Failed: no access to this save"
        # P0-fix: 传 script_id 的 embed meta，确保 query 向量与建库时相同
        from platform_app.knowledge._search import _get_script_embed_meta, _script_has_vectors
        # 先看这个剧本的规范实体有没有向量(没建过向量 / 桌面无 pgvector):没有就不嵌入查询,
        # 免得白打一次嵌入供应商再搜出空列表。与 _search / kb.recall 的存在性门同一口径。
        if not ctx.get("script_id") or not _script_has_vectors(db, int(ctx["script_id"]), "kb_canon_entities"):
            return "Search unavailable (this script has no vector index for canon entities yet)"
        _locked_api_id, _locked_model = _get_script_embed_meta(db, ctx["script_id"])
        qv = embed_query(
            query,
            user_id=user_id,
            force_api_id=_locked_api_id or None,
            force_model=_locked_model or None,
        )
        if not qv:
            return "Search unavailable (the embedding service is not ready)"
        hits = search_canon_by_vector(db, ctx["script_id"], qv, top_k=k,
                                      progress_chapter=ctx["progress_chapter"])
        return json.dumps([dict(h) for h in hits], ensure_ascii=False, default=str)


def _t_lookup_timeline(user_id: int, args: dict) -> str:
    from platform_app.db import connect
    save_id = _int(args.get("save_id"))
    if not save_id:
        return "Failed: save_id is required"
    label = (args.get("label") or "").strip()
    with connect() as db:
        ctx = _save_ctx(db, save_id, user_id)
        if not ctx:
            return "Failed: no access to this save"
        sql = ("select story_time_label, chapter_min, chapter_max, sample_summary "
               "from script_timeline_anchors where script_id=%s")
        a = [ctx["script_id"]]
        if ctx["progress_chapter"] is not None:
            sql += " and chapter_min <= %s"
            a.append(ctx["progress_chapter"])
        if label:
            sql += " and story_time_label ilike %s"
            a.append(f"%{label}%")
        sql += " order by chapter_min limit 20"
        rows = db.execute(sql, tuple(a)).fetchall()
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)


def _t_graph_neighbors(user_id: int, args: dict) -> str:
    from kb import live_repo
    from platform_app.db import connect
    save_id = _int(args.get("save_id"))
    entity = (args.get("entity") or "").strip()
    if not save_id or not entity:
        return "Failed: save_id and entity are required"
    with connect() as db:
        ctx = _save_ctx(db, save_id, user_id)
        if not ctx or not ctx["commit_id"]:
            return "Failed: no access, or the save has no commits"
        rels = live_repo.read_relationships(db, save_id, ctx["commit_id"])
        nb = [r for r in rels if r["from_key"] == entity or r["to_key"] == entity]
        return json.dumps(nb, ensure_ascii=False, default=str)


# ── 写工具(世界树 delta → kb_* 行) ─────────────────────────────────────────
def _require_commit(db, save_id: int, user_id: int):
    ctx = _save_ctx(db, save_id, user_id)
    if not ctx:
        return None, "Failed: no access to this save"
    if not ctx["commit_id"]:
        return None, "Failed: the save has no commits yet (cannot determine born_commit)"
    return ctx, None


def _t_kb_upsert_entity(user_id: int, args: dict) -> str:
    from kb import live_repo
    from platform_app.db import connect
    save_id = _int(args.get("save_id"))
    lk = (args.get("logical_key") or args.get("name") or "").strip()
    if not save_id or not lk:
        return "Failed: save_id and logical_key/name are required"
    with connect() as db:
        ctx, err = _require_commit(db, save_id, user_id)
        if err:
            return err
        _name = (args.get("name") or lk).strip()
        # 库扫描实锤(335 对同人两卡,「让」↔「让·保罗」):LLM 给的名字/键落库前必须过
        # 确定性归并——①canon 别名(化名/贬称→主名);②save 内 live 实体互为包含且唯一
        # 命中→归并到已有实体(COW 新行覆盖=更新),歧义(多命中)不猜保持原名。
        try:
            from kb.alias import canonical_name_for_save
            _cn = canonical_name_for_save(save_id, _name)
            if _cn and _cn != _name:
                _name = _cn
                lk = _cn
        except Exception:
            pass
        try:
            if len(_name) >= 2:
                _rows = db.execute(
                    "select distinct name, logical_key from kb_entities "
                    "where save_id=%s and status='live' and name <> %s "
                    "and (name like '%%' || %s || '%%' or %s like '%%' || name || '%%')",
                    (save_id, _name, _name, _name),
                ).fetchall()
                if len(_rows or []) == 1:
                    lk = _rows[0]["logical_key"]
                    _name = _rows[0]["name"]
        except Exception:
            pass
        live_repo.upsert_entity(
            db, save_id, ctx["commit_id"], lk,
            name=_name, type=(args.get("type") or "character"),
            status=(args.get("status") or "active"), summary=_sanitize_kb_text(args.get("summary")),
            attrs=args.get("attrs") if isinstance(args.get("attrs"), dict) else None,
            origin=(args.get("origin") or "player"),
        )
        return f"Updated entity '{lk}' (written to world-tree commit {ctx['commit_id']})"


def _t_kb_record_event(user_id: int, args: dict) -> str:
    from kb import live_repo
    from platform_app.db import connect
    save_id = _int(args.get("save_id"))
    summary = _sanitize_kb_text((args.get("summary") or "").strip())
    lk = (args.get("logical_key") or summary[:24]).strip()
    if not save_id or not summary:
        return "Failed: save_id and summary are required"
    with connect() as db:
        ctx, err = _require_commit(db, save_id, user_id)
        if err:
            return err
        live_repo.record_event(
            db, save_id, ctx["commit_id"], lk, summary=summary,
            story_time=(args.get("story_time") or ""),
            participants=args.get("participants") if isinstance(args.get("participants"), list) else None,
            location=(args.get("location") or ""),
        )
        return f"Recorded event '{summary[:40]}'"


def _t_kb_set_relationship(user_id: int, args: dict) -> str:
    from kb import live_repo
    from platform_app.db import connect
    save_id = _int(args.get("save_id"))
    frm = (args.get("from") or args.get("from_key") or "").strip()
    to = (args.get("to") or args.get("to_key") or "").strip()
    kind = (args.get("kind") or "").strip()
    if not save_id or not frm or not to:
        return "Failed: save_id / from / to are required"
    with connect() as db:
        ctx, err = _require_commit(db, save_id, user_id)
        if err:
            return err
        live_repo.set_relationship(db, save_id, ctx["commit_id"], f"{frm}->{to}",
                                   from_key=frm, to_key=to, kind=kind,
                                   note=_sanitize_kb_text(args.get("note"), 300))
        return f"Set relationship {frm}->{to}: {kind}"


def _t_kb_set_worldline_var(user_id: int, args: dict) -> str:
    from kb import live_repo
    from platform_app.db import connect
    save_id = _int(args.get("save_id"))
    key = (args.get("key") or args.get("logical_key") or "").strip()
    if not save_id or not key or "value" not in args:
        return "Failed: save_id / key / value are required"
    with connect() as db:
        ctx, err = _require_commit(db, save_id, user_id)
        if err:
            return err
        live_repo.set_worldline_var(db, save_id, ctx["commit_id"], key, value=args.get("value"))
        return f"Set worldline variable {key}={args.get('value')}"


# ── 注册 ─────────────────────────────────────────────────────────────────────
def _obj(props, required):
    return {"type": "object", "properties": props, "required": required}


def register_kb_tools() -> None:
    reg = get_registry()
    specs = [
        ToolSpec(name="lookup_entity", description="[KB query] Look up an entity's details by name (canon layer ∪ live layer, live takes precedence; filtered by player progress to avoid spoilers).",
                 input_schema=_obj({"save_id": {"type": "integer"}, "name": {"type": "string"}}, ["save_id", "name"]),
                 executor=_t_lookup_entity, scope="user", origins=_KB_READ_ORIGINS),
        ToolSpec(name="search_canon", description="[KB query] Semantic search over the canon lore/entities (pgvector, filtered by progress). Returns the top-k relevant entities.",
                 input_schema=_obj({"save_id": {"type": "integer"}, "query": {"type": "string"}, "k": {"type": "integer", "default": 6}}, ["save_id", "query"]),
                 executor=_t_search_canon, scope="user", origins=_KB_READ_ORIGINS),
        ToolSpec(name="lookup_timeline", description="[KB query] Look up canon timeline anchors (era/phase -> chapter range, filtered by progress).",
                 input_schema=_obj({"save_id": {"type": "integer"}, "label": {"type": "string"}}, ["save_id"]),
                 executor=_t_lookup_timeline, scope="user", origins=_KB_READ_ORIGINS),
        ToolSpec(name="graph_neighbors", description="[KB query] Look up an entity's relationship neighbors in the current save.",
                 input_schema=_obj({"save_id": {"type": "integer"}, "entity": {"type": "string"}}, ["save_id", "entity"]),
                 executor=_t_graph_neighbors, scope="user", origins=_KB_READ_ORIGINS),
        ToolSpec(name="kb_upsert_entity", description="[KB write] Create/update an entity (writes a world-tree delta stamped with born_commit). Use it when the player changes an NPC's state or creates a new entity.",
                 input_schema=_obj({"save_id": {"type": "integer"}, "logical_key": {"type": "string"}, "name": {"type": "string"}, "type": {"type": "string"}, "summary": {"type": "string"}}, ["save_id", "logical_key"]),
                 executor=_t_kb_upsert_entity, scope="user", origins=_KB_WRITE_ORIGINS),
        ToolSpec(name="kb_record_event", description="[KB write] Record an event that happened in this playthrough (writes a world-tree delta).",
                 input_schema=_obj({"save_id": {"type": "integer"}, "summary": {"type": "string"}, "participants": {"type": "array", "items": {"type": "string"}}, "location": {"type": "string"}}, ["save_id", "summary"]),
                 executor=_t_kb_record_event, scope="user", origins=_KB_WRITE_ORIGINS),
        ToolSpec(name="kb_set_relationship", description="[KB write] Set/change the relationship between two entities (writes a world-tree delta).",
                 input_schema=_obj({"save_id": {"type": "integer"}, "from": {"type": "string"}, "to": {"type": "string"}, "kind": {"type": "string"}}, ["save_id", "from", "to"]),
                 executor=_t_kb_set_relationship, scope="user", origins=_KB_WRITE_ORIGINS),
        ToolSpec(name="kb_set_worldline_var", description="[KB write] Set a worldline variable (writes a world-tree delta).",
                 input_schema=_obj({"save_id": {"type": "integer"}, "key": {"type": "string"}, "value": {}}, ["save_id", "key", "value"]),
                 executor=_t_kb_set_worldline_var, scope="user", origins=_KB_WRITE_ORIGINS),
    ]
    for s in specs:
        reg.replace(s)
