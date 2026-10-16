"""import_pipeline.liveness — 后台 import_jobs 的存活心跳 + 死任务回收(单一真源)。

问题:导入 / 重建 / LLM 提取 / 卡审 / 账户导入都在本进程 daemon 线程里跑。进程被杀或重启
(本地一键启停、崩溃、部署)时 finally 永远不执行,行停在 pending/queued/running:
  · per-user 并发闸(「你已有导入任务在跑」)把用户锁死;
  · 「取消」只置 cancel_requested,等一个已经不存在的 worker 去读 → 永远「取消中」;
  · 唯一兜底 reap_zombie_import_jobs 要等 6 小时。

做法(确定性,不靠猜进度):
  1. start_job_thread() 是这些任务唯一的起线程入口:起线程前先戳 heartbeat_at,线程存活期间
     进程内一根心跳线程每 HEARTBEAT_SECONDS 给所有在跑的 job 续 heartbeat_at。
     排队等信号量的任务线程也活着,所以同样续命,不会被误收。
  2. reap_dead_jobs():heartbeat_at 超过 DEAD_AFTER_SECONDS 没续 = worker 已死 → 落终态
     (cancel_requested → cancelled,否则 failed)。在启动、取消、建新任务前的并发闸、
     活跃任务列表处调用,所以死任务不会挡路。
  3. 本地(单进程)模式启动时,本进程刚起,任何非终态任务都不可能有活 worker → 直接全部收尾。

knowledge_sync 不归这里管:它有自己的心跳 + 重新入队恢复(script_import.sync_jobs)。
heartbeat_at 为空的行(本机制上线前的老行)也不碰,留给 6 小时兜底。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from ..db import connect, init_db

log = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 20.0
_ACTIVE = ("pending", "queued", "running")
_WORKER_LOST = "worker stopped (backend restarted or crashed); start it again"


def dead_after_seconds() -> float:
    try:
        return max(30.0, float(os.environ.get("IMPORT_JOB_DEAD_AFTER_SECONDS", "120")))
    except (TypeError, ValueError):
        return 120.0


_live: set[str] = set()
_live_lock = threading.Lock()
_hb_thread: threading.Thread | None = None


def live_job_ids() -> set[str]:
    with _live_lock:
        return set(_live)


def _touch(job_ids: list[str]) -> None:
    if not job_ids:
        return
    init_db()
    with connect() as db:
        db.execute(
            "update import_jobs set heartbeat_at = now() "
            "where job_id = any(%s) and status in ('pending', 'queued', 'running')",
            (job_ids,),
        )


def _heartbeat_loop() -> None:
    while True:
        time.sleep(HEARTBEAT_SECONDS)
        try:
            _touch(sorted(live_job_ids()))
        except Exception:
            log.warning("[job-liveness] heartbeat update failed", exc_info=True)


def _ensure_heartbeat_thread() -> None:
    global _hb_thread
    with _live_lock:
        if _hb_thread is not None and _hb_thread.is_alive():
            return
        _hb_thread = threading.Thread(target=_heartbeat_loop, name="import-job-heartbeat", daemon=True)
        _hb_thread.start()


def start_job_thread(job_id: str, target: Callable[..., Any], args: tuple = ()) -> threading.Thread:
    """起一个 import_jobs 后台 worker 线程,并让它在存活期间持续续心跳。"""
    with _live_lock:
        _live.add(job_id)
    try:
        _touch([job_id])
    except Exception:
        log.warning("[job-liveness] initial heartbeat failed for %s", job_id, exc_info=True)
    _ensure_heartbeat_thread()

    def _tracked() -> None:
        try:
            target(*args)
        finally:
            with _live_lock:
                _live.discard(job_id)

    th = threading.Thread(target=_tracked, name=f"job-{job_id}", daemon=True)
    th.start()
    return th


def reap_dead_jobs(*, user_id: int | None = None, job_id: str | None = None,
                   all_unfinished: bool = False) -> list[dict[str, Any]]:
    """把 worker 已死的非终态任务落终态,返回被收尾的 [{job_id, kind, status}]。

    all_unfinished=True 只给「本进程刚启动且是唯一 worker」(本地模式启动)用:不看心跳,
    所有非终态任务(knowledge_sync 除外)一律收尾。
    """
    conds = ["j.status in ('pending', 'queued', 'running')", "j.kind <> 'knowledge_sync'"]
    params: list[Any] = []
    if not all_unfinished:
        conds.append("j.heartbeat_at is not null")
        conds.append("j.heartbeat_at < now() - make_interval(secs => %s)")
        params.append(dead_after_seconds())
        live = sorted(live_job_ids())
        if live:
            conds.append("not (j.job_id = any(%s))")
            params.append(live)
    if user_id is not None:
        conds.append("j.user_id = %s")
        params.append(int(user_id))
    if job_id is not None:
        conds.append("j.job_id = %s")
        params.append(job_id)
    params = [_WORKER_LOST, *params]
    init_db()
    with connect() as db:
        rows = db.execute(
            f"""
            update import_jobs j
               set status = case when j.cancel_requested then 'cancelled' else 'failed' end,
                   finished_at = coalesce(j.finished_at, now()),
                   error = case when j.cancel_requested or coalesce(j.error, '') <> '' then j.error
                                else %s end,
                   updated_at = now()
             where {' and '.join(conds)}
            returning j.job_id, j.kind, j.status
            """,
            tuple(params),
        ).fetchall()
    reaped = [{"job_id": r["job_id"], "kind": r.get("kind"), "status": r.get("status")} for r in rows]
    if reaped:
        log.warning("[job-liveness] closed %d job(s) whose worker is gone: %s",
                    len(reaped), [r["job_id"] for r in reaped])
    return reaped


def reap_dead_jobs_quietly(**kwargs: Any) -> list[dict[str, Any]]:
    """reap_dead_jobs 的不抛版本,给并发闸 / 列表接口这类「顺手清一下」的调用点用。"""
    try:
        return reap_dead_jobs(**kwargs)
    except Exception:
        log.warning("[job-liveness] reap failed", exc_info=True)
        return []
