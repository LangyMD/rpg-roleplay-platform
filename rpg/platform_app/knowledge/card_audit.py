"""platform_app.knowledge.card_audit — 按需 AI 复核 NPC 角色卡的人名/语义错误。

用户在剧本 → NPC 角色卡 点「AI 复核」并在弹出的公用模型选择器里选模型(默认其常用模型、可改)→
用所选模型对全部 NPC 卡做【一次】批量裁决:
  ① merges:把同一人的多张卡(本名/小名/敬称,如金玉/玉儿/小玉)合并成一张;
  ② protagonist:选出真主角并锁定(复用 _db_set_protagonist 的 protagonist_locked,重新提取不再覆盖);
  ③ non_persons:删除非人名卡(官职/泛称/地名,如将军/单于/众人/无忧宫)。

确定性应用裁决、保守(LLM 不确定就不动、ID 必须真实存在),返回变更摘要。**按需触发、不进导入流水线
→ 对导入零自动成本**;模型由用户当场选(写入 card_audit.* 偏好,后端兜底也读它)。
"""
from __future__ import annotations

import json
import re
from typing import Any

from psycopg.types.json import Jsonb

from platform_app.db import connect, init_db
from platform_app.knowledge._character_cards_repo import _db_set_protagonist
from platform_app.knowledge._utils import _require_script_owner

_AUDIT_SYSTEM = (
    "You audit character cards extracted from a novel. Below are NPC character cards that were "
    "extracted automatically from one novel (they may contain mistakes). Review them **using only the "
    "information on the cards**; when unsure, change nothing (better to miss a fix than to make a wrong "
    "one). **Output only one JSON object**, with no explanation."
)


def _as_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str) and v.strip():
        return [s.strip() for s in v.split(",") if s.strip()]
    return []


def _parse_json_obj(text: str) -> dict:
    if not text:
        return {}
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except Exception:
        pass
    m = re.search(r"\{.*\}", text or "", re.S)
    if m:
        try:
            v = json.loads(m.group(0))
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


def _roster(cards: list[dict]) -> str:
    lines = []
    for c in cards:
        al = _as_list(c.get("aliases"))
        al_s = ", ".join(al[:6]) if al else "-"
        idt = (c.get("identity") or "").strip().replace("\n", " ")[:150] or "-"
        lines.append(
            f"[id={c['id']}] {c['name']} | aliases: {al_s} | identity: {idt} | appearances: {int(c.get('importance') or 0)}"
        )
    return "\n".join(lines)


def _build_user_prompt(title: str, cards: list[dict]) -> str:
    return (
        f"Novel title: \"{title or 'unknown'}\"\n\n"
        f"Review the {len(cards)} NPC character cards below, find three kinds of errors, and give the fixes:\n"
        "1) merges: which cards are really [the same person] under different names (full name / pet name / "
        "nickname / honorific, e.g. \"Elizabeth / Lizzy / Eliza\", \"Mr. Darcy / Darcy\"), and should be merged into "
        "one card. Each group: keep = the id of the card to keep, merge_ids = the list of ids merged into it. "
        "Different people must [never] be merged, even if they share part of a name (e.g. a surname).\n"
        "2) protagonist_id: the id of the card for this novel's [protagonist] (the narrative center who runs "
        "through the whole book and whom the reader identifies with; often the card whose identity/summary says "
        "protagonist / main character / transmigrator / reincarnator, or the first-person narrator. **Not "
        "necessarily the card with the most appearances**: villains and faction names often appear more but are "
        "not the protagonist). Decide only after reading every card; if unsure, use null.\n"
        "3) non_person_ids: which cards are [not specific people] (official posts / titles / generic terms / place "
        "names, e.g. \"the General\", \"the King\", \"the crowd\", \"Thornfield Hall\"), and should be deleted.\n\n"
        "[Character cards]\n" + _roster(cards) + "\n\n"
        "Output only this JSON (ids must be the numeric ids given above; do not make any up):\n"
        '{"merges":[{"keep":1,"merge_ids":[2,3]}],"protagonist_id":1,"non_person_ids":[4,5],"confidence":0.0}'
    )


def _resolve_audit_model(user_id: int, api_id: str, model: str) -> tuple[str, str]:
    """解析本次复核用的模型 —— 复用程序既有的模型解析设计,**不硬编码任何模型**:
      1. 前端当场传入的 (api_id, model)(用户在公用选择器里选的);
      2. card_audit.* 偏好(用户在选择器里改过会写这);
      3. 用户的【默认模型】—— first_user_model 已内含 gm.* 偏好 + BYOK(= 设置里设的默认模型)。
    三步都拿不到 → 返回空,由调用方的凭证预检转 credentials_required 引导用户去配,绝不回落到
    某个写死的便宜档。
    """
    from core.llm_backend import (
        first_user_model,
        resolve_preferred_api,
        resolve_preferred_model,
    )
    api_id = (api_id or "").strip()
    model = (model or "").strip()
    if not (api_id and model):
        api_id = api_id or (resolve_preferred_api(user_id, "card_audit.api_id") or "")
        model = model or (resolve_preferred_model(user_id, "card_audit.model_real_name") or "")
    if not (api_id and model):
        fu = first_user_model(user_id)  # gm.* 偏好优先 + 仅 BYOK 命中 = 用户的默认模型
        if fu:
            api_id = api_id or fu[0]
            model = model or fu[1]
    from model_aliases import normalize_api_id
    return normalize_api_id(api_id) if api_id else "", model


# 每批送审的卡数。60 张:单次调用稳在 CF 524(~100s)之下;且给推理型模型(deepseek-v4-flash 等)
# 留足 max_tokens —— 推理模型会先吃掉一大段 reasoning,token 不够时可见 content 直接为空(parse 失败、
# 主角识别不出)。实测 80 卡 @1600tok → 空;@4000tok → 正常 JSON。故 chunk 调小 + max_tokens 抬高。
_AUDIT_CHUNK = 60
_AUDIT_MAX_TOKENS = 4000   # 推理模型留足输出预算(reasoning + verdict JSON)
_AUDIT_TIMEOUT = 90        # 单批 client 超时,卡在 CF 524(~100s)之下 → 超时也是干净失败而非 524


def _cid(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def audit_character_cards(user_id: int, script_id: int, api_id: str = "", model: str = "",
                          *, max_cards: int = 600, progress_cb=None) -> dict[str, Any]:
    """对某剧本全部 NPC 卡做 AI 复核裁决并应用。**仅 owner**。返回变更摘要。

    **分批送审**:几百张卡一次性塞给 LLM 会让单次请求 >100s → CF 524(中转站边缘超时),且 verdict
    JSON 过长易截断。改成每批 80 张分多次调用(每次稳在 524 之下),逐批应用 merges/non_persons;
    主角(全局唯一)只采纳第 0 批(importance 最高,主角必在其中)的判定。progress_cb(done, total)
    用于把分批进度写进后台任务浮窗(终于有真实中间进度,不再只有 0/100%)。

    凭证缺失 → 抛 MissingUserCredentialError(端点转 credentials_required)。
    """
    init_db()
    from platform_app import import_pipeline
    api_id, model = _resolve_audit_model(user_id, api_id, model)

    with connect() as db:
        _require_script_owner(db, user_id, script_id)
        title_row = db.execute("select title from scripts where id=%s", (script_id,)).fetchone()
        title = ((title_row.get("title") if title_row else "") or "") if title_row else ""
        rows = db.execute(
            "select id, name, full_name, aliases, identity, importance, metadata "
            "from character_cards where script_id=%s and card_type='npc' "
            "order by importance desc, id asc limit %s",
            (script_id, int(max_cards)),
        ).fetchall()
    cards = [dict(r) for r in rows]
    if len(cards) < 2:
        return {"summary": {"merged": [], "protagonist": None, "dropped": []},
                "message": "Fewer than 2 NPC cards; nothing to review", "cards_reviewed": len(cards),
                "model": f"{api_id}/{model}"}

    # 凭证预检(用户当场选的 provider)。强鉴权下缺 key → 抛错让前端引导去配。
    from core.config import require_auth as _require_auth
    from platform_app.user_credentials import resolve_api_key
    if _require_auth():
        cred = resolve_api_key(user_id, api_id, env_fallback="")
        if not cred.get("key"):
            raise import_pipeline.MissingUserCredentialError(
                api_id=api_id, model=model,
                credential_api_id=import_pipeline._credential_api_id_for(api_id))

    # 结构化微任务禁深思(268 实锤族)+空正文护栏
    from agents._harness import call_agent_json_guarded
    chunks = [cards[i:i + _AUDIT_CHUNK] for i in range(0, len(cards), _AUDIT_CHUNK)]
    total = len(chunks)
    cards_by_id = {int(c["id"]): c for c in cards}
    agg: dict[str, Any] = {"merged": [], "protagonist": None, "dropped": []}
    protagonist_id: int | None = None
    parse_failures = 0

    for idx, chunk in enumerate(chunks):
        n = len(chunk)
        try:
            text, _usage = call_agent_json_guarded(
                api_id, model, _AUDIT_SYSTEM, _build_user_prompt(title, chunk), user_id,
                log_tag="card_audit", no_think=True,
                max_tokens=_AUDIT_MAX_TOKENS, timeout_sec=_AUDIT_TIMEOUT, agent_kind="card_audit",
                metadata_extra={"script_id": script_id, "cards": n, "chunk": idx, "chunks": total},
            )
            verdict = _parse_json_obj(text)
        except Exception:  # noqa: BLE001 — 单批失败不该让整次复核全废(其余批仍处理)
            verdict = {}
        if not verdict:
            parse_failures += 1
        else:
            # 第 0 批 importance 最高 → 主角必在此;仅此批的 protagonist_id 采纳,其余批只做合并/删除。
            if idx == 0:
                protagonist_id = _cid(verdict.get("protagonist_id"))
            chunk_by_id = {int(c["id"]): c for c in chunk}
            with connect() as db:
                _require_script_owner(db, user_id, script_id)
                part = _apply_verdicts(db, script_id, chunk_by_id, verdict, apply_protagonist=False)
            agg["merged"].extend(part["merged"])
            agg["dropped"].extend(part["dropped"])
        if progress_cb:
            try:
                progress_cb(idx + 1, total)
            except Exception:  # noqa: BLE001
                pass

    if total and parse_failures == total:
        raise ValueError("Could not parse the AI review output. Try again or switch to another model.")

    # 全局主角:取自第 0 批(若该卡已在某批被并走则跳过,保守)。
    if protagonist_id and protagonist_id in cards_by_id:
        with connect() as db:
            _require_script_owner(db, user_id, script_id)
            row = _db_set_protagonist(db, script_id, protagonist_id)
            if row:
                agg["protagonist"] = cards_by_id[protagonist_id]["name"]

    agg["cards_reviewed"] = len(cards)
    return {"summary": agg, "model": f"{api_id}/{model}", "chunks": total,
            "parse_failures": parse_failures}


def schedule_card_audit(user_id: int, script_id: int, api_id: str = "", model: str = "") -> dict[str, Any]:
    """异步调度 NPC 卡 AI 复核(单次 LLM 裁决)→ 进 import_jobs,全局后台任务浮窗自动跟踪。返 {ok, job_id}。

    复核本身是【一次】LLM 调用(非逐卡循环),所以没有真实百分比 —— 浮窗按 spinner 显示(与生图一致),
    完成后从 import_jobs.budget_estimate.result 读回摘要。凭证预检在调度【前】同步做(缺 key 立即返
    credentials_required,不进队列空转);owner 校验同理。复用同剧本进行中的复核任务,避免重复触发。
    """
    init_db()
    import secrets

    from platform_app import import_pipeline
    rapi, rmodel = _resolve_audit_model(user_id, api_id, model)

    with connect() as db:
        _require_script_owner(db, user_id, script_id)

    # 凭证预检(与同步版一致,放在 spawn 前):缺 key → 抛 MissingUserCredentialError,端点转 credentials_required。
    from core.config import require_auth as _require_auth
    from platform_app.user_credentials import resolve_api_key
    if _require_auth() and rapi:
        cred = resolve_api_key(user_id, rapi, env_fallback="")
        if not cred.get("key"):
            raise import_pipeline.MissingUserCredentialError(
                api_id=rapi, model=rmodel,
                credential_api_id=import_pipeline._credential_api_id_for(rapi))

    from platform_app.import_pipeline.liveness import reap_dead_jobs_quietly, start_job_thread
    reap_dead_jobs_quietly(user_id=user_id)
    with connect() as db:
        existing = db.execute(
            "select job_id from import_jobs where user_id=%s and script_id=%s and kind=%s "
            "and status in ('pending','queued','running') order by id desc limit 1",
            (user_id, script_id, "cards_audit"),
        ).fetchone()
        if existing:
            return {"ok": True, "job_id": existing["job_id"], "reused": True}
        job_id = f"audit_{script_id}_{secrets.token_hex(6)}"
        db.execute(
            "insert into import_jobs(job_id, user_id, script_id, kind, status, stage, "
            "module, sub_kind, overall_total, budget_estimate, stages) "
            "values (%s,%s,%s,%s,'pending','pending',%s,%s,1,%s,%s)",
            (
                job_id, user_id, script_id, "cards_audit",
                "cards_audit", "cards_audit",
                Jsonb({"action": "AI character card audit", "api_id": rapi, "model": rmodel}),
                Jsonb([{"id": "audit", "label": "AI character card audit", "status": "pending"}]),
            ),
        )
    start_job_thread(job_id, _run_card_audit, (job_id, user_id, script_id, rapi, rmodel))
    return {"ok": True, "job_id": job_id, "reused": False}


def _run_card_audit(job_id: str, user_id: int, script_id: int, api_id: str, model: str) -> None:
    """复核 worker:统一 import_jobs 状态机。done 时把摘要写进 budget_estimate.result(前端读回)。"""
    from platform_app.import_pipeline import JobController
    ctl = JobController(job_id)
    ctl.update(status="running", stage="audit", overall_progress=0, overall_total=100,
               stages=[{"id": "audit", "label": "AI character card audit", "status": "running"}])
    with connect() as db:
        db.execute("update import_jobs set started_at=now() where job_id=%s", (job_id,))
    try:
        def _prog(done: int, total: int) -> None:
            try:
                pct = int(done * 100 / max(total, 1))
                ctl.update(stage="audit", stage_progress=done, stage_total=max(total, 1),
                           overall_progress=pct, overall_total=100)
            except Exception:  # noqa: BLE001
                pass
        result = audit_character_cards(user_id, script_id, api_id, model, progress_cb=_prog)
        with connect() as db:
            # 合并进 budget_estimate(保留 insert 时写入的 api_id/model),供 get_job_status 暴露给前端。
            db.execute(
                "update import_jobs set budget_estimate = budget_estimate || %s where job_id=%s",
                (Jsonb({"result": result}), job_id),
            )
        ctl.update(status="done", stage="audit", overall_progress=1, overall_total=1,
                   stages=[{"id": "audit", "label": "AI character card audit", "status": "done"}])
        with connect() as db:
            db.execute("update import_jobs set finished_at=now() where job_id=%s", (job_id,))
    except Exception as exc:  # noqa: BLE001
        ctl.update(status="failed", stage="audit", error=str(exc),
                   stages=[{"id": "audit", "label": "AI character card audit", "status": "failed"}])
        with connect() as db:
            db.execute("update import_jobs set finished_at=now() where job_id=%s", (job_id,))


def _apply_verdicts(db, script_id: int, cards_by_id: dict, verdict: dict,
                    *, apply_protagonist: bool = True) -> dict:
    """确定性应用 LLM 裁决。保守:id 必须真实存在;被并/删的不再二次处理;主角被并走则用保留卡。

    apply_protagonist=False:分批送审时由调用方在全局只采纳第 0 批的主角并统一应用,这里跳过主角锁定。
    """
    out: dict[str, Any] = {"merged": [], "protagonist": None, "dropped": []}
    deleted: set[int] = set()
    merged_into: dict[int, int] = {}

    # 1) 合并同一人
    for grp in (verdict.get("merges") or []):
        if not isinstance(grp, dict):
            continue
        keep = _cid(grp.get("keep"))
        if keep is None or keep not in cards_by_id or keep in deleted:
            continue
        merge_ids = [m for m in (_cid(x) for x in (grp.get("merge_ids") or []))
                     if m and m in cards_by_id and m != keep and m not in deleted]
        if not merge_ids:
            continue
        keep_card = cards_by_id[keep]
        new_aliases = set(_as_list(keep_card.get("aliases")))
        max_imp = int(keep_card.get("importance") or 0)
        for mid in merge_ids:
            mc = cards_by_id[mid]
            new_aliases.add(str(mc["name"]))
            new_aliases.update(_as_list(mc.get("aliases")))
            max_imp = max(max_imp, int(mc.get("importance") or 0))
            merged_into[mid] = keep
        new_aliases.discard(str(keep_card["name"]))
        db.execute(
            "update character_cards set aliases=%s, importance=%s, "
            "row_version=row_version+1, updated_at=now() "
            "where id=%s and script_id=%s and card_type='npc'",
            (Jsonb(sorted(new_aliases)), max_imp, keep, script_id),
        )
        for mid in merge_ids:
            db.execute("delete from character_cards where id=%s and script_id=%s and card_type='npc'",
                       (mid, script_id))
            deleted.add(mid)
        out["merged"].append({"keep": keep_card["name"],
                              "merged": [cards_by_id[m]["name"] for m in merge_ids]})

    # 2) 删除非人名
    for nid in (_cid(x) for x in (verdict.get("non_person_ids") or [])):
        if nid and nid in cards_by_id and nid not in deleted:
            db.execute("delete from character_cards where id=%s and script_id=%s and card_type='npc'",
                       (nid, script_id))
            deleted.add(nid)
            out["dropped"].append(cards_by_id[nid]["name"])

    # 3) 锁定主角(若主角卡被并走 → 用保留卡)。分批模式由调用方统一处理 → 跳过。
    if apply_protagonist:
        pid = _cid(verdict.get("protagonist_id"))
        pid = merged_into.get(pid, pid)
        if pid and pid in cards_by_id and pid not in deleted:
            row = _db_set_protagonist(db, script_id, pid)
            if row:
                out["protagonist"] = cards_by_id[pid]["name"]
    return out
