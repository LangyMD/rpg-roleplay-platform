"""时间线战役批次1:揭示天花板估章钳制 单测。

生产实锤(save 268):occurred 冻结 ch7 十天,估章把 progress_chapter 顶到 17,
ch8-17 世界书/实体被超前揭示。钳制=有确定性地板才钳(发散无锚档解冻语义保留),
玩家 /set 显式跳章走 user_progress_floor 放行(逃生阀 d50eb926a)。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gm_serving.settings import clamp_reveal_progress  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]


def test_estimate_runaway_clamped_to_floor_plus_lookahead():
    # save 268 实况:occurred=7,估章=17 → 钳到 10
    assert clamp_reveal_progress(17, det_floor=7, lookahead=3) == 10


def test_progress_within_lookahead_untouched():
    assert clamp_reveal_progress(9, det_floor=7, lookahead=3) == 9
    assert clamp_reveal_progress(7, det_floor=7, lookahead=3) == 7


def test_no_floor_no_clamp_divergent_saves_keep_unfreeze():
    # 纯发散/无锚档:det_floor=0 → 不钳,progress_motion 解冻语义保留
    assert clamp_reveal_progress(42, det_floor=0, lookahead=3) == 42


def test_user_set_floor_bypasses_clamp():
    # 玩家 /set 显式跳到 17:user_floor 抬高确定性地板 → 17 放行
    assert clamp_reveal_progress(17, det_floor=17, lookahead=3) == 17


def test_lookahead_zero_disables_clamp():
    assert clamp_reveal_progress(17, det_floor=7, lookahead=0) == 17
    assert clamp_reveal_progress(17, det_floor=7, lookahead=-1) == 17


def test_source_guard_retrieval_applies_clamp():
    src = (_ROOT / "retrieval" / "assemble.py").read_text(encoding="utf-8")  # 拆包后 retrieve_context 住 retrieval/assemble.py
    assert "clamp_reveal_progress" in src, "retrieval 揭示进度必须过钳制"
    assert "user_progress_floor" in src, "钳制必须读玩家显式地板"


def test_source_guard_set_escape_valve_writes_floor():
    src = (_ROOT / "tools_dsl" / "command_tools.py").read_text(encoding="utf-8")
    i = src.index("advance_story_progress failed: no active save")
    window = src[i:i + 1500]
    assert "set_user_progress_floor" in window, "/set 显式跳章必须写 user_progress_floor(逃生阀)"


def test_source_guard_floor_key_sticky():
    src = (_ROOT / "platform_app" / "knowledge" / "_session_repo.py").read_text(encoding="utf-8")
    assert "'user_progress_floor'" in src, "user_progress_floor 必须在 PRESERVE sticky 键里"


def test_source_guard_recorder_private_scene_exclusion():
    src = (_ROOT / "agents" / "recorder.py").read_text(encoding="utf-8")
    assert "Purely private / everyday / romantic scenes" in src, "估章 prompt 必须排除生活流场景(save 268 误判根源)"
