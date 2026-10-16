"""known_events 卫生:materialize 数字序 + acceptance 元信息三写入口过滤。

背景(群反馈,save 268 turn 798 实锤):
  · materialize 按 logical_key 字典序还原 → kevt:10+ 排在 kevt:2 前 → GM 注入窗口
    ([-15:])与面板长期被最老条目占据,新事件不可见;import 往返按乱序重编号 →
    每回合槽位洗牌 COW 写放大(18359 行 kevt 历史)。
  · acceptance 验收元信息「acceptance '…' 跳过: …」混进 known_events,过滤闸原来
    只覆盖 memory.facts。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from kb.save_kb import _logical_key_order  # noqa: E402
from state.core import GameState  # noqa: E402
from state.json_ops import is_acceptance_meta  # noqa: E402

_ACC = "acceptance 'GM确认玩家当前处于特定场景中' 跳过: set 240 6"


class LogicalKeyOrder(unittest.TestCase):
    def test_numeric_not_lexicographic(self):
        keys = [f"kevt:{i}" for i in range(16)]
        scrambled = sorted(keys)  # 字典序:kevt:0,1,10..15,2..9(旧 bug 的顺序)
        self.assertNotEqual(scrambled, keys)  # 前提:字典序确实乱
        self.assertEqual(sorted(keys, key=_logical_key_order), keys)

    def test_fact_and_kevt_grouped_then_numeric(self):
        keys = ["kevt:2", "fact:10", "kevt:10", "fact:2"]
        self.assertEqual(sorted(keys, key=_logical_key_order),
                         ["fact:2", "fact:10", "kevt:2", "kevt:10"])

    def test_non_numeric_index_sorts_last_stably(self):
        keys = ["kevt:abc", "kevt:1", "kevt:0"]
        self.assertEqual(sorted(keys, key=_logical_key_order),
                         ["kevt:0", "kevt:1", "kevt:abc"])


class AcceptanceMetaPredicate(unittest.TestCase):
    def test_hits(self):
        self.assertTrue(is_acceptance_meta(_ACC))
        self.assertTrue(is_acceptance_meta("  acceptance 'x' skipped"))

    def test_narrow_no_false_positive(self):
        # 正常叙事事件/含 acceptance 字样但非元信息形态的,不误杀(宁漏勿误)
        self.assertFalse(is_acceptance_meta("成功击杀暴君量产型"))
        self.assertFalse(is_acceptance_meta("玩家接受了 acceptance 任务"))
        self.assertFalse(is_acceptance_meta("acceptance 测试通过,团队庆祝"))
        self.assertFalse(is_acceptance_meta(None))


class KnownEventsWriteGates(unittest.TestCase):
    """两个写入口都拒 acceptance 元信息;正常事件照常进。"""

    def test_json_op_append_filtered(self):
        st = GameState.new()
        st.apply_structured_updates(
            '```json\n[{"op":"append","path":"world.known_events","value":'
            f'["{_ACC}","主神光柱降下"]' '}]\n```'
        )
        events = st.data["world"]["known_events"]
        self.assertIn("主神光柱降下", events)
        self.assertNotIn(_ACC, events)

    def test_tool_executor_rejects(self):
        from tools_dsl.command_tools import execute_tool
        st = GameState.new()
        r = execute_tool(st, "set_world_known_event", {"event": _ACC})
        self.assertIn("ignored", r)
        self.assertEqual(st.data["world"]["known_events"], [])
        r2 = execute_tool(st, "set_world_known_event", {"event": "主神光柱降下"})
        self.assertIn("Known events", r2)
        self.assertEqual(st.data["world"]["known_events"], ["主神光柱降下"])


class AcceptanceRootGates(unittest.TestCase):
    """单点根闸:add_memory(五桶+工具通道)/update_relationship/set_user_variable。"""

    def test_add_memory_rejects_all_buckets(self):
        st = GameState.new()
        for bucket in ("facts", "notes", "pinned", "resources", "abilities"):
            self.assertFalse(st.add_memory(bucket, _ACC))
            self.assertEqual(st.data["memory"][bucket], [])
        self.assertTrue(st.add_memory("notes", "正常笔记"))

    def test_dispatcher_memory_tool_blocked(self):
        from tools_dsl.command_tools import execute_tool
        st = GameState.new()
        execute_tool(st, "add_memory_note", {"text": _ACC})
        self.assertEqual(st.data["memory"]["notes"], [])

    def test_relationship_and_user_variable(self):
        st = GameState.new()
        st.update_relationship("雷纳德", _ACC)
        self.assertNotIn("雷纳德", st.data["relationships"])
        st.update_relationship("雷纳德", "信任")
        self.assertEqual(st.data["relationships"]["雷纳德"], "信任")
        self.assertFalse(st.set_user_variable("x", _ACC, source="gm"))
        self.assertNotIn("x", st.data["worldline"].get("user_variables", {}))


class MemoryWindowDirection(unittest.TestCase):
    """注入窗口取尾(最近 N 条):桶超窗后新增条目必须可见、最老条目退出窗口。"""

    def test_short_summary_shows_newest_resources(self):
        st = GameState.new()
        for i in range(9):
            st.add_memory("resources", f"资源物品{i:02d}")
        summary = st.short_summary()
        self.assertIn("资源物品08", summary)   # 最新的必须在
        self.assertNotIn("资源物品00", summary)  # 窗口 6,最老的退出

    def test_short_summary_shows_newest_pinned(self):
        st = GameState.new()
        for i in range(8):
            st.add_memory("pinned", f"固定规则{i:02d}")
        summary = st.short_summary()
        self.assertIn("固定规则07", summary)
        self.assertNotIn("固定规则00", summary)


if __name__ == "__main__":
    unittest.main()
