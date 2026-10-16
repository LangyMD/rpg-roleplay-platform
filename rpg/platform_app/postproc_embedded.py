"""platform_app.postproc_embedded — run the chat_postproc_tasks consumer inside the web process.

Server deployments run `scripts/run_postproc_worker.py` as its own service. Local / desktop
installs never started it, so everything queued to `chat_postproc_tasks` (image generation,
acceptance verifier, black swan) sat in the queue forever. In local mode the lifespan starts
this daemon thread instead; claims are CAS-based, so an external worker running alongside is
harmless.

Env: RPG_EMBEDDED_POSTPROC=1 forces it on, =0 forces it off; unset → on in local modes only.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading

log = logging.getLogger("rpg.postproc_embedded")

_thread: threading.Thread | None = None


def embedded_postproc_wanted() -> bool:
    raw = os.environ.get("RPG_EMBEDDED_POSTPROC", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False  # test clients run the lifespan; never consume the shared test DB queue
    try:
        from core.config import is_local_deployment_mode
        return bool(is_local_deployment_mode())
    except Exception:
        return False


def _run() -> None:
    import psycopg
    import psycopg.rows

    from platform_app.db.connection import database_url
    from scripts.run_postproc_worker import consume

    try:
        conn = psycopg.connect(database_url(), autocommit=True, row_factory=psycopg.rows.dict_row)
    except Exception:
        log.exception("[postproc-embedded] cannot connect; queued post-turn tasks will not run")
        return
    log.info("[postproc-embedded] started in-process worker")
    try:
        asyncio.run(consume(conn))
    except Exception:
        log.exception("[postproc-embedded] worker stopped")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_embedded_postproc() -> bool:
    """Start the daemon consumer once per process when wanted. Returns True if started."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return False
    if not embedded_postproc_wanted():
        return False
    _thread = threading.Thread(target=_run, name="postproc-embedded", daemon=True)
    _thread.start()
    return True
