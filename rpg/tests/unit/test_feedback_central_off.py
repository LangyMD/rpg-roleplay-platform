"""RPG_CENTRAL_URL=off:local 模式反馈绝不出本机(隐私开关)。未设置时仍转发到默认中央地址。"""
from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException


class TestFeedbackCentralOff(unittest.TestCase):
    def _forward(self):
        from platform_app.api.feedback import _forward_feedback_to_central
        return asyncio.run(_forward_feedback_to_central({"free_text": "x"}, "ua"))

    def test_off_values_block_forwarding_without_network(self):
        for val in ("off", "OFF", " 0 ", "none", "disabled", "false"):
            with self.subTest(val=val), \
                 patch.dict(os.environ, {"RPG_CENTRAL_URL": val}), \
                 patch("httpx.AsyncClient") as client:
                with self.assertRaises(HTTPException) as cm:
                    self._forward()
                self.assertEqual(cm.exception.status_code, 503)
                client.assert_not_called()

    def test_unset_still_forwards_to_default(self):
        env = {k: v for k, v in os.environ.items() if k != "RPG_CENTRAL_URL"}
        posted = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"feedback_id": 1}

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

        with patch.dict(os.environ, env, clear=True), patch("httpx.AsyncClient", _Client):
            self._forward()
        self.assertEqual(posted["url"], "https://rpg-roleplay.stellatrix.icu/api/feedback/anon")


if __name__ == "__main__":
    unittest.main()
