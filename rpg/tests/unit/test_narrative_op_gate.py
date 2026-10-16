"""修1:GM 自主叙事记忆写入(consequence/npc_agenda/hypothesis 系 JSON op)必须走
权限闸门,不再直调专用方法绕闸。

病灶(台账 2026-07-07):apply_structured_updates 的 JSON op 循环里,
consequence / agenda / hypothesis / confirm_hypothesis / reject_hypothesis 五类 op
直调 register_consequence / upsert_npc_agenda / add_hypothesis / confirm_hypothesis /
reject_hypothesis,完全绕过 apply_state_write_typed 的权限闸门 —— read_only 也拦不住,
破坏「任何 LLM 自动写入都入 pending」承诺。

核实(2026-07-17):这些数据【确实进 GM 上下文注入】——
  · consequence → context_providers/consequence_echo.py(后果回响,layer+facts)
  · npc_agenda  → context_providers/npc_agenda.py(NPC 议程,layer+facts)
  · hypothesis  → context_providers/memory.py(以「未确认推测」注入)
  · confirm_hypothesis → 升级出注入的 runtime_fact
故有真实叙事影响,豁免不成立,判为真缺陷 → 并入闸门。

口径:read_only / default 入 pending,full_access 直写(与 test_user_variable_gate 同风)。
默认存档 mode=full_access,故常规游戏不受影响;仅玩家显式切 read_only/default 才生效。
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


def _fence(op_json: str, prose: str = "剧情推进。") -> str:
    return f"{prose}\n```json\n{op_json}\n```\n"


def _pending(g) -> list:
    return (g.data.get("permissions", {}) or {}).get("pending_writes", []) or []


class ConsequenceOpGate(unittest.TestCase):
    def test_read_only_consequence_goes_to_pending_not_ledger(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        updates = g.apply_structured_updates(
            _fence('{"op":"consequence","text":"答应帮铁匠找矿石","due_turns":4}')
        )
        # 未直写后果账本
        self.assertEqual(g.data.get("consequence_ledger", []), [],
                         "read_only 下后果不得绕闸直写账本")
        # 入 pending(合成 path=consequence)
        pw = _pending(g)
        self.assertTrue(any(p.get("path") == "consequence" for p in pw),
                        f"后果应入 pending;实际={pw}")
        self.assertTrue(any("pending approval" in u for u in updates), updates)

    def test_approve_consequence_pending_lands_in_ledger(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        g.apply_structured_updates(
            _fence('{"op":"consequence","text":"答应雷纳德带证据回村","due_turns":5}')
        )
        pid = _pending(g)[0]["id"]
        res = g.approve_pending_write(id=pid)
        self.assertIn("State write", res, res)
        ledger = g.data.get("consequence_ledger", [])
        self.assertEqual(len(ledger), 1, "审批后应落地后果账本")
        self.assertEqual(ledger[0]["text"], "答应雷纳德带证据回村")
        self.assertEqual(_pending(g), [], "审批后 pending 应清空")

    def test_default_mode_consequence_also_pends(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "default"
        g.apply_structured_updates(
            _fence('{"op":"consequence","text":"约定明早集合","due_turns":2}')
        )
        self.assertEqual(g.data.get("consequence_ledger", []), [],
                         "default 下后果也须入 pending(台账口径)")
        self.assertTrue(any(p.get("path") == "consequence" for p in _pending(g)))

    def test_full_access_consequence_writes_directly(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "full_access"
        g.apply_structured_updates(
            _fence('{"op":"consequence","text":"欠债三日内还","due_turns":3}')
        )
        self.assertEqual(len(g.data.get("consequence_ledger", [])), 1,
                         "full_access 应直写")
        self.assertEqual(_pending(g), [], "full_access 不应产生 pending")


class NpcAgendaOpGate(unittest.TestCase):
    def test_read_only_agenda_goes_to_pending_not_state(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        # 名字在正文出现 → 登记时刻捕获 extra_known,审批时不受回合漂移影响
        g.apply_structured_updates(_fence(
            '{"op":"agenda","name":"雷纳德","goal":"查清兽伤","stance":"信任但观察"}',
            prose="雷纳德皱眉。",
        ))
        self.assertNotIn("雷纳德", g.data.get("npc_agendas", {}),
                         "read_only 下议程不得绕闸直写")
        pw = _pending(g)
        self.assertTrue(any(p.get("path") == "npc_agenda" for p in pw), pw)

    def test_approve_agenda_pending_lands_in_state(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        g.apply_structured_updates(_fence(
            '{"op":"agenda","name":"雷纳德","goal":"查清兽伤","stance":"信任但观察"}',
            prose="雷纳德皱眉。",
        ))
        pid = _pending(g)[0]["id"]
        g.approve_pending_write(id=pid)
        agendas = g.data.get("npc_agendas", {})
        self.assertIn("雷纳德", agendas, "审批后议程应落地")
        self.assertEqual(agendas["雷纳德"]["goal"], "查清兽伤")

    def test_full_access_agenda_writes_directly(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "full_access"
        g.apply_structured_updates(_fence(
            '{"op":"agenda","name":"艾琳","goal":"渡河","stance":"警惕"}',
            prose="艾琳站在桥头。",
        ))
        self.assertIn("艾琳", g.data.get("npc_agendas", {}))
        self.assertEqual(_pending(g), [])


class HypothesisOpGate(unittest.TestCase):
    def test_read_only_hypothesis_goes_to_pending(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        g.apply_structured_updates(
            _fence('{"op":"hypothesis","text":"凶手可能是管家"}')
        )
        self.assertEqual(g.list_active_hypotheses(), [],
                         "read_only 下推测不得绕闸直写")
        self.assertTrue(any(p.get("path") == "hypothesis" for p in _pending(g)))

    def test_approve_hypothesis_pending_lands_active(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        g.apply_structured_updates(
            _fence('{"op":"hypothesis","text":"凶手可能是管家"}')
        )
        pid = _pending(g)[0]["id"]
        g.approve_pending_write(id=pid)
        active = g.list_active_hypotheses()
        self.assertEqual(len(active), 1, "审批后推测应转 active")
        self.assertEqual(active[0]["text"], "凶手可能是管家")

    def test_full_access_hypothesis_writes_directly(self):
        g = GameState.new()
        g.data["permissions"]["mode"] = "full_access"
        g.apply_structured_updates(
            _fence('{"op":"hypothesis","text":"密道通向地窖"}')
        )
        self.assertEqual(len(g.list_active_hypotheses()), 1)
        self.assertEqual(_pending(g), [])


class ConfirmRejectHypothesisOpGate(unittest.TestCase):
    def _seed_active_hypothesis(self, g) -> str:
        """full_access 直接种一条 active 推测,返回 id。"""
        hid = g.add_hypothesis("待验证推测", source="gm:json")
        return hid

    def test_read_only_confirm_hypothesis_pends_not_promotes(self):
        g = GameState.new()
        hid = self._seed_active_hypothesis(g)  # full_access 下种
        g.data["permissions"]["mode"] = "read_only"
        g.apply_structured_updates(
            _fence(f'{{"op":"confirm_hypothesis","id":"{hid}"}}')
        )
        # 未升级:推测仍 active(未被 confirm 成 runtime_fact)
        self.assertTrue(any(h["id"] == hid for h in g.list_active_hypotheses()),
                        "read_only 下 confirm 不得直接升级")
        self.assertTrue(any(p.get("path") == "confirm_hypothesis" for p in _pending(g)))
        # 审批后升级:原推测不再 active
        pid = next(p["id"] for p in _pending(g) if p.get("path") == "confirm_hypothesis")
        g.approve_pending_write(id=pid)
        self.assertFalse(any(h["id"] == hid for h in g.list_active_hypotheses()),
                         "审批后原推测应被 superseded")

    def test_read_only_reject_hypothesis_pends(self):
        g = GameState.new()
        hid = self._seed_active_hypothesis(g)
        g.data["permissions"]["mode"] = "read_only"
        g.apply_structured_updates(
            _fence(f'{{"op":"reject_hypothesis","id":"{hid}"}}')
        )
        self.assertTrue(any(h["id"] == hid for h in g.list_active_hypotheses()),
                        "read_only 下 reject 不得直接删活跃推测")
        self.assertTrue(any(p.get("path") == "reject_hypothesis" for p in _pending(g)))

    def test_read_only_confirm_missing_id_still_fails_no_pending(self):
        """缺 id 的 confirm 在 read_only 下仍走原失败分支(不入 pending),保既有报错行为。"""
        g = GameState.new()
        g.data["permissions"]["mode"] = "read_only"
        updates = g.apply_structured_updates(
            _fence('{"op":"confirm_hypothesis"}')
        )
        self.assertEqual(_pending(g), [], "缺 id 不应入 pending")
        self.assertTrue(any("Failed" in u for u in updates), updates)

    def test_full_access_confirm_hypothesis_promotes_directly(self):
        g = GameState.new()  # full_access
        hid = self._seed_active_hypothesis(g)
        g.apply_structured_updates(
            _fence(f'{{"op":"confirm_hypothesis","id":"{hid}"}}')
        )
        self.assertFalse(any(h["id"] == hid for h in g.list_active_hypotheses()),
                         "full_access 应直接升级")
        self.assertEqual(_pending(g), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
