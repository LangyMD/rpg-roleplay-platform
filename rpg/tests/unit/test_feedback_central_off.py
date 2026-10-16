"""local 模式反馈隐私默认:RPG_CENTRAL_URL 未设置 / off → 反馈存本机库,绝不出本机;
只有显式设成 URL 才转发到该中央服务器。"""
from __future__ import annotations

import asyncio
import os
import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

_VALID_TOKEN = "a" * 64


class _Resp:
    status_code = 200

    def json(self):
        return {"feedback_id": 1}


def _make_client(posted: dict):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            posted["url"] = url
            return _Resp()

    return _Client


def _env_without_central(**extra):
    env = {k: v for k, v in os.environ.items() if k != "RPG_CENTRAL_URL"}
    env.update(extra)
    return env


class TestCentralFeedbackBase(unittest.TestCase):
    def test_unset_and_off_values_mean_local(self):
        from platform_app.api.feedback import _central_feedback_base
        with patch.dict(os.environ, _env_without_central(), clear=True):
            self.assertIsNone(_central_feedback_base())
        for val in ("", "off", "OFF", " 0 ", "none", "disabled", "false", "not-a-url"):
            with self.subTest(val=val), patch.dict(os.environ, {"RPG_CENTRAL_URL": val}):
                self.assertIsNone(_central_feedback_base())

    def test_explicit_url_enables_forwarding(self):
        from platform_app.api.feedback import _central_feedback_base
        with patch.dict(os.environ, {"RPG_CENTRAL_URL": "https://central.example/"}):
            self.assertEqual(_central_feedback_base(), "https://central.example")


class TestForwardFeedback(unittest.TestCase):
    def _forward(self):
        from platform_app.api.feedback import _forward_feedback_to_central
        return asyncio.run(_forward_feedback_to_central({"free_text": "x"}, "ua"))

    def test_off_or_unset_blocks_forwarding_without_network(self):
        for val in (None, "off", "OFF", " 0 ", "none", "disabled", "false"):
            env = _env_without_central() if val is None else _env_without_central(RPG_CENTRAL_URL=val)
            with self.subTest(val=val), \
                 patch.dict(os.environ, env, clear=True), \
                 patch("httpx.AsyncClient") as client:
                with self.assertRaises(HTTPException) as cm:
                    self._forward()
                self.assertEqual(cm.exception.status_code, 503)
                client.assert_not_called()

    def test_explicit_url_forwards_there(self):
        posted: dict = {}
        with patch.dict(os.environ, _env_without_central(RPG_CENTRAL_URL="https://central.example"), clear=True), \
             patch("httpx.AsyncClient", _make_client(posted)):
            self._forward()
        self.assertEqual(posted["url"], "https://central.example/api/feedback/anon")


class _FakeRow(dict):
    pass


class _FakeDB:
    def __init__(self, log: list):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append(sql)

        class _Cur:
            def fetchone(self_inner):
                return _FakeRow(id=42)

            def fetchall(self_inner):
                return []

        return _Cur()


class _FakeRequest:
    headers = {"user-agent": "ua"}

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class TestSubmitFeedbackLocalMode(unittest.TestCase):
    @contextmanager
    def _local_env(self, **env_extra):
        sql_log: list = []

        @contextmanager
        def _fake_connect():
            yield _FakeDB(sql_log)

        with patch.dict(os.environ, _env_without_central(**env_extra), clear=True), \
             patch("core.config.deployment_mode", return_value="local"), \
             patch("platform_app.api.feedback.connect", _fake_connect), \
             patch("platform_app.api.feedback._client_ip", return_value="127.0.0.1"), \
             patch("platform_app.api.feedback._capture_feedback_env", return_value={}), \
             patch("platform_app.api.feedback.moderate_feedback", new=AsyncMock()) as mod:
            yield sql_log, mod

    def _submit(self):
        from platform_app.api.feedback import submit_feedback
        body = {"free_text": "hello", "excerpts": [], "consent_token": _VALID_TOKEN}
        return asyncio.run(submit_feedback(_FakeRequest(body), user={"id": 7}))

    def test_unset_central_stores_locally_and_never_hits_network(self):
        with self._local_env() as (sql_log, mod), patch("httpx.AsyncClient") as client:
            resp = self._submit()
        client.assert_not_called()
        mod.assert_not_called()  # no third-party moderation call in local mode
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any("insert into feedback" in s and "contact_email" in s for s in sql_log))
        self.assertTrue(any("insert into feedback_consent_log" in s for s in sql_log))

    def test_explicit_central_url_forwards(self):
        posted: dict = {}
        with self._local_env(RPG_CENTRAL_URL="https://central.example") as (sql_log, _mod), \
             patch("httpx.AsyncClient", _make_client(posted)):
            self._submit()
        self.assertEqual(posted["url"], "https://central.example/api/feedback/anon")
        self.assertEqual(sql_log, [])


if __name__ == "__main__":
    unittest.main()
