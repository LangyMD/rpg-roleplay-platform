"""
test_consequence_ledger.py — 后果账本 v1 确定性脚手架测试。

设计文档: docs/design/consequence_ledger_v1.md §6

覆盖范围:
  · 触发判定纯函数(state.consequence_ledger):
      turns 到期 / 未到期、location 命中 / 不命中、fired 幂等
  · 上限(20 条 pending)与指纹去重
  · apply op 分支(apply_structured_updates 的 "consequence" JSON op):
      合法登记 / 缺字段拒绝且不崩
  · dispatcher 工具 schedule_consequence:成功路径 + origin 拦截
  · context provider(consequence_echo):
      gate 关 = skip、无触发 = 空、触发 = 含模板文案

所有测试不依赖 DB。
"""
from __future__ import annotations

import copy
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("RPG_REQUIRE_AUTH", "0")

from state import DEFAULT_STATE, GameState  # noqa: E402
from state.consequence_ledger import (  # noqa: E402
    MAX_PENDING,
    entries_for_injection,
    register_consequence,
    scan_and_fire,
)


def _new_state(turn: int = 0) -> GameState:
    s = GameState(copy.deepcopy(DEFAULT_STATE))
    s.data["turn"] = turn
    return s


# ────────────────────────────────────────────────────────────
# register_consequence
# ────────────────────────────────────────────────────────────

class RegisterConsequenceTests(unittest.TestCase):
    def test_register_turns_success(self):
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 12
        ok, msg = register_consequence(data, text="答应雷纳德查清林中兽伤", due_turns=5)
        self.assertTrue(ok, msg)
        ledger = data["consequence_ledger"]
        self.assertEqual(len(ledger), 1)
        entry = ledger[0]
        self.assertEqual(entry["text"], "答应雷纳德查清林中兽伤")
        self.assertEqual(entry["due"], {"turns": 5})
        self.assertEqual(entry["created_turn"], 12)
        self.assertEqual(entry["status"], "pending")
        self.assertIsNone(entry["fired_turn"])
        self.assertEqual(entry["origin"], "gm")
        self.assertTrue(entry["id"].startswith("cq_"))

    def test_register_location_success(self):
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 3
        ok, msg = register_consequence(data, text="答应给阿托菲村送药", due_location="阿托菲村")
        self.assertTrue(ok, msg)
        entry = data["consequence_ledger"][0]
        self.assertEqual(entry["due"], {"location": "阿托菲村"})

    def test_register_missing_text_rejected(self):
        data = copy.deepcopy(DEFAULT_STATE)
        ok, msg = register_consequence(data, text="", due_turns=5)
        self.assertFalse(ok)
        self.assertNotIn("consequence_ledger", data)  # 不应产生任何写入副作用

    def test_register_missing_due_rejected(self):
        """既无 due_turns 也无 due_location → 拒绝,且不崩。"""
        data = copy.deepcopy(DEFAULT_STATE)
        ok, msg = register_consequence(data, text="没有期限的承诺")
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_register_non_positive_turns_rejected(self):
        data = copy.deepcopy(DEFAULT_STATE)
        ok, msg = register_consequence(data, text="非法期限", due_turns=0)
        self.assertFalse(ok)
        ok2, _ = register_consequence(data, text="非法期限2", due_turns=-3)
        self.assertFalse(ok2)

    def test_register_bad_turns_type_rejected_no_crash(self):
        data = copy.deepcopy(DEFAULT_STATE)
        ok, msg = register_consequence(data, text="坏类型", due_turns="abc")
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_pending_limit_20(self):
        """超过 20 条 pending 拒绝并说明,不崩。"""
        data = copy.deepcopy(DEFAULT_STATE)
        for i in range(MAX_PENDING):
            ok, msg = register_consequence(data, text=f"承诺{i}", due_turns=i + 1)
            self.assertTrue(ok, msg)
        ok, msg = register_consequence(data, text="第21条", due_turns=1)
        self.assertFalse(ok)
        self.assertIn("上限", msg)
        self.assertEqual(len(data["consequence_ledger"]), MAX_PENDING)

    def test_duplicate_fingerprint_rejected(self):
        """同 text + due 重复登记拒绝(指纹去重)。"""
        data = copy.deepcopy(DEFAULT_STATE)
        ok1, _ = register_consequence(data, text="欠钱不还", due_turns=5)
        self.assertTrue(ok1)
        ok2, msg2 = register_consequence(data, text="欠钱不还", due_turns=5)
        self.assertFalse(ok2)
        self.assertIn("重复", msg2)
        self.assertEqual(len(data["consequence_ledger"]), 1)

    def test_same_text_different_due_not_duplicate(self):
        """同文本但 due 不同 → 不算重复。"""
        data = copy.deepcopy(DEFAULT_STATE)
        ok1, _ = register_consequence(data, text="欠钱不还", due_turns=5)
        ok2, _ = register_consequence(data, text="欠钱不还", due_turns=10)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertEqual(len(data["consequence_ledger"]), 2)


# ────────────────────────────────────────────────────────────
# scan_and_fire
# ────────────────────────────────────────────────────────────

class ScanAndFireTests(unittest.TestCase):
    def test_turns_not_due_yet(self):
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 12
        register_consequence(data, text="X", due_turns=5)
        data["turn"] = 16  # created_turn(12) + 5 = 17,还差 1 回合
        fired = scan_and_fire(data)
        self.assertEqual(fired, [])
        self.assertEqual(data["consequence_ledger"][0]["status"], "pending")

    def test_turns_due_fires(self):
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 12
        register_consequence(data, text="X", due_turns=5)
        data["turn"] = 17  # 12 + 5 = 17 → 到期
        fired = scan_and_fire(data)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["text"], "X")
        entry = data["consequence_ledger"][0]
        self.assertEqual(entry["status"], "fired")
        self.assertEqual(entry["fired_turn"], 17)

    def test_turns_due_overshoot_still_fires(self):
        """turn 超过阈值(不只是恰好相等)也应触发。"""
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 12
        register_consequence(data, text="X", due_turns=5)
        data["turn"] = 30
        fired = scan_and_fire(data)
        self.assertEqual(len(fired), 1)

    def test_location_hit_fires(self):
        data = copy.deepcopy(DEFAULT_STATE)
        register_consequence(data, text="送药到村", due_location="阿托菲村")
        data["player"]["current_location"] = "阿托菲村·集市"
        fired = scan_and_fire(data)
        self.assertEqual(len(fired), 1)

    def test_location_miss_does_not_fire(self):
        data = copy.deepcopy(DEFAULT_STATE)
        register_consequence(data, text="送药到村", due_location="阿托菲村")
        data["player"]["current_location"] = "北港"
        fired = scan_and_fire(data)
        self.assertEqual(fired, [])
        self.assertEqual(data["consequence_ledger"][0]["status"], "pending")

    def test_fired_is_idempotent(self):
        """已 fired 的条目不再被重复触发(第二次 scan 不再出现在返回列表里)。"""
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 1
        register_consequence(data, text="X", due_turns=1)
        data["turn"] = 2
        fired1 = scan_and_fire(data)
        self.assertEqual(len(fired1), 1)
        # 再次扫描,turn 不变或前进,已 fired 的不应再出现
        fired2 = scan_and_fire(data)
        self.assertEqual(fired2, [])
        data["turn"] = 5
        fired3 = scan_and_fire(data)
        self.assertEqual(fired3, [])
        self.assertEqual(data["consequence_ledger"][0]["fired_turn"], 2)  # 保持首次触发回合不变

    def test_empty_ledger_no_crash(self):
        data = copy.deepcopy(DEFAULT_STATE)
        self.assertEqual(scan_and_fire(data), [])


# ────────────────────────────────────────────────────────────
# entries_for_injection
# ────────────────────────────────────────────────────────────

class EntriesForInjectionTests(unittest.TestCase):
    def test_empty_when_nothing_fired(self):
        data = copy.deepcopy(DEFAULT_STATE)
        register_consequence(data, text="X", due_turns=5)
        self.assertEqual(entries_for_injection(data), [])

    def test_includes_just_fired(self):
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 1
        register_consequence(data, text="X", due_turns=1)
        data["turn"] = 2
        scan_and_fire(data)
        entries = entries_for_injection(data)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["text"], "X")

    def test_includes_recent_fired_within_window(self):
        """最近 3 回合内 fired 的仍在注入窗口内。"""
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 1
        register_consequence(data, text="X", due_turns=1)
        data["turn"] = 2
        scan_and_fire(data)  # fired_turn = 2
        data["turn"] = 5  # 5 - 2 = 3,仍在窗口内(<=3)
        entries = entries_for_injection(data)
        self.assertEqual(len(entries), 1)

    def test_excludes_fired_beyond_window(self):
        data = copy.deepcopy(DEFAULT_STATE)
        data["turn"] = 1
        register_consequence(data, text="X", due_turns=1)
        data["turn"] = 2
        scan_and_fire(data)  # fired_turn = 2
        data["turn"] = 6  # 6 - 2 = 4 > 3,超出窗口
        entries = entries_for_injection(data)
        self.assertEqual(entries, [])

    def test_no_crash_on_empty_ledger(self):
        data = copy.deepcopy(DEFAULT_STATE)
        self.assertEqual(entries_for_injection(data), [])


# ────────────────────────────────────────────────────────────
# apply_structured_updates 的 "consequence" JSON op 分支
# ────────────────────────────────────────────────────────────

class ApplyOpBranchTests(unittest.TestCase):
    def test_json_op_registers_consequence(self):
        s = _new_state(turn=10)
        gm_response = (
            "正文正文。\n"
            "```json\n"
            '{"op": "consequence", "text": "答应帮铁匠找矿石", "due_turns": 4}\n'
            "```\n"
        )
        updates = s.apply_structured_updates(gm_response)
        self.assertEqual(len(s.data["consequence_ledger"]), 1)
        self.assertEqual(s.data["consequence_ledger"][0]["text"], "答应帮铁匠找矿石")
        self.assertTrue(any("状态写入" in u for u in updates), updates)

    def test_json_op_location_variant(self):
        s = _new_state(turn=1)
        gm_response = (
            "```json\n"
            '{"op": "consequence", "text": "答应去北港汇合", "due_location": "北港"}\n'
            "```\n"
        )
        s.apply_structured_updates(gm_response)
        self.assertEqual(s.data["consequence_ledger"][0]["due"], {"location": "北港"})

    def test_json_op_missing_text_rejected_no_crash(self):
        s = _new_state(turn=1)
        gm_response = (
            "```json\n"
            '{"op": "consequence", "due_turns": 5}\n'
            "```\n"
        )
        updates = s.apply_structured_updates(gm_response)
        self.assertEqual(s.data.get("consequence_ledger", []), [])
        self.assertTrue(any("缺文本" in u or "忽略" in u for u in updates), updates)

    def test_json_op_missing_due_rejected_no_crash(self):
        s = _new_state(turn=1)
        gm_response = (
            "```json\n"
            '{"op": "consequence", "text": "没有期限"}\n'
            "```\n"
        )
        updates = s.apply_structured_updates(gm_response)
        self.assertEqual(s.data.get("consequence_ledger", []), [])
        self.assertTrue(updates)  # 有说明,不静默

    def test_json_op_duplicate_via_apply_rejected(self):
        s = _new_state(turn=1)
        gm_response = (
            "```json\n"
            '{"op": "consequence", "text": "重复承诺", "due_turns": 3}\n'
            "```\n"
        )
        s.apply_structured_updates(gm_response)
        s.apply_structured_updates(gm_response)
        self.assertEqual(len(s.data["consequence_ledger"]), 1)

    def test_question_op_still_works_alongside(self):
        """回归:新分支不破坏既有 question op 行为。"""
        s = _new_state(turn=1)
        gm_response = (
            "```json\n"
            '{"op": "question", "question": "去哪?", "options": ["东", "西"]}\n'
            "```\n"
        )
        updates = s.apply_structured_updates(gm_response)
        self.assertTrue(any("等待玩家回答" in u for u in updates), updates)


# ────────────────────────────────────────────────────────────
# dispatcher 工具 schedule_consequence
# ────────────────────────────────────────────────────────────

class ScheduleConsequenceToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools_dsl.command_tools_register import force_reset_for_tests
        force_reset_for_tests()

    def setUp(self):
        from tools_dsl.command_dispatcher import ToolDispatcher, get_registry
        self.state = _new_state(turn=8)
        self.dispatcher = ToolDispatcher(
            registry=get_registry(),
            state_provider=lambda env: self.state,
        )

    def _call(self, args, origin="ui_button", save_id=100):
        from tools_dsl.command_dispatcher import ToolCallEnvelope
        env = ToolCallEnvelope(
            user_id=1, save_id=save_id, tool="schedule_consequence",
            args=args, origin=origin, trace_id="t-consequence",
        )
        return self.dispatcher.dispatch_sync(env)

    def test_success_from_llm_chat(self):
        r = self._call(
            {"text": "答应带回证据", "due_turns": 5},
            origin="llm_chat",
        )
        self.assertTrue(r.ok, r.error or r.result)
        self.assertEqual(len(self.state.data["consequence_ledger"]), 1)

    def test_success_from_ui_button(self):
        r = self._call({"text": "答应带药", "due_location": "阿托菲村"}, origin="ui_button")
        self.assertTrue(r.ok, r.error or r.result)

    def test_missing_text_rejected_by_dispatcher(self):
        r = self._call({"due_turns": 5})
        self.assertFalse(r.ok)

    def test_missing_due_rejected_by_executor_no_crash(self):
        r = self._call({"text": "没有期限"})
        self.assertFalse(r.ok)
        self.assertIn("Failed", r.result or r.error or "")

    def test_blocked_from_mcp_call_origin(self):
        """origin 白名单:mcp_call 不在合法值里,应被 dispatcher 拦截。"""
        r = self._call({"text": "X", "due_turns": 1}, origin="mcp_call")
        self.assertFalse(r.ok)
        self.assertIn("origin_forbidden", r.error or "")

    def test_duplicate_rejected(self):
        r1 = self._call({"text": "重复工具调用", "due_turns": 2})
        r2 = self._call({"text": "重复工具调用", "due_turns": 2})
        self.assertTrue(r1.ok)
        self.assertFalse(r2.ok)


# ────────────────────────────────────────────────────────────
# context provider: consequence_echo
# ────────────────────────────────────────────────────────────

class ConsequenceEchoProviderTests(unittest.TestCase):
    def setUp(self):
        from context_providers import Demand, ProviderServices
        from context_providers.registry import get_provider
        self.provider = get_provider("consequence_echo")
        self.assertIsNotNone(self.provider, "consequence_echo provider 未注册")
        self.demand = Demand.empty()
        self.manifest = {"context_providers": ["consequence_echo"]}
        self.services_factory = ProviderServices

    def test_gate_off_skips(self):
        """flag 默认关 → skip,不读 state。"""
        os.environ.pop("RPG_CONSEQUENCE_LEDGER", None)  # 确保走默认(关)
        s = _new_state(turn=10)
        register_consequence(s.data, text="X", due_turns=1)
        contrib = self.provider.collect(
            s, self.manifest, self.demand, self.services_factory(user_id=None),
        )
        self.assertFalse(contrib.applied)

    def test_gate_on_no_fire_returns_empty(self):
        os.environ["RPG_CONSEQUENCE_LEDGER"] = "1"
        try:
            s = _new_state(turn=1)
            register_consequence(s.data, text="X", due_turns=100)  # 远未到期
            contrib = self.provider.collect(
                s, self.manifest, self.demand, self.services_factory(user_id=None),
            )
            self.assertFalse(contrib.applied)
        finally:
            os.environ.pop("RPG_CONSEQUENCE_LEDGER", None)

    def test_gate_on_fire_returns_template_text(self):
        os.environ["RPG_CONSEQUENCE_LEDGER"] = "1"
        try:
            s = _new_state(turn=12)
            register_consequence(s.data, text="答应雷纳德查清林中兽伤", due_turns=5)
            s.data["turn"] = 17  # 到期
            contrib = self.provider.collect(
                s, self.manifest, self.demand, self.services_factory(user_id=None),
            )
            self.assertTrue(contrib.applied)
            self.assertEqual(len(contrib.layers), 1)
            content = contrib.layers[0]["content"]
            self.assertIn("Consequence echoes", content)
            self.assertIn("答应雷纳德查清林中兽伤", content)
            self.assertIn("planted on turn 12", content)
            self.assertEqual(s.data["consequence_ledger"][0]["status"], "fired")
        finally:
            os.environ.pop("RPG_CONSEQUENCE_LEDGER", None)

    def test_collect_does_the_scanning_itself(self):
        """provider.collect 一处完成扫描+触发+注入,调用方不需要另外调 scan_and_fire。"""
        os.environ["RPG_CONSEQUENCE_LEDGER"] = "1"
        try:
            s = _new_state(turn=1)
            register_consequence(s.data, text="X", due_turns=1)
            s.data["turn"] = 2
            self.assertEqual(s.data["consequence_ledger"][0]["status"], "pending")
            contrib = self.provider.collect(
                s, self.manifest, self.demand, self.services_factory(user_id=None),
            )
            self.assertTrue(contrib.applied)
            self.assertEqual(s.data["consequence_ledger"][0]["status"], "fired")
        finally:
            os.environ.pop("RPG_CONSEQUENCE_LEDGER", None)


if __name__ == "__main__":
    unittest.main()
