"""import_jobs 存活心跳 + 死任务回收(platform_app/import_pipeline/liveness.py)。

回归:后端重启后,上一进程留下的 running 导入任务永远挂着 →「你已有导入任务在跑」锁死新导入,
「取消」永远停在「取消中」(没有活 worker 去读取消标记)。
"""
from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

RPG = Path(__file__).resolve().parents[2]


class _FakeDB:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=()):
        self.log.append((" ".join(sql.split()), tuple(params)))
        return self

    def fetchall(self):
        return [{"job_id": "imp_x", "kind": "full_pipeline", "status": "failed"}]


@pytest.fixture
def fake_db(monkeypatch):
    from platform_app.import_pipeline import liveness
    log: list = []

    @contextmanager
    def _connect():
        yield _FakeDB(log)

    monkeypatch.setattr(liveness, "connect", _connect)
    monkeypatch.setattr(liveness, "init_db", lambda: None)
    monkeypatch.setattr(liveness, "_ensure_heartbeat_thread", lambda: None)
    with liveness._live_lock:
        liveness._live.clear()
    return log


def test_reap_uses_heartbeat_and_skips_live_jobs(fake_db):
    from platform_app.import_pipeline import liveness
    with liveness._live_lock:
        liveness._live.add("alive_1")
    out = liveness.reap_dead_jobs(user_id=7)
    assert out == [{"job_id": "imp_x", "kind": "full_pipeline", "status": "failed"}]
    sql, params = fake_db[-1]
    assert "heartbeat_at is not null" in sql
    assert "heartbeat_at < now() - make_interval" in sql
    assert "kind <> 'knowledge_sync'" in sql
    assert "not (j.job_id = any(%s))" in sql
    assert ["alive_1"] in [p for p in params if isinstance(p, list)]
    assert 7 in params
    # 用户取消过的落 cancelled,否则 failed
    assert "case when j.cancel_requested then 'cancelled' else 'failed' end" in sql


def test_reap_all_unfinished_ignores_heartbeat(fake_db):
    from platform_app.import_pipeline import liveness
    liveness.reap_dead_jobs(all_unfinished=True)
    sql, _ = fake_db[-1]
    assert "heartbeat_at" not in sql.split("where", 1)[1]
    assert "status in ('pending', 'queued', 'running')" in sql


def test_start_job_thread_tracks_until_target_returns(fake_db):
    from platform_app.import_pipeline import liveness
    gate = threading.Event()
    seen = {}

    def _work(x):
        seen["live_during"] = "job_a" in liveness.live_job_ids()
        seen["x"] = x
        gate.wait(5)

    th = liveness.start_job_thread("job_a", _work, (42,))
    # 起线程前先戳一次心跳(不等心跳线程第一拍)
    assert any("set heartbeat_at = now()" in s and ["job_a"] in p for s, p in
               [(s, list(p)) for s, p in fake_db])
    gate.set()
    th.join(5)
    assert seen == {"live_during": True, "x": 42}
    assert "job_a" not in liveness.live_job_ids()


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_start_job_thread_untracks_on_exception(fake_db):
    from platform_app.import_pipeline import liveness

    def _boom():
        raise RuntimeError("x")

    th = liveness.start_job_thread("job_b", _boom)
    th.join(5)
    assert "job_b" not in liveness.live_job_ids()


def test_cancel_finalizes_immediately_when_worker_is_gone(monkeypatch):
    from platform_app.import_pipeline import runner

    class _DB:
        def execute(self, *a, **k):
            return self

        def fetchone(self):
            return {"status": "running"}

    @contextmanager
    def _connect():
        yield _DB()

    monkeypatch.setattr(runner, "connect", _connect)
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(runner, "reap_dead_jobs_quietly",
                        lambda **kw: [{"job_id": kw["job_id"], "status": "cancelled"}])
    assert runner.cancel_job(1, "imp_dead") == {"ok": True, "current_status": "cancelled"}
    monkeypatch.setattr(runner, "reap_dead_jobs_quietly", lambda **kw: [])
    assert runner.cancel_job(1, "imp_alive") == {"ok": True, "current_status": "running"}


# 孪生奇偶守卫:每个建 import_jobs 行并起后台 worker 的地方都必须走 start_job_thread,
# 否则那类任务没有心跳,进程重启后又会卡死。knowledge_sync 有自己的心跳/恢复,豁免。
_EXEMPT = {"platform_app/script_import/sync_jobs.py"}


def test_every_import_job_spawner_uses_start_job_thread():
    offenders = []
    for path in RPG.rglob("*.py"):
        rel = path.relative_to(RPG).as_posix()
        if rel.startswith((".venv/", "tests/")) or rel in _EXEMPT:
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"insert into import_jobs", src):
            continue
        if "start_job_thread(" not in src or re.search(r"threading\.Thread\(", src):
            offenders.append(rel)
    assert offenders == []
