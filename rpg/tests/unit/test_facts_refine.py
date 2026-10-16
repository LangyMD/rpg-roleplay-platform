"""拆书审计 R2/R3/R4 修复单测:LLM 精炼验收 / 句边界截断 / 残句指纹检测。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chapter_fact_indexer import _sentence_truncate, _summary_from_events  # noqa: E402
from console_assistant.editor_context import _is_garbage_summary  # noqa: E402
from extract.facts_refine import build_refine_prompts, validate_refined  # noqa: E402

_CONTENT = (
    "林有德耸了耸肩，说：“我和司令官先生进行了友好的切磋，他对我的看法表示赞赏。”"
    "随后他转身离开了指挥部,外面的战姬们正在列队。" * 6
)


# ── validate_refined ─────────────────────────────────────────────────

def _raw(summary, itime="穿越次日下午"):
    return json.dumps({"chapter_summary": summary, "in_world_time": itime}, ensure_ascii=False)


def test_accepts_real_summary():
    out = validate_refined(_raw("林有德在指挥部与司令官会面并获得认可,离开时注意到战姬部队正在集结,他开始思考如何利用先知优势立足。"), _CONTENT)
    assert out and out["in_world_time"] == "穿越次日下午"


def test_rejects_verbatim_copy():
    """照抄原文 25 字连续片段 → 拒(schema 铁律:绝不照抄)。"""
    copied = "林有德耸了耸肩，说：“我和司令官先生进行了友好的切磋，他对我的看法表示赞赏。”"
    assert validate_refined(_raw(copied), _CONTENT) is None


def test_rejects_too_short_and_garbage():
    assert validate_refined(_raw("太短了"), _CONTENT) is None
    assert validate_refined("不是JSON", _CONTENT) is None


def test_fence_stripped():
    ok = "```json\n" + _raw("林有德离开指挥部后观察战姬列队,决定先弄清这个世界的军事格局再谋出路,为此他准备接近司令部的参谋们。") + "\n```"
    assert validate_refined(ok, _CONTENT) is not None


_EN_CONTENT = ("The miller's daughter carried the letter across the frozen river at dawn, "
               "and nobody in the village saw her leave. ") * 8


def test_accepts_english_summary_longer_than_cjk_cap():
    # ~70 words ≈ 420 chars: over the 200-char CJK cap, within the English equivalent
    summary = ("Mara slips out of the village before sunrise to deliver a sealed letter to the garrison. "
               "On the way she meets a deserter who warns her that the captain is not who he claims to be, "
               "and she must decide whether to trust him or finish the errand. She hides the letter, "
               "follows the deserter to an abandoned mill, and learns the garrison plans to burn the bridge.")
    assert len(summary) > 200
    out = validate_refined(_raw(summary, "dawn of the first frost"), _EN_CONTENT)
    assert out and out["summary"] == summary and out["in_world_time"] == "dawn of the first frost"


def test_rejects_english_copy_of_source():
    copied = "The miller's daughter carried the letter across the frozen river at dawn, and nobody saw it."
    assert validate_refined(_raw(copied), _EN_CONTENT) is None


def test_prompts_carry_title_and_body():
    sys_p, usr_p = build_refine_prompts("第1章 穿越", "正文内容" * 10)
    assert "Never copy" in sys_p and "第1章 穿越" in usr_p


# ── _sentence_truncate(R2 确定性侧) ─────────────────────────────────

def test_truncate_at_sentence_boundary():
    s = ("这是第一句话。" * 33)  # 231 字帧,加尾巴后超 240
    long = s + "这是最后一个不完整的句子会被截断在词中间xxxxxxxxxxxxxxxx"
    out = _sentence_truncate(long)
    assert out.endswith("。") and len(out) <= 240


def test_truncate_short_untouched():
    assert _sentence_truncate("短句。") == "短句。"


def test_summary_from_events_uses_boundary():
    ev = [{"event": "很长的事件描述" + "内容" * 60}]
    out = _summary_from_events(ev, [])
    assert len(out) <= 240


# ── _is_garbage_summary(R4 残句指纹) ────────────────────────────────

def test_garbage_divider_still_caught():
    assert _is_garbage_summary("======")


def test_fragment_starting_with_close_quote():
    assert _is_garbage_summary("”这时候有人对林有德说，“大炮可是很笨重的")


def test_hard_cut_tail_caught():
    frag = "林有德说了很多" + "内容" * 113  # ≥232 字且无句尾标点
    assert _is_garbage_summary(frag[:235])


def test_real_summary_passes():
    assert not _is_garbage_summary("林有德在指挥部与司令官会面并获得认可,随后开始筹划如何在这个战姬世界立足。")
