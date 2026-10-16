"""战斗 >50 回合僵局兜底必须有清晰结局,不能软锁。

bug:next_turn 在 round>50 时置 active=False 但**不设 outcome**,且 advance_turn 不收尾
→ encounter 静默失活、无 outcome/无结算事实/无 flag;玩家再攻击得"没有进行中的战斗",
依赖战斗结局的剧情门控卡死。修:next_turn 置 outcome='stalemate';advance_turn 在
next_turn 兜底结束后调用 _finalize_encounter 收尾并返回 resolved/message。
"""
import unittest

from rules.dnd5e import combat as engine_combat


def _live_encounter():
    # 双方都活着、谁也打不死谁的对峙(用于触发 >50 回合兜底)
    return {
        "active": True,
        "round": 50,            # 下一次 next_turn 跨回合会到 51 → 触发兜底
        "turn_index": 1,        # 指向 order 末尾,next_turn 会跨回合
        "initiative_order": [{"id": "hero"}, {"id": "orc"}],
        "combatants": [
            {"id": "hero", "side": "party", "hp": 10, "defeated": False},
            {"id": "orc", "side": "enemy", "hp": 10, "defeated": False},
        ],
    }


class CombatStalemateTimeout(unittest.TestCase):
    def test_next_turn_sets_stalemate_outcome(self):
        enc = _live_encounter()
        engine_combat.next_turn(enc)
        self.assertFalse(enc["active"], "超过50回合应强制结束")
        self.assertEqual(enc.get("outcome"), "stalemate",
                         "强制结束必须置 outcome,否则结局丢失→软锁")

    def test_advance_turn_finalizes_and_reports(self):
        # 用最小 fake state 走 rules_bridge.advance_turn 收尾路径
        from rules_bridge import combat as bridge

        class _FakeState:
            def __init__(self, enc):
                self.data = {"encounter": enc, "player_character": {}}
                self.flags = {}

            def set_scene_flag(self, k, v):
                self.flags[k] = v

        enc = _live_encounter()
        st = _FakeState(enc)
        # _sync_player_combatant 只读 player_character,空 dict 安全
        res = bridge.advance_turn(st)
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("resolved"), "兜底结束应回报 resolved")
        self.assertEqual(res.get("outcome"), "stalemate")
        self.assertIn("stalemate", res.get("message", ""))
        self.assertFalse(enc["active"])
        # 僵局不写 victory_flag
        self.assertEqual(st.flags, {})


if __name__ == "__main__":
    unittest.main()
