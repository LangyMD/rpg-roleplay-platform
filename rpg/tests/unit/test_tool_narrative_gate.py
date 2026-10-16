"""修2(孪生洞):GM 自主叙事记忆写入的【工具调用面】必须走权限闸门。

台账 2026-07-07 的 JSON-op 面(apply_structured_updates)已在 test_narrative_op_gate.py
锁死;本文件锁其孪生 —— function-calling 工具面:
  · schedule_consequence(command_tools_consequence._t_schedule_consequence)→ register_consequence
  · add_hypothesis        (command_tools._exec_add_hypothesis)              → add_hypothesis

这两个工具原直调对应 state 专用方法,绕过 apply_state_write 权限闸门 —— read_only 也拦不住,
与 JSON-op 面同病。修复:read_only/default 且非玩家主动 origin 时经 add_pending_narrative_op
入 pending(与 JSON-op 面同队列、同 _approve_narrative_op_pending 回放),full_access 直写不变。

origin 语义:_origin 由 dispatcher 无条件注入(env.args["_origin"]=env.origin,不可被 LLM
伪造)。玩家主动 origin(ui_button/llm_set/api_direct)属玩家意志 → 豁免直写;GM 自主
(llm_chat/llm_chat_json_op)→ 受闸。本测试用 args["_origin"] 模拟 dispatcher 注入的 origin。

风格参照 tests/unit/test_narrative_op_gate.py(直接跑 state / 工具执行体,不起 DB/dispatcher)。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("RPG_REQUIRE_AUTH", "0")

from state import GameState  # noqa: E402
from tools_dsl.command_tools import execute_tool  # noqa: E402
from tools_dsl.command_tools_consequence import _t_schedule_consequence  # noqa: E402


def _pending(g) -> list:
    return (g.data.get("permissions", {}) or {}).get("pending_writes", []) or []


def _ledger(g) -> list:
    return g.data.get("consequence_ledger", []) or []


class ScheduleConsequenceToolGate(unittest.TestCase):
    def test_read_only_gm_consequence_goes_to_pending_not_ledger(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        res = _t_schedule_consequence(
            g, {"text": "答应帮铁匠找矿石", "due_turns": 4, "_origin": "llm_chat"}
        )
        self.assertEqual(_ledger(g), [], "read_only 下 GM 工具后果不得绕闸直写账本")
        pw = _pending(g)
        self.assertTrue(any(p.get("path") == "consequence" for p in pw),
                        f"后果应入 pending;实际={pw}")
        self.assertIn("pending approval", res, res)

    def test_default_mode_gm_consequence_also_pends(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "default"
        _t_schedule_consequence(
            g, {"text": "约定明早集合", "due_turns": 2, "_origin": "llm_chat_json_op"}
        )
        self.assertEqual(_ledger(g), [], "default 下 GM 工具后果也须入 pending")
        self.assertTrue(any(p.get("path") == "consequence" for p in _pending(g)))

    def test_approve_consequence_pending_lands_in_ledger(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        _t_schedule_consequence(
            g, {"text": "答应雷纳德带证据回村", "due_turns": 5, "_origin": "llm_chat"}
        )
        pid = _pending(g)[0]["id"]
        res = g.approve_pending_write(id=pid)
        self.assertIn("State write", res, res)
        ledger = _ledger(g)
        self.assertEqual(len(ledger), 1, "审批后应落地后果账本")
        self.assertEqual(ledger[0]["text"], "答应雷纳德带证据回村")
        self.assertEqual(_pending(g), [], "审批后 pending 应清空")

    def test_full_access_gm_consequence_writes_directly(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "full_access"
        res = _t_schedule_consequence(
            g, {"text": "欠债三日内还", "due_turns": 3, "_origin": "llm_chat"}
        )
        self.assertEqual(len(_ledger(g)), 1, "full_access 应直写")
        self.assertEqual(_pending(g), [], "full_access 不应产生 pending")
        self.assertIn("Consequence recorded", res, res)

    def test_player_origin_bypasses_gate_even_read_only(self):
        """玩家主动 origin(ui_button)属玩家意志 → 即便 read_only 也直写,不入 pending。"""
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        _t_schedule_consequence(
            g, {"text": "玩家亲自记一笔账", "due_turns": 1, "_origin": "ui_button"}
        )
        self.assertEqual(len(_ledger(g)), 1, "玩家主动 origin 应豁免直写")
        self.assertEqual(_pending(g), [], "玩家主动写入不入 pending")


class AddHypothesisToolGate(unittest.TestCase):
    def test_read_only_gm_hypothesis_goes_to_pending(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        res = execute_tool(
            g, "add_hypothesis", {"text": "凶手可能是管家", "_origin": "llm_chat"}
        )
        self.assertEqual(g.list_active_hypotheses(), [],
                         "read_only 下 GM 工具推测不得绕闸直写")
        self.assertTrue(any(p.get("path") == "hypothesis" for p in _pending(g)))
        self.assertIn("pending approval", res, res)

    def test_default_mode_gm_hypothesis_also_pends(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "default"
        execute_tool(
            g, "add_hypothesis", {"text": "密道通向地窖", "_origin": "llm_chat_json_op"}
        )
        self.assertEqual(g.list_active_hypotheses(), [], "default 下也须入 pending")
        self.assertTrue(any(p.get("path") == "hypothesis" for p in _pending(g)))

    def test_approve_hypothesis_pending_lands_active(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        execute_tool(
            g, "add_hypothesis",
            {"text": "凶手可能是管家", "time_label": "案发当夜",
             "characters": ["管家"], "_origin": "llm_chat"},
        )
        pid = _pending(g)[0]["id"]
        g.approve_pending_write(id=pid)
        active = g.list_active_hypotheses()
        self.assertEqual(len(active), 1, "审批后推测应转 active")
        self.assertEqual(active[0]["text"], "凶手可能是管家")
        self.assertEqual(_pending(g), [], "审批后 pending 应清空")

    def test_full_access_gm_hypothesis_writes_directly(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "full_access"
        execute_tool(
            g, "add_hypothesis", {"text": "凶手另有其人", "_origin": "llm_chat"}
        )
        self.assertEqual(len(g.list_active_hypotheses()), 1, "full_access 应直写")
        self.assertEqual(_pending(g), [])

    def test_player_origin_bypasses_gate_even_read_only(self):
        """玩家主动 origin(llm_set = /set 命令)属玩家意志 → read_only 也直写。"""
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        execute_tool(
            g, "add_hypothesis", {"text": "玩家亲手记的推测", "_origin": "llm_set"}
        )
        self.assertEqual(len(g.list_active_hypotheses()), 1, "玩家主动 origin 应豁免直写")
        self.assertEqual(_pending(g), [], "玩家主动写入不入 pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)
