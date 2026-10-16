"""call_structured:端点拒绝 response_format=json_object(400)时去掉它重发,并记住该 combo。

回归:LM Studio 返回「'response_format.type' must be 'json_schema' or 'text'」,
本地模型跑「重建规范实体」每一弧都失败。
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai

from agents.gm.backends import openai_compat


def _resp(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=None,
    )


def _bad_request():
    req = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    return openai.BadRequestError(
        "'response_format.type' must be 'json_schema' or 'text'",
        response=httpx.Response(400, request=req), body=None,
    )


def test_json_object_rejected_falls_back_and_remembers(monkeypatch):
    calls = []

    def fake_create(self, **kw):
        calls.append(dict(kw))
        if "response_format" in kw:
            raise _bad_request()
        return _resp('{"ok": 1}')

    monkeypatch.setattr(openai_compat._OpenAICompatBackend, "_create", fake_create)
    monkeypatch.setattr(openai_compat._OpenAICompatBackend, "_no_json_object_combos", set())
    b = object.__new__(openai_compat._OpenAICompatBackend)
    b.api_id, b.model_name, b.user_id = "lm-studio", "local", 1
    b.last_usage = {}
    b._to_messages = lambda s, m: [{"role": "system", "content": s}, *m]
    b._capture_usage = lambda *a, **k: None

    assert b.call_structured("sys", [{"role": "user", "content": "u"}], 100) == '{"ok": 1}'
    assert ["response_format" in c for c in calls] == [True, False]
    calls.clear()
    assert b.call_structured("sys", [{"role": "user", "content": "u"}], 100) == '{"ok": 1}'
    assert ["response_format" in c for c in calls] == [False]
