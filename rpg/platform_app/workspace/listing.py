"""platform_app.workspace.listing — 存档/剧本【列表·概览·就绪度】只读面(包化搬家)。

ensure_default(遗留存档 backfill 幂等兜底)+ overview + scripts / scripts_page +
saves / saves_page + save_detail + 就绪度计数(_readiness_for_scripts)+ 列清单常量。
纯机械搬家,逐字复制,零行为变化。
"""
from __future__ import annotations

from typing import Any

from state import SAVE_FILE

from .. import branches, runtime
from ..db import connect, cursor_id, expose, init_db, limit_value, page_payload
from ..db import status as db_status
from ..security import public_user


def ensure_default(user_id: int) -> None:
    """Maintain existing save runtime state without creating demo content.

    Production users must be able to have an empty script list. Older builds
    seeded a default novel whenever the list was empty, which made successful
    deletes appear to re-create the same script on the next authenticated
    request.
    """
    init_db()
    with connect() as db:
        save = db.execute(
            """
            select gs.*
            from game_saves gs
            join scripts s on s.id = gs.script_id
            where gs.user_id = %s and s.owner_id = %s
            order by gs.id
            limit 1
            """,
            (user_id, user_id),
        ).fetchone()
    # P0 修复:不再自动创建名为「当前自动存档」的引导存档。
    # 自动存档是「每个存档每回合无感提交」的能力,不是一个独立槽位。
    # 新用户进来 saves 列表为空 → 前端走空态 + 引导去建档(用户决策)。
    # 仅当用户已有存档时,补齐分支树 / runtime 指针(兼容存量数据)。
    if not save:
        return
    branches.seed_tree(save["id"], str(SAVE_FILE))
    if not runtime.read_runtime(user_id=user_id):
        with connect() as db:
            active = db.execute("select active_branch_node_id from game_saves where id = %s", (save["id"],)).fetchone()
            node_id = active.get("active_branch_node_id") if active else None
        if node_id:
            branches.activate_node(user_id, int(node_id))


def overview(user: dict | None) -> dict[str, Any]:
    if not user:
        return {"user": None, "auth_required": True, "database": db_status()}
    ensure_default(user["id"])
    with connect() as db:
        # 不要 select *:import_report jsonb 单行可达数 MB(felixchaos 4 个剧本合计 ~4MB,
        # script 11 历史实测单行 65MB),select * 把整列拉出来 + 序列化,实测把 /api/platform
        # 概览拖到 ~3.8s 本地 / 过网络 15s → nginx 超时 503(用户端表现为"加载转圈 30s")。
        # 概览/首页不渲染 import_report(全前端仅 scripts.jsx 详情用,且走 /api/scripts 分页端点,
        # scripts_page 那里也已显式列字段跳过此列)。这里照搬同款显式列清单,O(行数) 不 de-TOAST。
        scripts = db.execute(
            """
            select id, owner_id, title, description, source_path, created_at, updated_at,
                   public_id, row_version, chapter_count, word_count, content_fingerprint,
                   shareable, extracted_through_chapter, extraction_seeded,
                   is_public, published_at, clone_count, review_status, reviewed_at,
                   embed_api_id, embed_model,
                   forked_from_script_id, forked_at_commit_id, sharing_mode,
                   current_pin_script_id, current_pin_commit_id, head_commit_id
            from scripts where owner_id = %s order by updated_at desc, id desc limit 50
            """,
            (user["id"],),
        ).fetchall()
        saves = db.execute("select * from game_saves where user_id = %s order by updated_at desc, id desc limit 50", (user["id"],)).fetchall()
        settings = db.execute("select key, value from settings where user_id = %s", (user["id"],)).fetchall()
        branch_counts = {
            row["save_id"]: row["count"]
            for row in db.execute(
                """
                select n.save_id,
                       sum(
                         case
                           when n.kind = 'gm' and exists (
                             select 1 from branch_commits p
                             where p.id = n.parent_id
                               and p.kind = 'player'
                               and p.turn_index = n.turn_index
                           ) then 0
                           else 1
                         end
                       )::int as count
                from branch_commits n
                where n.save_id in (select id from game_saves where user_id = %s)
                group by n.save_id
                """,
                (user["id"],),
            ).fetchall()
        }
        assets = db.execute("select * from assets where user_id = %s order by id desc limit 20", (user["id"],)).fetchall()
    return {
        "user": public_user(user),
        "database": db_status(),
        "scripts": [expose(row) for row in scripts],
        "saves": [{**expose(row), "branch_count": branch_counts.get(row["id"], 0)} for row in saves],
        "settings": {row["key"]: row["value"] for row in settings},
        "assets": [expose(row) for row in assets],
        "runtime": runtime.read_runtime(user_id=user["id"]),
    }


def scripts(user_id: int) -> list[dict[str, Any]]:
    ensure_default(user_id)
    with connect() as db:
        return [expose(row) for row in db.execute("select * from scripts where owner_id = %s order by updated_at desc, id desc limit 200", (user_id,)).fetchall()]


def scripts_page(user_id: int, limit: int | str | None = None, cursor: str | None = None) -> dict[str, Any]:
    """列表 API:**显式列字段**,跳过 import_report jsonb (实测 script 11 这一行
    65 MB,select * 直接把列表 API 拖到 15s + 2.3MB 响应)。完整字段走 detail endpoint。

    顺手把游戏就绪度 (readiness) 摊到每行 — 列表"状态"列要用,见 _readiness_for_scripts。

    task 74: union owned + subscribed(公开剧本订阅,immutable knowledge,不复制数据,
    只挂指针)。前端通过 item.is_subscribed 区分是否本人拥有(决定能否编辑)。
    """
    ensure_default(user_id)
    page_limit = limit_value(limit)
    before_id = cursor_id(cursor)
    with connect() as db:
        rows = db.execute(
            """
            select s.id, s.owner_id, s.title, s.description, s.source_path, s.created_at, s.updated_at,
                   s.public_id, s.row_version, s.chapter_count, s.word_count, s.content_fingerprint,
                   s.shareable, s.extracted_through_chapter, s.extraction_seeded,
                   s.is_public, s.published_at, s.clone_count, s.review_status, s.reviewed_at,
                   s.embed_api_id, s.embed_model,
                   s.forked_from_script_id, s.forked_at_commit_id, s.sharing_mode,
                   s.current_pin_script_id, s.current_pin_commit_id, s.head_commit_id,
                   s.cover_image_url,
                   (s.owner_id != %s) as is_subscribed
            from scripts s
            where (
              s.owner_id = %s
              or s.id in (select script_id from user_script_subscriptions where user_id = %s)
            )
              and (%s::bigint is null or s.id < %s)
            order by s.id desc
            limit %s
            """,
            (user_id, user_id, user_id, before_id, before_id, page_limit + 1),
        ).fetchall()
        readiness = _readiness_for_scripts(db, [int(r["id"]) for r in rows])
    payload = page_payload(rows, page_limit)
    for item in payload["items"]:
        item["readiness"] = readiness.get(int(item["id"])) or _empty_readiness()
    return payload


# 游戏就绪度 — 5 个维度:章节切片 / 向量嵌入 / 知识库人物 / 世界观条目 / 时间线锚点。
# cards 是用户级别(user_character_cards 没有 script_id),不算 per-script 就绪度。
_READINESS_KEYS = ("chunks", "embeddings", "canon", "worldbook", "anchors")


def _empty_readiness() -> dict[str, Any]:
    return {
        "ok": False,
        "missing": list(_READINESS_KEYS),
        "items": [
            {"key": k, "ok": False, "count": 0, "total": 0} for k in _READINESS_KEYS
        ],
    }


def _readiness_for_scripts(db, script_ids: list[int]) -> dict[int, dict[str, Any]]:
    """一次查询拿到 N 个剧本的就绪度计数,避免 N+1。

    返 {script_id: {ok, missing, items: [{key, ok, count, total}]}}。
    每个 item 含 jump 信息留给前端拼(后端只给 raw counts)。
    """
    if not script_ids:
        return {}
    # 单 SQL,对每张表 group-by script_id;script_id 表 left-join
    # 用 UNION ALL 把 5 张表的 (script_id, dim, count, total) 全拍平,再 Python 侧组装。
    sql = """
        select script_id, 'chunks'::text as dim, count(*)::bigint as cnt, count(*)::bigint as total
          from document_chunks where script_id = any(%(ids)s) group by script_id
        union all
        select script_id, 'embeddings'::text,
               sum(case when embedding is not null then 1 else 0 end)::bigint as cnt,
               count(*)::bigint as total
          from document_chunks where script_id = any(%(ids)s) group by script_id
        union all
        select script_id, 'canon'::text, count(*)::bigint, count(*)::bigint
          from kb_canon_entities where script_id = any(%(ids)s) group by script_id
        union all
        select script_id, 'worldbook'::text, count(*)::bigint, count(*)::bigint
          from worldbook_entries where script_id = any(%(ids)s) group by script_id
        union all
        select script_id, 'anchors'::text, count(*)::bigint, count(*)::bigint
          from script_timeline_anchors where script_id = any(%(ids)s) group by script_id
    """
    rows = db.execute(sql, {"ids": script_ids}).fetchall()
    # 初始化全 0
    out: dict[int, dict[str, dict[str, int]]] = {
        sid: {k: {"count": 0, "total": 0} for k in _READINESS_KEYS}
        for sid in script_ids
    }
    for r in rows:
        sid = int(r["script_id"])
        dim = r["dim"]
        if sid in out and dim in out[sid]:
            out[sid][dim]["count"] = int(r["cnt"] or 0)
            out[sid][dim]["total"] = int(r["total"] or 0)
    # 拼装最终结构 + ok 判定
    result: dict[int, dict[str, Any]] = {}
    for sid in script_ids:
        items = []
        missing = []
        for key in _READINESS_KEYS:
            cnt = out[sid][key]["count"]
            total = out[sid][key]["total"]
            # chunks/canon/worldbook/anchors 只看 count>0;embeddings 看 == 或近似 ==(允许少 5%)
            if key == "embeddings":
                ready = total > 0 and cnt >= max(1, int(total * 0.95))
            else:
                ready = cnt > 0
            if not ready:
                missing.append(key)
            items.append({"key": key, "ok": ready, "count": cnt, "total": total})
        result[sid] = {
            "ok": not missing,
            "missing": missing,
            "items": items,
        }
    return result


def _read_state_snapshot() -> dict[str, Any]:
    """新存档的初始 state。

    安全：绝对不能读全局 SAVE_FILE（那是 admin 的运行态，会泄露给新用户）。
    走 state.GameState.new()，得到干净的初始 state。
    """
    try:
        from state import GameState
        return GameState.new().data
    except Exception:
        return {"history": [], "turn": 0}


# 列表页只取摘要字段；完整 state_snapshot 通过 save_detail() 单独取
# 全列用 game_saves. 限定:saves_page() 里有 `left join scripts s`,scripts 同名列(id/title 等)
# 会让裸列名歧义(AmbiguousColumn 500)。限定后在 saves()(无 join)与 saves_page()(有 join)都成立。
_SAVE_LIST_COLUMNS = """
    game_saves.id, game_saves.public_id, game_saves.user_id, game_saves.script_id, game_saves.title, game_saves.state_path,
    game_saves.active_commit_id, game_saves.active_branch_node_id, game_saves.active_branch_ref_id,
    game_saves.created_at, game_saves.updated_at,
    coalesce(game_saves.last_played_at, game_saves.updated_at) as last_played_at, game_saves.row_version,
    (game_saves.state_snapshot->>'turn')::int as turn,
    (game_saves.state_snapshot->'player'->>'name') as player_name,
    coalesce(jsonb_array_length(game_saves.state_snapshot->'history'), 0) as history_count,
    coalesce((game_saves.state_snapshot->'world'->>'time'), '') as world_time,
    coalesce(game_saves.save_kind, 'game') as save_kind
"""


def saves(user_id: int) -> list[dict[str, Any]]:
    ensure_default(user_id)
    with connect() as db:
        return [expose(row) for row in db.execute(
            f"select {_SAVE_LIST_COLUMNS} from game_saves where user_id = %s order by updated_at desc, id desc limit 200",
            (user_id,),
        ).fetchall()]


def saves_page(user_id: int, limit: int | str | None = None, cursor: str | None = None) -> dict[str, Any]:
    ensure_default(user_id)
    page_limit = limit_value(limit)
    before_id = cursor_id(cursor)
    with connect() as db:
        rows = db.execute(
            f"""
            select {_SAVE_LIST_COLUMNS},
                   s.title as script_title,
                   (
                     select sum(
                       case
                         when n.kind = 'gm' and exists (
                           select 1 from branch_commits p
                           where p.id = n.parent_id
                             and p.kind = 'player'
                             and p.turn_index = n.turn_index
                         ) then 0
                         else 1
                       end
                     )::int
                     from branch_commits n
                     where n.save_id = game_saves.id
                   ) as branch_count,
                   (game_saves.id = (
                     select ur.save_id from user_runtime ur
                     where ur.user_id = game_saves.user_id
                     limit 1
                   )) as current
            from game_saves
            left join scripts s on s.id = game_saves.script_id
            where game_saves.user_id = %s and (%s::bigint is null or game_saves.id < %s)
            order by game_saves.id desc
            limit %s
            """,
            (user_id, before_id, before_id, page_limit + 1),
        ).fetchall()
    return page_payload(rows, page_limit)


def save_detail(user_id: int, save_id: int) -> dict[str, Any]:
    """单条详情：包含完整 state_snapshot。前端只在打开 save 时才调。"""
    with connect() as db:
        row = db.execute(
            "select * from game_saves where id = %s and user_id = %s",
            (save_id, user_id),
        ).fetchone()
    if not row:
        raise ValueError(f"No access to this save: {save_id}")
    return expose(row) or {}
