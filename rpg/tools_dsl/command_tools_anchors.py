"""
command_tools_anchors.py — task 136: 世界线收束机制 · GM 工具

公开 3 个 dispatcher 工具:
  list_pending_anchors      — GM 查看待发生的原著锚点
  mark_anchor_satisfied     — GM 标记某锚点已经发生 (按原著或变体)
  mark_anchor_superseded    — GM 标记某锚点被剧情绕过 (rare,需 reason)

允许 origin: llm_chat (GM 主要用户) + ui_button + api_direct + console_assistant。
注意 satisfied / superseded 是【非破坏性】的状态变更,GM 必须有权限调,否则
"原著事件按变体方式发生"这种判断没人记账,锚点会反复重复触发。
"""
from __future__ import annotations

import json

from tools_dsl._arg_guards import require_int_arg
from tools_dsl.command_dispatcher import ToolSpec, get_registry

_ANCHOR_READ_ORIGINS = frozenset({"ui_button", "api_direct", "console_assistant", "llm_chat", "llm_set"})
# GM 直接负责标记锚点状态, 必须给 llm_chat origin
_ANCHOR_MUTATE_ORIGINS = frozenset({"ui_button", "api_direct", "console_assistant", "llm_chat"})


# ────────────────────────────────────────────────────────────
# Tool executors
# ────────────────────────────────────────────────────────────


def _own_save(db, save_id: int, user_id: int) -> bool:
    # 归属判定收敛到 perms.owns_save(唯一来源);保留本名兼容 11+ 处调用。
    from platform_app.perms import owns_save
    return owns_save(db, save_id, user_id)


def _t_list_pending_anchors(user_id: int, args: dict) -> str:
    """list_pending_anchors — 列待发生锚点。

    args:
      save_id: 必填
      phase_label: 可选, 过滤当前阶段
      chapter_min / chapter_max: 可选, 章节窗口
      limit: 默认 5, 上限 20
      include_metadata: 默认 false, true 时附带 participants/locations/concepts
    """
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id_raw)
    phase_label = (args.get("phase_label") or "").strip() or None
    try:
        chapter_min = int(args.get("chapter_min")) if args.get("chapter_min") is not None else None
        chapter_max = int(args.get("chapter_max")) if args.get("chapter_max") is not None else None
    except (TypeError, ValueError):
        return "Failed: chapter_min / chapter_max must be integers"
    try:
        limit = int(args.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(20, limit))
    include_meta = bool(args.get("include_metadata"))

    try:
        from platform_app.db import connect, init_db
        init_db()
        # SEC(M-5): 整快照 read-modify-write 在 (user,save) 级锁内,防与并发 save 级写者互覆盖。
        from tools_dsl.command_dispatcher import _get_sync_scope_lock
        with _get_sync_scope_lock((int(user_id), save_id)), connect() as db:
            if not _own_save(db, save_id, user_id):
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
        from agents.anchor_seed_agent import list_pending_for_phase, summarize_save_anchor_state
        anchors = list_pending_for_phase(
            save_id, phase_label,
            limit=limit, chapter_min=chapter_min, chapter_max=chapter_max,
        )
        if not include_meta:
            for a in anchors:
                a.pop("metadata", None)
        summary = summarize_save_anchor_state(save_id)
        return json.dumps({
            "save_id": save_id,
            "filter": {
                "phase_label": phase_label,
                "chapter_min": chapter_min, "chapter_max": chapter_max,
                "limit": limit,
            },
            "pending_count_total": summary["pending"],
            "fatal_pending_count": summary["fatal_pending"],
            "occurred_count": summary["occurred"],
            "variant_count": summary["variant"],
            "superseded_count": summary["superseded"],
            "avg_drift": summary["avg_drift"],
            "anchors": anchors,
        }, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_mark_anchor_satisfied(user_id: int, args: dict) -> str:
    """mark_anchor_satisfied — 锚点已经发生。

    args:
      save_id: 必填
      anchor_key: 必填 (来自 list_pending_anchors 返回)
                  也支持 anchor_id (整数主键)
      how_it_happened: 必填,描述"实际怎么发生的"(可以是变体)
      drift_score: 可选 0.0-1.0, 默认 0.0 (完全按原著) / 0.5 (中度变体) / 1.0 (核心保留方式全变)
      occurred_at_turn: 可选,默认拿存档当前最大 turn
    """
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id_raw)
    anchor_key = (args.get("anchor_key") or "").strip()
    anchor_id_raw = args.get("anchor_id")
    if not anchor_key and anchor_id_raw is None:
        return "Failed: provide at least one of anchor_key or anchor_id"
    how = (args.get("how_it_happened") or "").strip()
    if not how:
        return "Failed: how_it_happened is required; describe how the event actually happened"
    if len(how) > 600:
        how = how[:600]
    try:
        drift = float(args.get("drift_score") if args.get("drift_score") is not None else 0.0)
    except (TypeError, ValueError):
        drift = 0.0
    drift = max(0.0, min(1.0, drift))
    new_status = "variant" if drift >= 0.15 else "occurred"
    try:
        occurred_turn = int(args.get("occurred_at_turn")) if args.get("occurred_at_turn") is not None else None
    except (TypeError, ValueError):
        return "Failed: occurred_at_turn must be an integer"

    try:
        from platform_app.db import connect, init_db
        init_db()
        # SEC(M-5): 整快照 read-modify-write 在 (user,save) 级锁内,防与并发 save 级写者互覆盖。
        from tools_dsl.command_dispatcher import _get_sync_scope_lock
        with _get_sync_scope_lock((int(user_id), save_id)), connect() as db:
            if not _own_save(db, save_id, user_id):
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
            # 默认 occurred_turn 从 branch_commits 最大值取
            if occurred_turn is None:
                r = db.execute(
                    "select coalesce(max(turn_index), 0) as t from branch_commits where save_id = %s",
                    (save_id,),
                ).fetchone()
                occurred_turn = int((r or {}).get("t") or 0)
            # 锁定锚点
            if anchor_key:
                row = db.execute(
                    """
                    select id, status, summary, source_chapter, anchor_key from save_anchor_states
                    where save_id = %s and anchor_key = %s
                    """,
                    (save_id, anchor_key),
                ).fetchone()
            else:
                row = db.execute(
                    """
                    select id, status, summary, source_chapter, anchor_key from save_anchor_states
                    where save_id = %s and id = %s
                    """,
                    (save_id, int(anchor_id_raw)),
                ).fetchone()
            if not row:
                return f"Failed: anchor not found (save={save_id}, key={anchor_key!r}, id={anchor_id_raw})"
            if row.get("status") in ("occurred", "variant"):
                return (
                    f"Note: anchor {anchor_key or row['id']} is already {row['status']}; nothing changed."
                    f" (To re-mark it, call mark_anchor_superseded first)"
                )
            db.execute(
                """
                update save_anchor_states set
                  status = %s,
                  variant_description = %s,
                  occurred_at_turn = %s,
                  drift_score = %s,
                  updated_at = now()
                where save_id = %s and id = %s
                """,
                (new_status, how, occurred_turn, drift, save_id, row["id"]),
            )
            # BUG-3: 锚点满足 = 玩家已推进到该锚点所在原著章节 → 同步玩家进度
            # (advance_progress 取 max 只增不减,幂等)。让 progress_chapter 真随剧情走,
            # 防剧透集合(Phase D canon_repo._reveal_clause + retrieval 层级图)随之扩。
            _src_ch = row.get("source_chapter")
            if isinstance(_src_ch, int) and _src_ch >= 1:
                try:
                    from gm_serving.settings import advance_progress
                    advance_progress(db, save_id, _src_ch)
                except Exception:
                    pass  # 进度同步失败不阻断锚点标记
            # P4(S6):写前沿(GM 声明到达 → 增量并入可见集)。同一 db 连接,原子;
            # flag off 时 _frontier_on 返 False → 不写,行为零变化。
            try:
                from kb.reveal import _frontier_on, mark_anchor_reached
                _akey = anchor_key or row.get("anchor_key")
                if _akey and _frontier_on(save_id):
                    mark_anchor_reached(save_id, _akey, turn=occurred_turn,
                                        via="gm", drift=drift, db=db)
            except Exception:
                pass  # 前沿写失败不阻断锚点标记
        # 反向级联(连接已释放后调,理由见 _cascade_history_from_anchor 文档串)
        _cascade_history_from_anchor(
            save_id, anchor_key=anchor_key or (row.get("anchor_key") or ""),
            anchor_summary=row.get("summary") or "", new_status=new_status,
            detail=how, turn_occurred=occurred_turn)
        return json.dumps({
            "ok": True,
            "anchor_id": row["id"],
            "anchor_key": anchor_key or None,
            "previous_status": row.get("status"),
            "new_status": new_status,
            "drift_score": drift,
            "occurred_at_turn": occurred_turn,
            "summary": row.get("summary", "")[:120],
        }, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_mark_anchor_superseded(user_id: int, args: dict) -> str:
    """mark_anchor_superseded — 锚点被剧情绕过, 永远不会按这个 anchor 发生了。
    例如玩家穿越前就阻止了某事件的前置条件。需要 reason。
    """
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id_raw)
    anchor_key = (args.get("anchor_key") or "").strip()
    anchor_id_raw = args.get("anchor_id")
    if not anchor_key and anchor_id_raw is None:
        return "Failed: provide at least one of anchor_key or anchor_id"
    reason = (args.get("reason") or "").strip()
    if not reason:
        return "Failed: reason is required (explain why this anchor can no longer happen)"
    if len(reason) > 600:
        reason = reason[:600]

    try:
        from platform_app.db import connect, init_db
        init_db()
        # SEC(M-5): 整快照 read-modify-write 在 (user,save) 级锁内,防与并发 save 级写者互覆盖。
        from tools_dsl.command_dispatcher import _get_sync_scope_lock
        with _get_sync_scope_lock((int(user_id), save_id)), connect() as db:
            if not _own_save(db, save_id, user_id):
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
            if anchor_key:
                row = db.execute(
                    "select id, status, is_fatal, summary, anchor_key from save_anchor_states "
                    "where save_id = %s and anchor_key = %s",
                    (save_id, anchor_key),
                ).fetchone()
            else:
                row = db.execute(
                    "select id, status, is_fatal, summary, anchor_key from save_anchor_states "
                    "where save_id = %s and id = %s",
                    (save_id, int(anchor_id_raw)),
                ).fetchone()
            if not row:
                return f"Failed: anchor not found (save={save_id}, key={anchor_key!r})"
            if row.get("is_fatal"):
                return (
                    "Refused: this is an is_fatal=true anchor (Final Destination mode); it must happen in principle "
                    "and cannot be superseded. Use mark_anchor_satisfied instead and describe "
                    "how it actually happened (a high drift_score is fine)."
                )
            if row.get("status") == "superseded":
                return "Note: the anchor is already superseded; nothing changed."
            db.execute(
                """
                update save_anchor_states set
                  status = 'superseded',
                  variant_description = %s,
                  drift_score = 1.0,
                  updated_at = now()
                where save_id = %s and id = %s
                """,
                (reason, save_id, row["id"]),
            )
        # 反向级联(连接已释放后调,理由见 _cascade_history_from_anchor 文档串)
        _cascade_history_from_anchor(
            save_id, anchor_key=anchor_key or (row.get("anchor_key") or ""),
            anchor_summary=row.get("summary") or "", new_status="superseded",
            detail=reason)
        return json.dumps({
            "ok": True,
            "anchor_id": row["id"],
            "anchor_key": anchor_key or None,
            "new_status": "superseded",
            "reason": reason,
        }, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


# ── 锚点脱离 pending → 自动补写历史锚点 ────────────────────────────────────────
# 缝已搬到 agents.save_history.cascade_history_from_anchor —— 因为真正在标锚点的不是
# 这条 GM 工具路径,而是 anchor_reconcile 的每回合确定性兜底(详见那边的注释)。
# 这里保留薄委托:GM 真的自己调工具时,记成 gm_generated。
def _cascade_history_from_anchor(save_id: int, *, anchor_key: str, anchor_summary: str,
                                 new_status: str, detail: str,
                                 turn_occurred: int | None = None) -> None:
    from agents.save_history import cascade_history_from_anchor
    cascade_history_from_anchor(
        save_id, anchor_key=anchor_key, anchor_summary=anchor_summary,
        new_status=new_status, detail=detail, turn_occurred=turn_occurred,
        source="gm_generated", via="gm_tool")


def _t_record_history_anchor(user_id: int, args: dict) -> str:
    """record_history_anchor — 写"存档独立时间线"里玩家创造的重要历史节点。
    跟 mark_anchor_satisfied(剧本未来锚点)是两套表两套语义。

    args:
      save_id           : 必填
      summary           : 必填,事件描述 (≤800 chars)
      importance        : 0-100, 默认 50 (建议 60 起留档)
      tags / characters / locations : list[str],可选
      linked_canon_keys / linked_pending_anchors : list[str],可选,关联到 KB / 剧本锚点
      ingame_chapter    : int 可选,玩家声明的"原著章节进度"
      source            : 'gm_generated' | 'player_declared',默认前者
    """
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    summary = (args.get("summary") or "").strip()
    if not summary:
        return "Failed: summary is required"
    # 安全围栏:save 必须属于当前用户(LLM 可在 args 注入任意 save_id;复用兄弟工具同款 _own_save)
    from platform_app.db import connect, init_db
    init_db()
    with connect() as db:
        if not _own_save(db, int(save_id_raw), user_id):
            return f"Failed (permission): save {int(save_id_raw)} does not belong to the current user or does not exist"
    try:
        from agents.save_history import record_history_anchor
        linked_pending = args.get("linked_pending_anchors") or []
        if not isinstance(linked_pending, list):
            linked_pending = []
        result = record_history_anchor(
            int(save_id_raw),
            summary=summary,
            importance=int(args.get("importance") or 50),
            story_time_label=(args.get("story_time_label") or "").strip(),
            ingame_chapter=args.get("ingame_chapter"),
            tags=args.get("tags") or None,
            characters=args.get("characters") or None,
            locations=args.get("locations") or None,
            linked_canon_keys=args.get("linked_canon_keys") or None,
            linked_pending_anchors=linked_pending or None,
            source=(args.get("source") or "gm_generated").strip(),
        )
        if not result.get("ok"):
            return f"Failed: {result.get('error', 'unknown')}"
        # iter#5: 级联自动 mark_anchor_satisfied — 用户的"大体对应,允许不同"诉求
        # linked_pending_anchors 非空 → 同事务里把对应 pending 标 satisfied,防止
        # 同事件【未来段 pending】+【过去段 history】双重注入,GM 看到自相矛盾上下文
        # 又触发一次(典型记忆污染)。
        cascade_results: list[str] = []
        if linked_pending:
            try:
                from platform_app.db import connect, init_db
                init_db()
                _drift = float(args.get("drift_score") or 0.5)  # history 改写默认为中度变体
                _drift = max(0.0, min(1.0, _drift))
                _new_status = "variant" if _drift >= 0.15 else "occurred"
                with connect() as db:
                    for ak in linked_pending:
                        ak_str = str(ak).strip()
                        if not ak_str:
                            continue
                        row = db.execute(
                            """
                            update save_anchor_states
                            set status = %s, drift_score = %s,
                                variant_description = %s,
                                occurred_at_turn = (select coalesce((state_snapshot->>'turn')::int, 0)
                                                    from game_saves where id = %s),
                                updated_at = now()
                            where save_id = %s and anchor_key = %s
                              and status = 'pending'
                            returning anchor_key, status
                            """,
                            (_new_status, _drift, summary[:240],
                             int(save_id_raw), int(save_id_raw), ak_str),
                        ).fetchone()
                        if row:
                            cascade_results.append(f"{ak_str}→{row['status']}")
            except Exception as casc_exc:
                cascade_results.append(f"[cascade failed: {type(casc_exc).__name__}: {casc_exc}]")
        cascade_str = (f" + cascaded pending marks: {', '.join(cascade_results)}"
                       if cascade_results else "")
        return (f"OK: history anchor written (id={result['id']}, turn={result['turn_occurred']}, "
                f"importance={result['importance']}){cascade_str}")
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_check_pending_anchor_drift(user_id: int, args: dict) -> str:
    """check_pending_anchor_drift — 反查指定 pending anchor 是否已被某条 history 改写。

    args:
      save_id     : 必填
      anchor_keys : 必填,list[str] 一批 anchor_key
    返回 JSON {anchor_key: [{turn, summary, importance, characters}]},
    空数组表示该 anchor 未被任何 history 改写,GM 仍应正常触发。
    """
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    aks = args.get("anchor_keys")
    if not isinstance(aks, list) or not aks:
        return "Failed: anchor_keys is required and must be a non-empty array"
    # 安全围栏:save 必须属于当前用户(防 LLM 注入异档 save_id 跨用户读)
    from platform_app.db import connect, init_db
    init_db()
    with connect() as db:
        if not _own_save(db, int(save_id_raw), user_id):
            return f"Failed (permission): save {int(save_id_raw)} does not belong to the current user or does not exist"
    try:
        from agents.save_history import find_history_for_pending
        result = find_history_for_pending(int(save_id_raw), [str(x) for x in aks])
        import json
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_list_recent_history(user_id: int, args: dict) -> str:
    """list_recent_history — 查存档最近的历史锚点 (按 turn 倒序)。

    args:
      save_id           : 必填
      limit             : 1-20,默认 8
      min_importance    : 只返 importance >= 此值的,默认 0
      character_filter  : 可选,只返 characters 含该名字的
    """
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    # 安全围栏:save 必须属于当前用户(防 LLM 注入异档 save_id 跨用户读)
    from platform_app.db import connect, init_db
    init_db()
    with connect() as db:
        if not _own_save(db, int(save_id_raw), user_id):
            return f"Failed (permission): save {int(save_id_raw)} does not belong to the current user or does not exist"
    try:
        from agents.save_history import list_recent_history
        items = list_recent_history(
            int(save_id_raw),
            limit=int(args.get("limit") or 8),
            min_importance=int(args.get("min_importance") or 0),
            character_filter=args.get("character_filter") or None,
        )
        import json
        return json.dumps(items, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_summarize_anchors(user_id: int, args: dict) -> str:
    """summarize_anchors — 当前存档的整体锚点收束状态。"""
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id_raw)
    try:
        from platform_app.db import connect, init_db
        init_db()
        # SEC(M-5): 整快照 read-modify-write 在 (user,save) 级锁内,防与并发 save 级写者互覆盖。
        from tools_dsl.command_dispatcher import _get_sync_scope_lock
        with _get_sync_scope_lock((int(user_id), save_id)), connect() as db:
            if not _own_save(db, save_id, user_id):
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
        from agents.anchor_seed_agent import summarize_save_anchor_state
        s = summarize_save_anchor_state(save_id)
        return json.dumps(s, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────
# Registration
# ────────────────────────────────────────────────────────────


def _t_claim_protagonist_pov(user_id: int, args: dict) -> str:
    """claim_protagonist_pov — 玩家显式声明「我就是原作主角 X」(灵魂占据 X 的身体)。

    **重要语义边界**:
    isekai 默认设定是「玩家用 自定义角色卡 的肉身 + 现代灵魂,与原作主角【平行共存】」 —
    爱丽丝(原作主角)应作为独立 NPC 触发她自己的登场 anchor,杭雁菱(玩家)在同一场景平行加入。

    本工具**只在玩家显式声明** "我就是 X / 我占据了 X 的身体 / 灵魂寄宿在 X 身上"
    这种**主角身份覆盖**情境下由 GM 主动调用。**不要默认调用**。

    调用效果:
      · 找指定原作主角 X (或 importance 第 1 character 作为兜底)
      · 把 "X(character)首次登场" 类 pending anchor 标记 satisfied
        (drift=0, resolution='玩家声明自己就是 X')
      · player.aliases 加入 X (GM 看到 "X" 这个名字时知道指向玩家)
      · player_meta.pov_replaces 加入 X (结构化关系,后续工具可查)

    幂等可重复调。

    args:
      save_id: 必填
      original_protag_name: 强烈建议显式传 — 不传按 type='character' importance desc 第 1 取兜底
    """
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id_raw)
    explicit_name = (args.get("original_protag_name") or "").strip()
    try:
        from psycopg.types.json import Jsonb

        from platform_app.db import connect, init_db
        init_db()
        # SEC(M-5): 整快照 read-modify-write 在 (user,save) 级锁内,防与并发 save 级写者互覆盖。
        from tools_dsl.command_dispatcher import _get_sync_scope_lock
        with _get_sync_scope_lock((int(user_id), save_id)), connect() as db:
            if not _own_save(db, save_id, user_id):
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
            # 1. 拿 script_id
            sr = db.execute(
                "select script_id, state_snapshot from game_saves where id=%s", (save_id,),
            ).fetchone()
            if not sr:
                return "Failed: save does not exist"
            script_id = int(sr["script_id"])
            state = sr["state_snapshot"] if isinstance(sr["state_snapshot"], dict) else {}
            # 2. 找原作主角
            name = explicit_name
            if not name:
                r = db.execute(
                    "select name from kb_canon_entities where script_id=%s and type='character' "
                    "order by importance desc nulls last limit 1",
                    (script_id,),
                ).fetchone()
                if r:
                    name = r["name"]
            if not name:
                return "Failed: original protagonist not found (the script may not have run canon_extract yet)"
            # 3. 找该主角的"首次登场"类 pending anchors
            #    匹配:summary 含 "X(character)首次登场" OR must_preserve::text 含 "X 参与"
            rows = db.execute(
                """select id, anchor_key, summary, status from save_anchor_states
                   where save_id=%s and status='pending'
                     and (summary like %s or must_preserve::text like %s)""",
                (save_id, f"%{name}(character)首次登场%", f"%{name} 参与%"),
            ).fetchall() or []
            # 4. mark satisfied
            satisfied = []
            for r in rows:
                db.execute(
                    """update save_anchor_states set
                         status='occurred', drift_score=0.0,
                         variant_description=%s, updated_at=now()
                       where id=%s and save_id=%s""",
                    # 签名 "takes over {name}'s POV position" 是 revoke 反查的契约(老中文签名见 revoke)
                    (f"The player, as '{state.get('player', {}).get('name', 'the player')}', takes over {name}'s POV position - the protagonist's entrance is the player's entrance", r["id"], save_id),
                )
                satisfied.append({"anchor_id": r["id"], "anchor_key": r["anchor_key"], "summary": (r["summary"] or "")[:120]})
            # 5. 把原作主角名加进 player.aliases (持久化到 state_snapshot)
            player = state.setdefault("player", {})
            aliases = player.get("aliases") or []
            if isinstance(aliases, str):
                # 老存档 aliases 可能是字符串
                aliases = [a.strip() for a in aliases.split(",") if a.strip()]
            if name not in aliases:
                aliases.append(name)
            player["aliases"] = aliases
            # 也记录到 pov_replaces 元字段(让 GM 查 lookup_player_pov 时能拿到结构化关系)
            player_meta = state.setdefault("player_meta", {})
            pov_list = player_meta.get("pov_replaces") or []
            if name not in pov_list:
                pov_list.append(name)
            player_meta["pov_replaces"] = pov_list
            db.execute(
                "update game_saves set state_snapshot=%s, updated_at=now() where id=%s",
                (Jsonb(state), save_id),
            )
        return json.dumps({
            "ok": True,
            "original_protag_name": name,
            "satisfied_anchors": satisfied,
            "satisfied_count": len(satisfied),
            "player_aliases_added": name,
        }, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_revoke_protagonist_pov(user_id: int, args: dict) -> str:
    """revoke_protagonist_pov — 撤销玩家代入原作主角 X 的状态(claim_protagonist_pov 的逆操作)。

    把因 claim 操作而标 satisfied 的 anchor 重置 pending,清 player.aliases 里的 X 项,
    清 player_meta.pov_replaces 里的 X。

    场景:误调 claim 后撤销,或玩家从"我就是 X" 转变为 "我是独立穿越者跟 X 平行"。

    args:
      save_id: 必填
      original_protag_name: 必填 — 要撤销哪个原作主角的 POV 声明
    """
    save_id_raw = args.get("save_id")
    _chk = require_int_arg(save_id_raw, "save_id")
    if isinstance(_chk, str):
        return _chk
    save_id = int(save_id_raw)
    name = (args.get("original_protag_name") or "").strip()
    if not name:
        return "Failed: original_protag_name is required"
    try:
        from psycopg.types.json import Jsonb

        from platform_app.db import connect, init_db
        init_db()
        # SEC(M-5): 整快照 read-modify-write 在 (user,save) 级锁内,防与并发 save 级写者互覆盖。
        from tools_dsl.command_dispatcher import _get_sync_scope_lock
        with _get_sync_scope_lock((int(user_id), save_id)), connect() as db:
            if not _own_save(db, save_id, user_id):
                return f"Failed (permission): save {save_id} does not belong to the current user or does not exist"
            # 1. 把 claim 标记过的 anchor 重置 pending。
            #    BUG 修复:原来用 `summary like '%X(character)首次登场%' AND variant_description like`,
            #    但 claim 是按 (summary OR must_preserve like '%X 参与%') 标记的 —— 靠 must_preserve
            #    命中(summary 无"首次登场")的锚点会被 claim 标 occurred 却永不被 revoke 重置,
            #    POV 切回后原著事件永久吞失。改为只按 claim 自己写的 variant_description 签名
            #    "代入 {name} 的 POV 位置"(claim 给所有标记锚点统一写入)精确反查,与 claim 镜像。
            rows = db.execute(
                """select id, anchor_key, summary, status, variant_description
                   from save_anchor_states
                   where save_id=%s and status in ('occurred','variant')
                     and (variant_description like %s or variant_description like %s)""",
                # 中英两种签名都认:老存档是中文签名,claim 现写英文签名
                (save_id, f"%代入 {name} 的 POV 位置%", f"%takes over {name}'s POV position%"),
            ).fetchall() or []
            reverted = []
            for r in rows:
                db.execute(
                    """update save_anchor_states set
                         status='pending', drift_score=0.0,
                         variant_description='', occurred_at_turn=NULL, updated_at=now()
                       where id=%s and save_id=%s""",
                    (r["id"], save_id),
                )
                reverted.append({"anchor_id": r["id"], "anchor_key": r["anchor_key"], "summary": (r["summary"] or "")[:80]})
            # 2. 从 player.aliases / player_meta.pov_replaces 移除 X
            sr = db.execute(
                "select state_snapshot from game_saves where id=%s", (save_id,),
            ).fetchone()
            state = sr["state_snapshot"] if isinstance(sr["state_snapshot"], dict) else {}
            player = state.setdefault("player", {})
            aliases = player.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(",") if a.strip()]
            aliases = [a for a in aliases if a != name]
            player["aliases"] = aliases
            player_meta = state.setdefault("player_meta", {})
            pov_list = player_meta.get("pov_replaces") or []
            pov_list = [x for x in pov_list if x != name]
            player_meta["pov_replaces"] = pov_list
            db.execute(
                "update game_saves set state_snapshot=%s, updated_at=now() where id=%s",
                (Jsonb(state), save_id),
            )
        return json.dumps({
            "ok": True,
            "original_protag_name": name,
            "reverted_anchors": reverted,
            "reverted_count": len(reverted),
            "player_aliases_after": aliases,
            "pov_replaces_after": pov_list,
        }, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _anchor_worldline_specs() -> list:
    return [
        ToolSpec(
            name="list_pending_anchors",
            description=(
                "[Worldline convergence] List the canon anchor events still pending in the current save. "
                "The GM should call it every few turns to learn which key events 'the script requires but have not happened yet', "
                "and actively design scenes that steer the story toward them. Returns a list sorted by importance desc, "
                "with anchor_key / chapter / summary / must_preserve / may_vary / is_fatal. "
                "is_fatal=true means Final Destination mode - any attempt by the player to prevent it triggers it another way."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                    "phase_label": {"type": "string", "description": "Optional; only anchors in this phase"},
                    "chapter_min": {"type": "integer", "description": "Optional; lower bound of the chapter range"},
                    "chapter_max": {"type": "integer", "description": "Optional; upper bound of the chapter range"},
                    "limit": {"type": "integer", "description": "Number of results (1-20), default 5", "default": 5},
                    "include_metadata": {"type": "boolean", "description": "When true, include participants/locations; default false"},
                },
                "required": ["save_id"],
            },
            executor=_t_list_pending_anchors,
            scope="user",
            origins=_ANCHOR_READ_ORIGINS,
            destructive=False,
            input_examples=[
                {"save_id": 1, "limit": 5},
                {"save_id": 1, "phase_label": "Berlin undercurrent arc", "limit": 3},
                {"save_id": 1, "chapter_min": 10, "chapter_max": 30},
            ],
        ),
        ToolSpec(
            name="mark_anchor_satisfied",
            description=(
                "[Worldline convergence] Mark a canon anchor as having happened in this save. "
                "drift_score=0 means it happened exactly as in canon; with drift_score>=0.15 the status becomes variant "
                "(happened as a variant: the core is preserved but the details differ). how_it_happened is required: "
                "describe how this event happened in this save (it is logged for later audit)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                    "anchor_key": {"type": "string", "description": "Anchor key (e.g. 'chapter:12:event:3')"},
                    "anchor_id": {"type": "integer", "description": "Or the anchor's primary-key id (one of anchor_key / anchor_id)"},
                    "how_it_happened": {"type": "string", "description": "Description of how the event actually happened"},
                    "drift_score": {"type": "number", "description": "0.0-1.0, how far it deviates from canon"},
                    "occurred_at_turn": {"type": "integer", "description": "Optional; defaults to the save's current turn"},
                },
                "required": ["save_id", "how_it_happened"],
            },
            executor=_t_mark_anchor_satisfied,
            scope="user",
            origins=_ANCHOR_MUTATE_ORIGINS,
            destructive=False,
            input_examples=[
                {"save_id": 1, "anchor_key": "chapter:12:event:0",
                 "how_it_happened": "Muriel reveals the heretic intel to the MC in the underground garage instead of the canon bathhouse scene",
                 "drift_score": 0.3},
                {"save_id": 1, "anchor_key": "chapter:7:event:2",
                 "how_it_happened": "Exactly as in canon - the Kaiserin orders the northern intelligence station cleared that night", "drift_score": 0.0},
            ],
        ),
        ToolSpec(
            name="mark_anchor_superseded",
            description=(
                "[Worldline convergence] Mark a canon anchor as bypassed by the story: it will never happen as this anchor describes. "
                "is_fatal=true anchors [refuse] to be superseded (Final Destination mode cannot be bypassed). "
                "Use it carefully even for non-fatal anchors - most deviations should be recorded with mark_anchor_satisfied plus a drift_score."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                    "anchor_key": {"type": "string", "description": "Anchor key"},
                    "anchor_id": {"type": "integer", "description": "Or the anchor's primary-key id"},
                    "reason": {"type": "string", "description": "Why this anchor can no longer happen (required)"},
                },
                "required": ["save_id", "reason"],
            },
            executor=_t_mark_anchor_superseded,
            scope="user",
            origins=_ANCHOR_MUTATE_ORIGINS,
            destructive=False,
            input_examples=[
                {"save_id": 1, "anchor_key": "chapter:18:event:1",
                 "reason": "The MC intercepted Toulouse's secret order 6 chapters early, so the event's preconditions no longer exist"},
            ],
        ),
        ToolSpec(
            name="record_history_anchor",
            description=(
                "[Save-specific timeline] Record an important historical milestone the player created in this worldline (past tense). "
                "Different from mark_anchor_satisfied - that one marks [canon] anchors; this tool records new events [created by the player] "
                "that need not correspond to any canon anchor. Suggested importance: 60+ changes an NPC relationship / faction stance, "
                "80+ rewrites a canon anchor (linked_pending_anchors non-empty), 90+ introduces a new character/faction. "
                "No need to call it every turn - state.history already covers the running log; only record events that are important enough."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                    "summary": {"type": "string", "description": "Event description, past tense, <= 800 characters"},
                    "importance": {"type": "integer", "description": "0-100, >= 60 recommended", "default": 60},
                    "story_time_label": {"type": "string", "description": "The save's world.time when the event happened; may be empty"},
                    "ingame_chapter": {"type": "integer", "description": "Source-chapter progress declared by the player"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tag array, e.g. ['politics', 'transmigrator leak']"},
                    "characters": {"type": "array", "items": {"type": "string"}, "description": "Names of the characters involved"},
                    "locations": {"type": "array", "items": {"type": "string"}, "description": "Locations involved"},
                    "linked_canon_keys": {"type": "array", "items": {"type": "string"}, "description": "Linked canon entity logical_keys"},
                    "linked_pending_anchors": {"type": "array", "items": {"type": "string"}, "description": "**Strongly encouraged**: if a canon anchor was rewritten, you must fill in its anchor_key (this tool then syncs mark_anchor_satisfied automatically, so the GM does not see it still pending next turn and trigger it again)."},
                    "drift_score": {"type": "number", "minimum": 0, "maximum": 1, "description": "If linked_pending_anchors is non-empty, the drift_score used for the cascaded marks (0 = as in canon, 1 = core kept but everything else changed); default 0.5"},
                    "source": {"type": "string", "enum": ["gm_generated", "player_declared"], "default": "gm_generated"},
                },
                "required": ["save_id", "summary"],
            },
            executor=_t_record_history_anchor,
            scope="user",
            origins=_ANCHOR_MUTATE_ORIGINS,
            destructive=False,
            input_examples=[
                {"save_id": 2, "summary": "At the Persian royal palace the MC told the king that a world war would break out in 1914; the king called an emergency cabinet meeting",
                 "importance": 75, "tags": ["politics", "transmigrator leak"], "characters": ["King of Persia"], "locations": ["Persian royal palace"]},
                {"save_id": 2, "summary": "The MC saved Lin Youde, who was assassinated in canon, rewriting the crater assassination event",
                 "importance": 90, "characters": ["Lin Youde"], "linked_pending_anchors": ["chapter:162:event:0"]},
            ],
        ),
        ToolSpec(
            name="check_pending_anchor_drift",
            description=(
                "[Worldline convergence] Reverse-look-up whether the given pending anchors have been rewritten by some history entry (reverse lookup of linked_pending_anchors). "
                "Use it to investigate the suspicion 'why did retrieve_context inject this pending anchor when I think it already happened?'. "
                "Returns, per anchor, its history entries (top 3 by turn desc); an empty array means not rewritten. "
                "The GM usually need not call it - retrieve_context already marks ⚠ and shows drift_marker when injecting."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer"},
                    "anchor_keys": {"type": "array", "items": {"type": "string"},
                                    "description": "Array of anchor_keys to look up"},
                },
                "required": ["save_id", "anchor_keys"],
            },
            executor=_t_check_pending_anchor_drift,
            scope="user",
            origins=_ANCHOR_READ_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="list_recent_history",
            description=(
                "[Save-specific timeline] List this save's recent history anchors (by turn desc). "
                "The GM should call it once at the start of each turn to learn [what the player has already done in this worldline], "
                "avoiding repeated narration or contradictions with established facts (memory-pollution guard). "
                "Returns list[{turn, summary, importance, tags, characters, locations, linked_anchors}]."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                    "limit": {"type": "integer", "description": "Number of results, default 8", "default": 8},
                    "min_importance": {"type": "integer", "description": "Only return entries with importance >= this value", "default": 0},
                    "character_filter": {"type": "string", "description": "Optional; only return entries involving this character"},
                },
                "required": ["save_id"],
            },
            executor=_t_list_recent_history,
            scope="user",
            origins=_ANCHOR_READ_ORIGINS,
            destructive=False,
            input_examples=[
                {"save_id": 2, "limit": 5},
                {"save_id": 2, "character_filter": "Lin Youde", "min_importance": 60},
            ],
        ),
        ToolSpec(
            name="summarize_anchors",
            description=(
                "[Worldline convergence] Return the current save's overall anchor convergence status: counts of pending / occurred / variant / superseded, "
                "the number of fatal_pending, and avg_drift. The GM can call it occasionally to check overall drift."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                },
                "required": ["save_id"],
            },
            executor=_t_summarize_anchors,
            scope="user",
            origins=_ANCHOR_READ_ORIGINS,
            destructive=False,
        ),
    ]


def _anchor_pov_specs() -> list:
    return [
        ToolSpec(
            name="revoke_protagonist_pov",
            description=(
                "[Protagonist identity override - undo] The inverse of claim_protagonist_pov. "
                "Resets the 'X first appears' anchors that the claim marked satisfied back to pending, "
                "and removes X from player.aliases / pov_replaces. "
                "Use it to correct a mistaken call or when the player's identity semantics change."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer"},
                    "original_protag_name": {"type": "string"},
                },
                "required": ["save_id", "original_protag_name"],
            },
            executor=_t_revoke_protagonist_pov,
            scope="user",
            origins=_ANCHOR_MUTATE_ORIGINS,
            destructive=False,
            input_examples=[{"save_id": 3, "original_protag_name": "Alice"}],
        ),
        ToolSpec(
            name="claim_protagonist_pov",
            description=(
                "[Protagonist identity override] The player **explicitly declares** 'I am the original protagonist X' (their soul occupies X's body).\n\n"
                "**Important boundary**: isekai defaults to 'the player's own character card + a modern soul, [coexisting in parallel] with the original protagonist' - \n"
                "the original protagonist appears normally as an independent NPC and the player joins the same scenes alongside them. **Do not call this tool by default**.\n\n"
                "**The GM should call it only when**:\n"
                "  · the player says outright 'I am X' / 'I took over X's body' / 'my soul is in X'\n"
                "  · the player picked a user_card explicitly marked as an alias of a canon character\n\n"
                "Effect: pending anchors of the 'X(character) first appearance' kind -> satisfied (drift=0),\n"
                "X is added to player.aliases and player_meta.pov_replaces. Idempotent; safe to repeat."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer", "description": "Target save id"},
                    "original_protag_name": {
                        "type": "string",
                        "description": "Optional; the original protagonist's name (exact match on kb_canon_entities.name). If omitted, the top type='character' entity by importance desc is used.",
                    },
                },
                "required": ["save_id"],
            },
            executor=_t_claim_protagonist_pov,
            scope="user",
            origins=_ANCHOR_MUTATE_ORIGINS,
            destructive=False,
            input_examples=[
                {"save_id": 3},  # 默认按 importance 取
                {"save_id": 3, "original_protag_name": "Alice"},
            ],
        ),
    ]


def register_anchor_tools() -> None:
    registry = get_registry()
    specs = [*_anchor_worldline_specs(), *_anchor_pov_specs()]
    for spec in specs:
        if not registry.has(spec.name):
            registry.register(spec)


__all__ = ["register_anchor_tools"]
