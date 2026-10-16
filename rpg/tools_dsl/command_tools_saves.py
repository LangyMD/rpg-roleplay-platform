"""
command_tools_saves.py — task 87 Phase 2.2: saves / branches user 级工具表。

把 /api/saves/* 和 /api/branches/* 系列改造成 LLM 可调工具:

  user 级 (scope="user"):
    list_my_saves          列出当前用户所有存档
    activate_save          激活某个存档 (切档,会 drain 当前队列)
    rename_save            重命名存档
    delete_save            **destructive** 删档,仅 ui_button
    list_branches          列出某存档的所有分支
    activate_branch        激活分支
    delete_branch          **destructive** 删分支,仅 ui_button
    continue_branch        从某 turn 创建新分支

注意:
  · 所有工具 executor 签名 (user_id, args) — dispatcher 通过 scope="user"
    自动注入 user_id,不需要 GameState。
  · DB 操作走 platform_app.db / platform_app.branches。
  · destructive 操作只允许 ui_button + api_direct,不允许 llm_chat / llm_set。
"""
from __future__ import annotations

from typing import Any

from tools_dsl._arg_guards import require_int_arg
from tools_dsl.command_dispatcher import ToolSpec, get_registry

# task 87 Phase 7 安全审查:跨"世界泡"隔离
# task 48 新增 console_assistant:控制台助手是「用户带方向盘的 agent」,
# 它的工具调用语义上等同于「用户在 UI 上点了相应按钮」(read 自由,mutate 直接执行,
# destructive 由 endpoint 层做二次确认)。
# user 级 read 工具:列存档/列分支/查存档详情等 → 任意 origin (含 LLM 与 console_assistant)
_USER_ORIGINS_READ = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat", "console_assistant",
})
# user 级 mutate 工具:激活/改名/切分支等会**影响后续 chat 路由的另一个 save** →
# LLM 任何 origin 都不允许 (即使玩家 /set 也不允许跨 save 操作)。
# console_assistant 允许 (它就是用来帮用户管 save 的)。
_USER_ORIGINS_MUTATE = frozenset({"ui_button", "api_direct", "console_assistant"})
# Destructive 同上,即使删自己当前 save 也是破坏性。console_assistant 允许,
# 但 /api/console_assistant/chat 在调度前会先 yield confirmation_required 等用户确认。
_USER_ORIGINS_DESTRUCTIVE = frozenset({"ui_button", "api_direct", "console_assistant"})


def _t_create_save(user_id: int, args: dict) -> str:
    """task 48: 基于 script_id 创建一个新存档。

    复用 platform_app.workspace.create_save (与 POST /api/saves 同源)。
    args:
      script_id    : 必填,基于哪个剧本建档
      title        : 可选,存档标题(空字符串则 workspace 自动给 "新存档")
      script_card_id : 可选,选用该剧本里的某张角色卡 (映射 character_kind="script_card")
      persona_id   : 可选,选用该用户某个 persona (映射 character_kind="persona")
    返回字符串 "save 创建: id=X title='...' script=Y"。
    """
    script_id = args.get("script_id")
    _chk = require_int_arg(script_id, "script_id", fail="Failed: script_id is required and must be an integer")
    if isinstance(_chk, str):
        return _chk
    title = (args.get("title") or "").strip()
    character: dict[str, Any] | None = None
    if args.get("script_card_id") is not None:
        character = {"kind": "script_card", "id": args.get("script_card_id")}
    elif args.get("persona_id") is not None:
        character = {"kind": "persona", "id": args.get("persona_id")}
    elif args.get("user_card_id") is not None:
        character = {"kind": "user_card", "id": args.get("user_card_id")}
    try:
        from platform_app import workspace as _ws
        save = _ws.create_save(
            user_id=int(user_id),
            script_id=int(script_id),
            title=title,
            new_card=None,
            character=character,
        )
        # 失效缓存,UI 切档时能拿到新 save
        try:
            import app as _ui
            _ui._invalidate_user_cache({"id": int(user_id)})
        except Exception:
            pass
        sid = (save or {}).get("id") or "?"
        stitle = (save or {}).get("title") or title or "New save"
        # task 112: 工具结果带强 hint, 让 LLM 不要在用户说"最新/刚才创建的"时
        # 还问选择 — 答案就是这个 sid。
        return (
            f"Save created: id={sid} title={stitle!r} script={script_id}. "
            f"Hint: this is the most recently created save in the user's session; when the user says "
            f"'the latest one' / 'the one I just created' / 'that one above', they mean id={sid}. Do not ask the user to choose again."
        )
    except ValueError as exc:
        return f"Failed (permission): {exc}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_list_my_usage(user_id: int, args: dict) -> str:
    """task 119: 查当前用户的 token 用量/成本/请求数(按天/周/月窗口)。

    page=Usage 时用户说"统计/给我看/汇总一下用量"应直接调本工具,而不是 ui_set_field。
    """
    days = int(args.get("days") or 30)
    if days <= 0 or days > 365:
        days = 30
    try:
        from platform_app import usage as _usage
        data = _usage.aggregate_usage(int(user_id), days=days)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"
    if not data:
        return f"No usage recorded in the past {days} days."
    requests = int(data.get("requests", 0) or 0)
    in_tk = int(data.get("input_tokens", 0) or 0)
    out_tk = int(data.get("output_tokens", 0) or 0)
    cost = float(data.get("cost_usd", 0) or 0)
    avg_lat = data.get("avg_latency_ms")
    err_rate = data.get("error_rate")
    by_api = data.get("by_api") or []
    by_model = data.get("by_model") or []
    daily_avg = (requests / max(days, 1))
    lines = [
        f"Usage summary for the past {days} days:",
        f"- Requests: {requests} (daily average {daily_avg:.1f})",
        f"- Tokens: input {in_tk:,} / output {out_tk:,} (ratio {in_tk / max(out_tk, 1):.1f}:1)",
        f"- Cost: ${cost:.4f}",
    ]
    if avg_lat is not None:
        lines.append(f"- Average latency: {avg_lat} ms")
    if err_rate is not None:
        lines.append(f"- Error rate: {err_rate}%")
    if by_api:
        lines.append("By API:")
        for r in by_api[:5]:
            lines.append(f"  · {r.get('api','-')}: {r.get('requests',0)} requests · ${float(r.get('cost_usd', 0) or 0):.4f}")
    if by_model:
        lines.append("By model (top 5):")
        for r in by_model[:5]:
            lines.append(f"  · {r.get('model','-')} (via {r.get('api','-')}): {r.get('requests',0)} requests · ${float(r.get('cost_usd', 0) or 0):.4f}")
    return "\n".join(lines)


def _t_list_my_saves(user_id: int, args: dict) -> str:
    script_id = args.get("script_id")
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if script_id:
                rows = db.execute(
                    "select id, title, script_id, updated_at, created_at "
                    "from game_saves where user_id = %s and script_id = %s "
                    "order by updated_at desc limit 50",
                    (user_id, int(script_id)),
                ).fetchall()
            else:
                rows = db.execute(
                    "select id, title, script_id, updated_at, created_at "
                    "from game_saves where user_id = %s "
                    "order by updated_at desc limit 50",
                    (user_id,),
                ).fetchall()
        if not rows:
            return "(no saves)"
        # task 112: 排序明示 + 时间 + "最新"标记, 让 LLM 不需再问"哪个最新"
        lines = [
            f"{len(rows)} saves in total (sorted by updated_at desc, **the first one is the latest**):"
        ]
        for i, r in enumerate(rows[:20]):
            ts = r.get("updated_at") or r.get("created_at")
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts else "")
            tag = " **[latest]**" if i == 0 else ""
            lines.append(
                f"  · id={r['id']} title={r.get('title') or '(untitled)'} "
                f"script={r.get('script_id')} updated_at={ts_str}{tag}"
            )
        if len(rows) > 20:
            lines.append(f"  ...({len(rows) - 20} more)")
        lines.append(
            "Hint: when the user says 'the latest' / 'the one I just created' / 'that one above' -> use the id on the first line; do not ask the user to choose."
        )
        return "\n".join(lines)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_activate_save(user_id: int, args: dict) -> str:
    save_id = args.get("save_id")
    _chk = require_int_arg(save_id, "save_id", fail="Failed: save_id must be an integer")
    if isinstance(_chk, str):
        return _chk
    try:
        from platform_app import branches as _branches
        result = _branches.activate_save(int(user_id), int(save_id))
        # 同步清 app.py 的 user state cache,跨模块耦合
        try:
            import app as _ui
            _ui._invalidate_user_cache({"id": int(user_id)})
        except Exception:
            pass
        # task 110: 激活成功后, 在工具返回里强提示 LLM 必须接着 navigate_to_setting
        # 跳到 game_console (否则用户停在 Platform 看不到剧本)。
        return (
            f"Activated save {save_id} ✓ (active_commit={result.get('active_commit_id', '?')}). "
            f"Next step: if the user wants to 'enter the game / start playing', you must call "
            f"navigate_to_setting(target='game_console', reason='Enter the game') to switch pages."
        )
    except ValueError as exc:
        return f"Failed (permission): {exc}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_rename_save(user_id: int, args: dict) -> str:
    save_id = args.get("save_id")
    title = (args.get("title") or "").strip()
    _chk = require_int_arg(save_id, "save_id", fail="Failed: save_id must be an integer")
    if isinstance(_chk, str):
        return _chk
    if not title:
        return "Failed: title must not be empty"
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            owned = db.execute(
                "select 1 from game_saves where id = %s and user_id = %s",
                (int(save_id), user_id),
            ).fetchone()
            if not owned:
                return "Failed (permission): this save does not belong to the current user"
            db.execute(
                "update game_saves set title = %s, updated_at = now() where id = %s",
                (title, int(save_id)),
            )
        return f"Renamed save {save_id} -> {title!r}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_delete_save(user_id: int, args: dict) -> str:
    save_id = args.get("save_id")
    _chk = require_int_arg(save_id, "save_id", fail="Failed: save_id must be an integer")
    if isinstance(_chk, str):
        return _chk
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            # task 120: 先查 save 归属 (select 1 快速存在性校验)
            owned = db.execute(
                "select 1 from game_saves where id = %s and user_id = %s",
                (int(save_id), user_id),
            ).fetchone()
            if not owned:
                return f"Failed (permission/not found): save_id={save_id} does not belong to the current user or no longer exists. **Do not claim it was 'deleted'**: nothing was done to this ID."
            # task 120: 拿 turn 信息警告高价值存档
            detail = db.execute(
                "select title, coalesce((state_snapshot->>'turn')::int, 0) as turn "
                "from game_saves where id = %s",
                (int(save_id),),
            ).fetchone() or {}
            turn = int(detail.get("turn") or 0)
            title = str(detail.get("title") or "")
            db.execute(
                "delete from game_saves where id = %s and user_id = %s",
                (int(save_id), user_id),
            )
        # 失效 user state cache
        try:
            import app as _ui
            _ui._invalidate_user_cache({"id": int(user_id)})
        except Exception:
            pass
        # task 120: 结果带 turn 信息, LLM 续叙时也只能引用这一次返回的具体 save_id, 不能 generalize
        warn = ""
        if turn >= 5:
            warn = f" ⚠️ This save had {turn} turns played; significant progress was permanently deleted!"
        return f"Deleted save_id={save_id} ({title!r}, turn={turn}) ✓{warn}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_delete_saves(user_id: int, args: dict) -> str:
    """task 120: 批量删除 - 解决"删多个存档"场景下 LLM 只调 1 次然后编造其他被删的幻觉。
    LLM 必须给出完整 save_ids 列表(先 list_my_saves 拿真实 ID),
    backend 逐个验证 + 删除, 返回 JSON 列出 deleted/not_found/protected 三个桶,
    LLM 续叙时只能基于这个真实结果, 无法编造。
    """
    import json as _json
    save_ids = args.get("save_ids")
    if not isinstance(save_ids, list) or not save_ids:
        return "Failed: save_ids must be a non-empty array of integers"
    try:
        ids = [int(x) for x in save_ids]
    except (TypeError, ValueError):
        return "Failed: save_ids must be a list of integers"
    if len(ids) > 50:
        return "Failed: at most 50 saves can be deleted per call (to avoid mistakes)"

    deleted: list[dict] = []
    not_found: list[int] = []
    protected: list[dict] = []  # turn>=10 的高价值存档,需要单独 delete_save 确认
    errors: list[dict] = []

    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            for sid in ids:
                try:
                    row = db.execute(
                        "select id, title, "
                        "  (state_snapshot->>'turn')::int as turn, "
                        "  coalesce(jsonb_array_length(state_snapshot->'history'), 0) as msg_count "
                        "from game_saves where id = %s and user_id = %s",
                        (sid, user_id),
                    ).fetchone()
                    if not row:
                        not_found.append(sid)
                        continue
                    turn = int(row.get("turn") or 0)
                    title = str(row.get("title") or "")
                    # 保护高价值存档:turn >= 10 必须单独 delete_save 走 destructive 确认
                    if turn >= 10:
                        protected.append({"id": sid, "title": title, "turn": turn})
                        continue
                    db.execute(
                        "delete from game_saves where id = %s and user_id = %s",
                        (sid, user_id),
                    )
                    deleted.append({"id": sid, "title": title, "turn": turn})
                except Exception as exc:
                    errors.append({"id": sid, "error": f"{type(exc).__name__}: {exc}"})
        try:
            import app as _ui
            _ui._invalidate_user_cache({"id": int(user_id)})
        except Exception:
            pass
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"

    # 详细 JSON 结果, LLM 必须基于这个 narrate, 不能编
    result = {
        "requested": len(ids),
        "deleted_count": len(deleted),
        "deleted": deleted,
        "not_found": not_found,
        "protected": protected,
        "errors": errors,
    }
    # 全军覆没(0 删除)必须以失败惯例开头,否则 dispatcher 记 ok=True=报成功
    if ids and not deleted:
        summary_lines = [f"Batch delete failed (requested {len(ids)}, succeeded 0):"]
    else:
        summary_lines = [f"Batch delete result (requested {len(ids)}):"]
    if deleted:
        summary_lines.append(f"  ✓ Deleted {len(deleted)}: " + ", ".join(
            f"{d['id']}({d['title']!r},turn={d['turn']})" for d in deleted
        ))
    if not_found:
        summary_lines.append(f"  ✗ Not found / no permission ({len(not_found)}): {not_found}")
    if protected:
        prot_strs = [f"{p['id']}({p['title']!r},turn={p['turn']})" for p in protected]
        summary_lines.append(
            f"  ⚠️ High-value saves must be deleted individually (turn>=10, skipped automatically) ({len(protected)}): " +
            ", ".join(prot_strs) + " — use delete_save one at a time with confirmation"
        )
    if errors:
        summary_lines.append(f"  ❌ Errors ({len(errors)}): {errors}")
    summary_lines.append("--- raw JSON ---")
    summary_lines.append(_json.dumps(result, ensure_ascii=False))
    return "\n".join(summary_lines)


def _branch_node_arg(args: dict):
    """branch_node_id(与 ui_manifest 同名)优先;兼容旧参数名 node_id / branch_id。"""
    for k in ("branch_node_id", "node_id", "branch_id"):
        if args.get(k) is not None:
            return args.get(k)
    return None


def _invalidate_state_cache(user_id: int) -> None:
    # 与 POST /api/branches/activate|delete 同:切换/删除后清 app.py 进程内 state 缓存,
    # 否则 /api/state 仍读旧 runtime。
    try:
        import app as _ui
        _ui._invalidate_user_cache({"id": int(user_id)})
    except Exception:
        pass


def _t_list_branches(user_id: int, args: dict) -> str:
    """列出存档的分支 = branch_refs(git 式命名分支)及其指向的 commit。

    旧实现查一张不存在的分支表,工具恒失败;现接真实存储(platform_app/branches)。
    归属走 perms.owns_save(单一真相源)。"""
    save_id = args.get("save_id")
    _chk = require_int_arg(save_id, "save_id", fail="Failed: save_id must be an integer")
    if isinstance(_chk, str):
        return _chk
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import owns_save
        init_db()
        with connect() as db:
            if not owns_save(db, int(save_id), int(user_id)):
                return "Failed (permission): this save does not belong to the current user"
            save = db.execute(
                "select active_commit_id from game_saves where id = %s", (int(save_id),),
            ).fetchone() or {}
            rows = db.execute(
                "select r.name, r.target_commit_id, r.is_active, c.turn_index, c.summary, c.title "
                "from branch_refs r left join branch_commits c on c.id = r.target_commit_id "
                "where r.save_id = %s order by r.id desc limit 50",
                (int(save_id),),
            ).fetchall() or []
        if not rows:
            return f"Save {save_id} has no branches yet"
        active_commit = save.get("active_commit_id")
        lines = [f"{len(rows)} branches of save {save_id}:"]
        for r in rows[:20]:
            nid = r.get("target_commit_id")
            active = bool(r.get("is_active")) or (nid is not None and nid == active_commit)
            summary = str(r.get("summary") or r.get("title") or "").strip().replace("\n", " ")[:80]
            lines.append(
                f"  · branch_node_id={nid} name={r.get('name') or '(unnamed)'} "
                f"turn={r.get('turn_index')}{' [active]' if active else ''}"
                + (f" - {summary}" if summary else "")
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_activate_branch(user_id: int, args: dict) -> str:
    """切到某分支节点(branch_commits.id),与 POST /api/branches/activate 同源 activate_node。
    归属由 activate_node 内 _commit_for_user(user_id) 校验。"""
    node_id = _branch_node_arg(args)
    _chk = require_int_arg(node_id, "branch_node_id", fail="Failed: branch_node_id must be an integer")
    if isinstance(_chk, str):
        return _chk
    try:
        from platform_app import branches as _branches
        result = _branches.activate_node(int(user_id), int(node_id))
        _invalidate_state_cache(user_id)
        return (f"Activated branch node {node_id} ✓ "
                f"(save={((result or {}).get('save') or {}).get('id', '?')})")
    except ValueError as exc:
        return f"Failed (permission): {exc}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_delete_branch(user_id: int, args: dict) -> str:
    """删除某分支节点起的整棵子树,与 POST /api/branches/delete 同源 delete_subtree。
    归属由 delete_subtree 内 _commit_for_user(user_id) 校验。"""
    node_id = _branch_node_arg(args)
    _chk = require_int_arg(node_id, "branch_node_id", fail="Failed: branch_node_id must be an integer")
    if isinstance(_chk, str):
        return _chk
    try:
        from platform_app import branches as _branches
        result = _branches.delete_subtree(int(user_id), int(node_id)) or {}
        _invalidate_state_cache(user_id)
        return (f"Deleted branch node {node_id} and everything after it ✓ "
                f"({len(result.get('nodes') or [])} nodes remain in the save)")
    except ValueError as exc:
        return f"Failed: {exc}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _t_continue_branch(user_id: int, args: dict) -> str:
    """从存档的第 from_turn 回合(该回合结束后的状态)分叉出新分支并切为活跃。

    旧实现调 `platform_app.branches.continue_branch` —— 该函数从未存在,工具恒返失败。
    现接到真实的 fork 链(与 POST /api/branches/continue 同源):
      resolve_commit_id_by_message(活跃血缘内按 turn 定位 commit) → continue_from(新 ref + 激活)。
    from_turn → message_index 换算:resolve 内部 turn_index = (idx - opening_offset)//2,
    opening_offset ∈ {0,1};取 idx = 2*from_turn + 1 时两种相位都恰好得到 from_turn。
    归属:先过 perms.owns_save(单一真相源),continue_from 内部 _commit_for_user 再校验一次。
    """
    save_id = args.get("save_id")
    from_turn = args.get("from_turn")
    _chk = require_int_arg(save_id, "save_id", fail="Failed: save_id must be an integer")
    if isinstance(_chk, str):
        return _chk
    _chk = require_int_arg(from_turn, "from_turn", fail="Failed: from_turn must be an integer")
    if isinstance(_chk, str):
        return _chk
    save_id, from_turn = int(save_id), int(from_turn)
    if from_turn < 0:
        return "Failed: from_turn must be >= 0"
    try:
        from platform_app import branches as _branches
        from platform_app.db import connect, init_db
        from platform_app.perms import owns_save
        init_db()
        with connect() as db:
            if not owns_save(db, save_id, int(user_id)):
                return "Failed (permission): this save does not belong to the current user"
        node_id = _branches.resolve_commit_id_by_message(int(user_id), save_id, 2 * from_turn + 1)
        if node_id is None:
            return f"Failed: no commit found for turn {from_turn} in save {save_id}"
        result = _branches.continue_from(int(user_id), int(node_id))
        # 同 POST /api/branches/continue:fork 后清 user state cache,否则 /api/state 仍读旧 runtime
        try:
            import app as _ui
            _ui._invalidate_user_cache({"id": int(user_id)})
        except Exception:
            pass
        ref = (result or {}).get("active_ref") or {}
        return (
            f"Created a branch from save={save_id} turn={from_turn} ✓ "
            f"(commit_id={result.get('active_commit_id', node_id)}, ref={ref.get('name', '?')}); "
            f"it is now the active branch."
        )
    except ValueError as exc:
        return f"Failed (permission): {exc}"
    except Exception as exc:
        return f"Failed: {type(exc).__name__}: {exc}"


def _save_specs() -> list:
    return [
        ToolSpec(
            name="create_save",
            description=(
                "Create a new save from a script_id. Equivalent to 'New save' in the UI."
                "\n\n**Pick ONE character-card id (important, do not mix them up):**"
                "\n  · `user_card_id`: a cross-script character card the user created (from list_my_character_cards). "
                "**Prefer this one**, because it is shared across scripts."
                "\n  · `persona_id`: the user's player persona (from list_my_personas)."
                "\n  · `script_card_id`: an NPC card inside the script (preset by the script author, listed in the script's characters). "
                "Only use it when the player wants to play that NPC as the protagonist. It is **not** a card the user created."
                "\n\nIf unsure, **call list_my_character_cards first to see the user_card_id list**, then use user_card_id. "
                "If none of the 3 is passed, the system falls back to the user's default persona."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "script_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "user_card_id": {
                        "type": "integer",
                        "description": "User-created character card id (recommended, from list_my_character_cards)",
                    },
                    "persona_id": {
                        "type": "integer",
                        "description": "The user's player persona id (from list_my_personas)",
                    },
                    "script_card_id": {
                        "type": "integer",
                        "description": "NPC card id inside the script (preset by the script author, not user-created)",
                    },
                },
                "required": ["script_id"],
            },
            executor=_t_create_save,
            scope="user",
            # task 48: console_assistant 可调,UI 与 api_direct 也可调。
            # LLM chat / llm_set 不可调:即使玩家在 chat 里 /set,也不该跨 save 操作。
            origins=frozenset({"ui_button", "api_direct", "console_assistant"}),
            destructive=False,
        ),
        ToolSpec(
            name="list_my_saves",
            description="List the current user's saves (optionally filtered by script_id).",
            input_schema={
                "type": "object",
                "properties": {
                    "script_id": {"type": "integer",
                                  "description": "Optional; only list saves of this script"},
                },
                "required": [],
            },
            executor=_t_list_my_saves,
            scope="user",
            origins=_USER_ORIGINS_READ,
        ),
        # task 119: 助手在用量页 (Usage) 时,看到用户问"统计/汇总/给我看一下用量",
        # 必须直接调这个工具,而不是 ui_set_field 把字符串塞回自己的输入框。
        ToolSpec(
            name="list_my_usage",
            description=(
                "Query the current user's token usage / cost / request count / error rate over the past N days, "
                "broken down by API and model. When the user on the #usage page asks to \"show stats / summarize / see usage / how much did I spend\", "
                "use this tool directly, not ui_set_field."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer",
                             "description": "Number of days to look back (default 30, range 1-365)",
                             "default": 30},
                },
                "required": [],
            },
            executor=_t_list_my_usage,
            scope="user",
            origins=_USER_ORIGINS_READ,
        ),
        ToolSpec(
            name="activate_save",
            description=(
                "Make the given save the active save. All subsequent chat is based on this save. "
                "Before switching, waits for the current save's tool queue to drain."
            ),
            input_schema={
                "type": "object",
                "properties": {"save_id": {"type": "integer"}},
                "required": ["save_id"],
            },
            executor=_t_activate_save,
            scope="user",
            origins=_USER_ORIGINS_MUTATE,  # task 87 Phase 7: LLM 禁
        ),
        ToolSpec(
            name="rename_save",
            description="Rename a save (change its title).",
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer"},
                    "title": {"type": "string"},
                },
                "required": ["save_id", "title"],
            },
            executor=_t_rename_save,
            scope="user",
            origins=_USER_ORIGINS_MUTATE,  # task 87 Phase 7
        ),
        ToolSpec(
            name="delete_save",
            description="**Permanently delete** a single save with all its branches/context chain. Irreversible. Deletes one at a time; when the user wants several deleted, use delete_saves instead.",
            input_schema={
                "type": "object",
                "properties": {"save_id": {"type": "integer"}},
                "required": ["save_id"],
            },
            executor=_t_delete_save,
            scope="user",
            origins=_USER_ORIGINS_DESTRUCTIVE,
            destructive=True,
        ),
        # task 120: 批量删除 - 防止 LLM 只调 1 次 delete_save 然后编造其他被删的幻觉。
        # 用法:用户说"删除多个/批量/除了 X 以外的"时,先 list_my_saves 拿全部 ID,
        # 然后**一次性**调 delete_saves(save_ids=[...]),走 1 次 destructive 确认,
        # 工具返回真实成败列表;turn>=10 的高价值档自动跳过,需要单独 delete_save。
        ToolSpec(
            name="delete_saves",
            description=(
                "**Permanently delete several saves in one batch.** One call, one destructive confirmation. "
                "Use this when the user says 'delete all / all except X / these few'; do not loop over delete_save. "
                "Saves with turn>=10 are skipped automatically (to protect long-running progress); the returned protected list needs a separate delete_save confirmation for each. "
                "You must call list_my_saves first and pass the real IDs; never fill them in from memory."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Array of save_ids to delete (must come from list_my_saves; never invent them)",
                        "minItems": 1,
                        "maxItems": 50,
                    },
                },
                "required": ["save_ids"],
            },
            input_examples=(
                {"save_ids": [10144, 13787, 13788, 13789]},
            ),
            executor=_t_delete_saves,
            scope="user",
            origins=_USER_ORIGINS_DESTRUCTIVE,
            destructive=True,
        ),
    ]


def _branch_specs() -> list:
    return [
        ToolSpec(
            name="list_branches",
            description="List the branches of a save (each with its branch_node_id, turn and whether it is active).",
            input_schema={
                "type": "object",
                "properties": {"save_id": {"type": "integer"}},
                "required": ["save_id"],
            },
            executor=_t_list_branches,
            scope="user",
            origins=_USER_ORIGINS_READ,
        ),
        ToolSpec(
            name="activate_branch",
            description=(
                "Make the given branch node the active one (checks out that point of the story). "
                "Get branch_node_id from list_branches."
            ),
            input_schema={
                "type": "object",
                "properties": {"branch_node_id": {
                    "type": "integer", "description": "Branch node (commit) id from list_branches"}},
                "required": ["branch_node_id"],
            },
            executor=_t_activate_branch,
            scope="user",
            origins=_USER_ORIGINS_MUTATE,  # task 87 Phase 7
        ),
        ToolSpec(
            name="delete_branch",
            description=(
                "**Permanently delete** the given branch node and everything after it. Irreversible. "
                "Get branch_node_id from list_branches."
            ),
            input_schema={
                "type": "object",
                "properties": {"branch_node_id": {
                    "type": "integer", "description": "Branch node (commit) id from list_branches"}},
                "required": ["branch_node_id"],
            },
            executor=_t_delete_branch,
            scope="user",
            origins=_USER_ORIGINS_DESTRUCTIVE,
            destructive=True,
        ),
        ToolSpec(
            name="continue_branch",
            description=(
                "Fork a new branch from a given turn of a save: the new branch keeps the history up to "
                "and including that turn (turn 0 = the opening) and becomes the active branch."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "save_id": {"type": "integer"},
                    "from_turn": {
                        "type": "integer", "minimum": 0,
                        "description": "Turn number to fork from (state after that turn; 0 = the opening)",
                    },
                },
                "required": ["save_id", "from_turn"],
            },
            executor=_t_continue_branch,
            scope="user",
            origins=_USER_ORIGINS_MUTATE,  # task 87 Phase 7
        ),
    ]


def register_saves_tools() -> None:
    registry = get_registry()
    specs: list[ToolSpec] = [*_save_specs(), *_branch_specs()]
    for spec in specs:
        if not registry.has(spec.name):
            registry.register(spec)


__all__ = ["register_saves_tools"]
