"""重建 / LLM 提取入口没显式给模型时,必须回落到用户的「提取模型」设置,而不是硬编码 deepseek。

回归:只配了本地模型(LM Studio)的用户点「重建规范实体」→ 报「deepseek 未配置 key」。
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

RPG = Path(__file__).resolve().parents[2]


def test_resolve_extraction_llm_falls_back_to_extractor_pref(monkeypatch):
    from platform_app.import_pipeline import stages_llm
    from platform_app.knowledge import llm_extract

    monkeypatch.setattr(stages_llm, "_resolve_extractor_llm",
                        lambda uid: ("lm-studio", "local-model"))
    assert llm_extract.resolve_extraction_llm(1) == ("lm-studio", "local-model")
    assert llm_extract.resolve_extraction_llm(1, None, None) == ("lm-studio", "local-model")
    # 显式给了就原样用
    assert llm_extract.resolve_extraction_llm(1, "openai", "gpt-x") == ("openai", "gpt-x")
    # 只给一半:缺的那个补
    assert llm_extract.resolve_extraction_llm(1, None, "m") == ("lm-studio", "m")


@pytest.mark.parametrize("fn_path", [
    ("platform_app.knowledge.llm_extract", "run_llm_extraction"),
    ("platform_app.import_pipeline.rebuild_modules", "rebuild_cards_with_llm"),
])
def test_entry_points_default_to_none(fn_path):
    import importlib
    mod = importlib.import_module(fn_path[0])
    sig = inspect.signature(getattr(mod, fn_path[1]))
    assert sig.parameters["model"].default is None
    assert sig.parameters["api_id"].default is None


@pytest.mark.parametrize("rel", [
    "platform_app/import_pipeline/rebuild_worker.py",
    "extract/job_runner.py",
    "platform_app/api/imports.py",
    "platform_app/knowledge/llm_extract.py",
    "platform_app/import_pipeline/rebuild_modules.py",
])
def test_no_hardcoded_deepseek_api_fallback(rel):
    src = (RPG / rel).read_text(encoding="utf-8")
    assert not re.search(r"""api_id\s*[=:].{0,60}["']deepseek["']""", src), rel
