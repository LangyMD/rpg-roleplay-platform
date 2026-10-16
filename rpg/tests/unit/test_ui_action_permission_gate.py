"""修2:ui_set_field 后端按 permission_mode 把关。

病灶(台账):command_tools_ui_action.py 旧注释称「前端会在 read_only 检查」,而
frontend/src/ui-atlas.js 的 setField 实际零检查 —— read_only 下 console/LLM 可
静默代填任意表单。安全边界两头不管。

修:后端权威闸(确定性缝优先后端,不指望前端)。read_only / default 拒绝(走 dispatcher
「失败: ...」惯例串,_RESULT_FAILURE_RE 可识别);full_access 正常返回 __ui_action__ payload。
permission mode 经 _current_permission_mode 读(参照 apply_ops:state.permissions.mode);
本测试 monkeypatch 该函数控制模式,不依赖 DB / 真存档。
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

import tools_dsl.command_tools_ui_action as ui_action  # noqa: E402

_ARGS = {"form_id": "newgame", "field_key": "存档名称", "value": "雾港调查"}


class UiSetFieldPermissionGate(unittest.TestCase):
    def setUp(self):
        self._orig = ui_action._current_permission_mode

    def tearDown(self):
        ui_action._current_permission_mode = self._orig

    def _set_mode(self, mode: str):
        ui_action._current_permission_mode = lambda _uid, _m=mode: _m

    def test_read_only_rejected(self):
        self._set_mode("read_only")
        res = ui_action._t_ui_set_field(1, dict(_ARGS))
        self.assertIsInstance(res, str, "read_only 应返回失败串而非 UI action dict")
        self.assertTrue(res.startswith("Failed"), res)
        self.assertIn("read_only", res)

    def test_default_rejected(self):
        self._set_mode("default")
        res = ui_action._t_ui_set_field(1, dict(_ARGS))
        self.assertIsInstance(res, str)
        self.assertTrue(res.startswith("Failed"), res)

    def test_full_access_allowed(self):
        self._set_mode("full_access")
        res = ui_action._t_ui_set_field(1, dict(_ARGS))
        self.assertIsInstance(res, dict, "full_access 应返回 UI action payload")
        self.assertEqual(res.get("__ui_action__"), "set_field")
        self.assertEqual(res.get("field_key"), "存档名称")

    def test_auto_review_allowed(self):
        """auto_review(自动应用+审计)归直写侧,允许代填(与台账口径读_only/default 拒一致)。"""
        self._set_mode("auto_review")
        res = ui_action._t_ui_set_field(1, dict(_ARGS))
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("__ui_action__"), "set_field")

    def test_input_validation_still_first(self):
        """缺字段的既有校验不被闸门破坏(即便 full_access)。"""
        self._set_mode("full_access")
        self.assertTrue(
            ui_action._t_ui_set_field(1, {"field_key": "x", "value": "y"}).startswith("Failed"),
            "缺 form_id 应仍先报失败",
        )

    def test_helper_fail_open_returns_full_access_on_load_error(self):
        """fail-open(hermetic):底层读状态抛异常时 _current_permission_mode 返回
        full_access(不阻断非游戏页 / 无存档时的正常代填)。patch app._ensure_loaded
        抛错,不触 DB。"""
        import app
        orig = app._ensure_loaded

        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        app._ensure_loaded = _boom
        try:
            self.assertEqual(ui_action._current_permission_mode(1), "full_access")
        finally:
            app._ensure_loaded = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
