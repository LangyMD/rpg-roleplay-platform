"""platform_app.api.scripts.listing —— 剧本列表 + 状态/元数据只读端点。

/api/scripts、modules-status、embed/status、chapter-facts、timeline、birthpoints、
recommend-identity。纯机械搬家,行为零变化。
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from ... import knowledge
from ...db import connect
from .._deps import json_response, require_user, value_error_response
from ._shared import router


@router.get("/api/scripts")
async def api_scripts(limit: int | None = None, cursor: str | None = None, user=Depends(require_user)):
    from ... import workspace
    return json_response({"ok": True, **workspace.scripts_page(user["id"], limit, cursor)})


# phase_backend: 旧 POST /api/scripts/{id}/embed 移到 api/imports.py 作为
# /rebuild/embeddings 的 alias(走统一 import_jobs + SSE);此处只留 /embed/status。


@router.get("/api/scripts/{script_id}/modules-status")
async def api_script_modules_status(script_id: int, user=Depends(require_user)):
    """phase_backend: 一次返 7 模块各自的 done/total/stale/last_job_id。

    7 模块:chunks/chapter-facts/canon/cards/worldbook/anchors/embeddings
    每模块返:
      done: 当前已落库的行数(>0 即视为可用)
      total: 目标数(章节数 / canon entity 数 等参考值)
      stale: 是否过期(若有更晚的同 script 写入但本模块未跟上,如 chapters 改了但 chunks 未重建)
      last_job_id: 最近一次本模块的 import_jobs.job_id(可用于继续/重订 SSE)
    """
    with connect() as db:
        owned = db.execute(
            """select s.chapter_count, s.updated_at from scripts s
            where s.id = %s and (
              s.owner_id = %s
              or s.id in (select script_id from user_script_subscriptions where user_id = %s)
            )""",
            (script_id, user["id"], user["id"]),
        ).fetchone()
        if not owned:
            return json_response({"ok": False, "error": "No access to this script"}, status_code=403)
        script_updated = owned.get("updated_at")
        chapter_count = int(owned.get("chapter_count") or 0)

        # 各模块当前 done / total
        def _scalar(sql: str) -> int:
            row = db.execute(sql, (script_id,)).fetchone()
            return int(row["c"]) if row else 0

        chunks_done = _scalar("select count(*) as c from document_chunks where script_id = %s")
        facts_done = _scalar("select count(*) as c from chapter_facts where script_id = %s")
        canon_done = _scalar("select count(*) as c from kb_canon_entities where script_id = %s")
        cards_done = _scalar("select count(*) as c from character_cards where script_id = %s and card_type='npc'")
        wb_done = _scalar("select count(*) as c from worldbook_entries where script_id = %s")
        anchors_done = _scalar("select count(*) as c from script_timeline_anchors where script_id = %s")
        # embeddings — chunks 的 embedding_vec 是真相源(不是 jsonb embedding)
        embed_done = _scalar(
            "select count(*) as c from document_chunks where script_id = %s and embedding_vec is not null"
        )

        # 每模块最近一次 job(by kind)
        kind_to_module = {
            "rebuild_chunks": "chunks",
            "rebuild_facts": "chapter-facts",
            "rebuild_canon": "canon",
            "rebuild_cards": "cards",
            "rebuild_worldbook": "worldbook",
            "rebuild_anchors": "anchors",
            "rebuild_embeddings": "embeddings",
            "full_pipeline": "full_pipeline",
            "llm_extract": "llm_extract",
            # 三个新模块(facts_refine/worldbook_enrich/world_key)。这三个不在下方
            # modules-status 的 7 张固定卡片里(它们是按需精炼/充实操作，非"是否已建立"
            # 状态型模块)，但登记进这份 kind→module 映射保持与 REBUILD_MODULES 的
            # job kind 命名一致，避免这三类 job 的 kind 在此表里"找不到"而被静默丢弃。
            "rebuild_facts_refine": "facts_refine",
            "rebuild_worldbook_enrich": "worldbook_enrich",
            "rebuild_world_key": "world_key",
        }
        job_rows = db.execute(
            "select kind, job_id, status, finished_at, created_at "
            "from import_jobs where script_id = %s "
            "order by created_at desc limit 50",
            (script_id,),
        ).fetchall()
        last_job_by_module: dict[str, dict[str, Any]] = {}
        for r in job_rows:
            kind = r.get("kind") or ""
            mod = kind_to_module.get(kind)
            if not mod or mod in last_job_by_module:
                continue
            last_job_by_module[mod] = {
                "job_id": r.get("job_id"),
                "status": r.get("status"),
                "finished_at": str(r.get("finished_at")) if r.get("finished_at") else None,
                "kind": kind,
            }

    # E2E 暴露:rebuild-panel agent 的前端读 m.done_count/m.total_count/m.status,
    # 但 _build 返的是 done/total + 没 status → 卡片"条数:—" + "modules.status.unknown"
    # 同时双写新字段(done_count/total_count/status)+ 老字段(done/total)兼容
    def _build(name: str, done: int, total: int) -> dict[str, Any]:
        lj = last_job_by_module.get(name)
        stale = False
        if lj and lj.get("finished_at") and script_updated and done > 0:
            stale = str(script_updated) > str(lj.get("finished_at"))
        # status 派生:
        #   running: 有活跃 job (pending/running)
        #   stale:   旧版数据但 chapters 已变
        #   ready:   done>=total>0 或 done>0 且 total=0(canon/cards 等无 total 概念)
        #   partial: 0<done<total
        #   missing: done==0
        if lj and lj.get("status") in ("pending", "running"):
            status = "running"
        elif stale:
            status = "stale"
        elif total > 0:
            status = "ready" if done >= total else ("partial" if done > 0 else "missing")
        else:
            status = "ready" if done > 0 else "missing"
        return {
            "module": name,
            "done": done,
            "total": total,
            "done_count": done,       # 新字段名,前端 ModuleStatusCard 期望的
            "total_count": total,     # 同上
            "status": status,         # 派生 'ready'|'partial'|'missing'|'stale'|'running'
            "stale": stale,
            "last_job_id": (lj or {}).get("job_id"),
            "last_status": (lj or {}).get("status"),
        }

    return json_response({
        "ok": True,
        "script_id": script_id,
        "modules": [
            _build("chunks", chunks_done, max(chapter_count, 1)),
            _build("chapter-facts", facts_done, max(chapter_count, 1)),
            _build("canon", canon_done, 0),
            _build("cards", cards_done, 0),
            _build("worldbook", wb_done, 0),
            _build("anchors", anchors_done, 0),
            _build("embeddings", embed_done, max(chunks_done, 1)),
        ],
    })


@router.get("/api/scripts/{script_id}/embed/status")
async def api_script_embed_status(script_id: int, user=Depends(require_user)):
    """task 51: 查询某剧本的向量化进度。前端轮询用。"""
    from ...knowledge import embedding as _embed
    with connect() as db:
        owned = db.execute(
            """select 1 from scripts s
            where s.id = %s and (
              s.owner_id = %s
              or s.id in (select script_id from user_script_subscriptions where user_id = %s)
            )""",
            (script_id, user["id"], user["id"]),
        ).fetchone()
    if not owned:
        return json_response({"ok": False, "error": "No access to this script"}, status_code=403)
    return json_response({"ok": True, "status": _embed.embed_status(script_id)})


@router.get("/api/scripts/{script_id}/chapter-facts")
async def api_script_chapter_facts(script_id: int, limit: int | None = None, cursor: str | None = None, user=Depends(require_user)):
    try:
        return json_response({"ok": True, **knowledge.list_chapter_facts(user["id"], script_id, limit, cursor)})
    except ValueError as exc:
        return value_error_response(exc)


@router.get("/api/scripts/{script_id}/timeline")
async def api_script_timeline(script_id: int, user=Depends(require_user)):
    """剧本时间线锚点 — script_timeline_anchors 全量按 chapter_min 顺序返。

    跟 /birthpoints (按 phase 聚合采样,给入场选择用) 不同:
    本 endpoint 给"时间线编辑器 tab"用,要看到所有 anchor + 故事时间标签。
    返:{phases: [{phase_label, anchors: [{chapter_min/max, story_time_label, sample_summary, story_phase}]}]}
    若 story_phase 全为空(LLM extract 没填),把全部 anchor 放到一个"未分阶段"桶。
    """
    with connect() as db:
        owned = db.execute(
            """select 1 from scripts s
            where s.id = %s and (
              s.owner_id = %s
              or s.id in (select script_id from user_script_subscriptions where user_id = %s)
            )""",
            (script_id, user["id"], user["id"]),
        ).fetchone()
        if not owned:
            return json_response({"ok": False, "error": "No access to this script"}, status_code=403)
        rows = db.execute(
            """
            select id, story_phase, story_time_label, chapter_min, chapter_max,
                   chapter_count, sample_summary, confidence, keywords, sample_title
            from script_timeline_anchors
            where script_id = %s
            order by chapter_min asc, id asc
            """,
            (script_id,),
        ).fetchall()
    # 按 story_phase 聚合;phase 全空时归"未分阶段"
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        phase = (r.get("story_phase") or "").strip() or "未分阶段"
        buckets.setdefault(phase, []).append({
            "anchor_id": r["id"],
            "id": r["id"],
            "story_time_label": r["story_time_label"],
            "chapter_min": r["chapter_min"],
            "chapter_max": r["chapter_max"],
            "chapter_count": r["chapter_count"],
            "sample_summary": r["sample_summary"],
            "confidence": float(r["confidence"] or 0),
            # 编辑器锚点编辑需全字段回显,否则用户在「看似为空」的 keywords/sample_title 里输入
            # 会静默覆盖 DB 真实值(审计 P0 数据丢失)。keywords 是 text[] → 原样返回数组。
            "keywords": r["keywords"] or [],
            "sample_title": r["sample_title"] or "",
        })
    phases = []
    for p, items in buckets.items():
        cmins = [a["chapter_min"] for a in items if a.get("chapter_min") is not None]
        cmaxs = [a["chapter_max"] for a in items if a.get("chapter_max") is not None]
        phases.append({
            "phase_label": p,
            "chapter_min": min(cmins) if cmins else None,
            "chapter_max": max(cmaxs) if cmaxs else None,
            "anchor_count": len(items),
            "anchors": items,
        })
    return json_response({"ok": True, "phases": phases, "total": len(rows)})


@router.get("/api/scripts/{script_id}/birthpoints")
async def api_script_birthpoints(script_id: int, user=Depends(require_user)):
    """入场选出生点：按 phase 聚合 + 每 phase 均匀采样代表性 anchor。

    返回 phase_digests 的各阶段，以及每阶段从 script_timeline_anchors 均匀采样的
    5-15 个 anchor（≤15 全取，否则步长 round(N/12) 采样）。
    """
    with connect() as db:
        owned = db.execute(
            """select 1 from scripts s
            where s.id = %s and (
              s.owner_id = %s
              or s.id in (select script_id from user_script_subscriptions where user_id = %s)
            )""",
            (script_id, user["id"], user["id"]),
        ).fetchone()
        if not owned:
            return json_response({"ok": False, "error": "No access to this script"}, status_code=403)

        # 全部锚点(按章序)。真实锚点是唯一可靠数据源 —— phase_digests 的 chapter_min/max
        # 在历史迁移后常与锚点的章号不在同一标尺(实测多剧本:phase 范围覆盖全书但锚点只落早章,
        # 或 phase 用阶段序号当章号),strict containment 会让整段出生点空掉(用户「显示不出来」)。
        all_anchors = db.execute(
            """
            select id, story_time_label, chapter_min, chapter_max, chapter_count, sample_summary
            from script_timeline_anchors
            where script_id = %s
              and coalesce(source, 'novel') = 'novel'
            order by chapter_min asc, id asc
            """,
            (script_id,),
        ).fetchall()
        if not all_anchors:
            # 无锚点 → 前端走空态(从头开始),不渲染空的 phase 手风琴。
            return json_response({"ok": True, "phases": []})

        phase_rows = db.execute(
            """
            select phase_label, chapter_min, chapter_max, chapter_count, summary
            from phase_digests
            where script_id = %s
            order by chapter_min asc
            """,
            (script_id,),
        ).fetchall()

        def _sample(rows):
            # ≤15 全取，否则步长 round(N/12) 均匀采样 + 末尾兜底
            n = len(rows)
            if n <= 15:
                return list(rows)
            step = max(1, round(n / 12))
            s = list(rows[::step])
            if rows[-1] not in s:
                s.append(rows[-1])
            return s

        def _dto(ar):
            return {
                "anchor_id": int(ar["id"]),
                "story_time_label": ar["story_time_label"],
                "chapter_min": int(ar["chapter_min"]),
                "chapter_max": int(ar["chapter_max"]),
                "chapter_count": int(ar["chapter_count"]),
                "sample_summary": ar["sample_summary"] or "",
            }

        # 优先:phase_digests 与锚点「完全对齐」(所有锚点都按重叠落进某段 + 每段非空)
        # 才用富 phase 信息(真实 arc 标签/章号/摘要)。
        phases = None
        if phase_rows:
            buckets = [[] for _ in phase_rows]
            unassigned = 0
            for a in all_anchors:
                amin, amax = int(a["chapter_min"]), int(a["chapter_max"])
                hit = next(
                    (i for i, pr in enumerate(phase_rows)
                     if amin <= int(pr["chapter_max"]) and amax >= int(pr["chapter_min"])),
                    None,
                )
                if hit is None:
                    unassigned += 1
                else:
                    buckets[hit].append(a)
            if unassigned == 0 and all(buckets):
                phases = [
                    {
                        "phase_label": pr["phase_label"],
                        "chapter_min": int(pr["chapter_min"]),
                        "chapter_max": int(pr["chapter_max"]),
                        "chapter_count": int(pr["chapter_count"]),
                        "summary": pr["summary"] or "",
                        "anchors": [_dto(ar) for ar in _sample(buckets[i])],
                    }
                    for i, pr in enumerate(phase_rows)
                ]

        # 否则(phase_digests 缺失 / 与锚点章号错位)→ 直接把真实锚点按序均分成 N 段,
        # 沿用 arc 标签命名,每段章号取该段锚点的真实首尾 —— 保证每段都有真实锚点、绝不空。
        if phases is None:
            labels = [pr["phase_label"] for pr in phase_rows] if phase_rows else \
                ["开端", "发展前期", "发展中期", "发展后期", "结局"]
            n_seg = max(1, len(labels))
            total = len(all_anchors)
            phases = []
            for i in range(n_seg):
                seg = all_anchors[(total * i) // n_seg:(total * (i + 1)) // n_seg]
                if not seg:
                    continue
                phases.append({
                    "phase_label": labels[i] if i < len(labels) else f"阶段 {i + 1}",
                    "chapter_min": int(seg[0]["chapter_min"]),
                    "chapter_max": int(seg[-1]["chapter_max"]),
                    "chapter_count": int(seg[-1]["chapter_max"]) - int(seg[0]["chapter_min"]) + 1,
                    "summary": "",
                    "anchors": [_dto(ar) for ar in _sample(seg)],
                })

    return json_response({"ok": True, "phases": phases})


@router.post("/api/scripts/{script_id}/recommend-identity")
async def api_script_recommend_identity(request: Request, script_id: int, user=Depends(require_user)):
    """task 123: 入场 wizard Step 4 — LLM 推荐玩家初始身份。
    入参 body: {birthpoint_phase, birthpoint_label, character_card_id?, character_card_kind?, n?}
    返回: {ok, recommendations: [{name, role, background}, ...]}
    """
    body = await request.json()
    # 校验 script 归属
    with connect() as db:
        owned = db.execute(
            """select 1 from scripts s
            where s.id = %s and (
              s.owner_id = %s
              or s.id in (select script_id from user_script_subscriptions where user_id = %s)
            )""",
            (script_id, user["id"], user["id"]),
        ).fetchone()
        if not owned:
            return json_response({"ok": False, "error": "No access to this script"}, status_code=403)
    # 调 recommend_player_identity 工具
    try:
        import secrets as _sec

        from console_assistant import dispatch_assistant_tool
        args = {
            "script_id": int(script_id),
            "birthpoint_phase": str(body.get("birthpoint_phase") or ""),
            "birthpoint_label": str(body.get("birthpoint_label") or ""),
            "n": int(body.get("n") or 4),
        }
        if body.get("character_card_id") is not None:
            args["character_card_id"] = int(body["character_card_id"])
        if body.get("character_card_kind"):
            args["character_card_kind"] = str(body["character_card_kind"])
        # player_origin: 'isekai'(穿越/转生) | 'native'(原作角色) — 透到 LLM 工具,
        # 决定生成的 4 个候选是"现代灵魂穿越成 X"还是"原作世界里的 X 身份"
        po = str(body.get("player_origin") or "").lower()
        if po == "isekai":
            po = "soul"  # 旧值兼容
        if po in ("soul", "body", "dual", "native"):
            args["player_origin"] = po
        result = dispatch_assistant_tool(
            user_id=int(user["id"]),
            tool="recommend_player_identity",
            args=args,
            save_id=None,
            script_id=int(script_id),
            trace_id=f"wizard-{_sec.token_urlsafe(6)}",
            call_id=f"wiz-{_sec.token_urlsafe(6)}",
        )
        # 工具 return JSON 字符串, parse 一下
        import json as _j
        try:
            payload = _j.loads(result.result) if isinstance(result.result, str) else result.result
        except Exception:
            payload = {"ok": False, "error": "无法解析推荐结果", "raw": str(result.result)[:200]}
        if not result.ok:
            return json_response({"ok": False, "error": result.error or "工具执行失败"}, status_code=200)
        # task: 工具自报 ok=false (LLM 403 / 上下文不足 / 模型不可用 等)返 200 + ok:false,
        # payload.error 含详细原因(如 Vertex 403:用户 SA 缺权限 / 未启用 API)。
        # 前端按 ok 字段判断,不再被 HTTP 502 generic message 吞掉真因。
        # (旧设计返 502 让前端"区分系统问题",反而让真错误信息丢失。)
        if isinstance(payload, dict) and payload.get("ok") is False:
            return json_response(payload, status_code=200)
        return json_response(payload)
    except Exception as exc:
        return json_response(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
            status_code=500,
        )
