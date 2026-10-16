"""test_write_preview — 写作搭档 agent 落库前的 before→after 改动预览。

章节正文写:必须给真·当前全文(before)+ 提议全文(after),供前端 diff/对照;新建章节 is_new=True。
结构化写(世界书/人物/锚点/canon):给「将写入的字段」(after)。失败/不支持 → None,绝不阻断确认。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.environ.setdefault("RPG_REQUIRE_AUTH", "1")

from tests.helpers import cleanup_test_users, make_client, register_user  # noqa: E402


class WritePreviewE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cleanup_test_users()
        cls.client = make_client()

    @classmethod
    def tearDownClass(cls):
        cleanup_test_users()

    def _mk_script_with_chapter(self, uid: int):
        from platform_app.db import connect
        with connect() as db:
            sid = int(db.execute(
                "insert into scripts(owner_id, title) values (%s,%s) returning id",
                (uid, "integtest_preview"),
            ).fetchone()["id"])
            db.execute(
                "insert into script_chapters(script_id, chapter_index, title, content) values (%s,%s,%s,%s)",
                (sid, 1, "开篇", "原始正文：他站在站台上，等一班永不到站的列车。"),
            )
        return sid

    def _uid(self):
        u = register_user(self.client)
        me = self.client.get("/api/v1/auth/me", cookies=u["cookies"])
        return int(me.json()["user"]["id"])

    def test_chapter_preview_before_after(self):
        from console_assistant.write_preview import build_write_preview
        uid = self._uid()
        sid = self._mk_script_with_chapter(uid)
        pv = build_write_preview(
            "update_script_chapter",
            {"chapter_index": 1, "content": "改写正文：列车终于来了，门开的瞬间他犹豫了。"},
            uid, sid,
        )
        self.assertIsNotNone(pv)
        self.assertEqual(pv["kind"], "chapter")
        self.assertFalse(pv["is_new"])
        self.assertIn("原始正文", pv["before"])
        self.assertIn("改写正文", pv["after"])
        self.assertIn("Chapter 1", pv["label"])

    def test_chapter_preview_new_chapter(self):
        from console_assistant.write_preview import build_write_preview
        uid = self._uid()
        sid = self._mk_script_with_chapter(uid)
        pv = build_write_preview(
            "update_script_chapter",
            {"chapter_index": 99, "title": "新章", "content": "全新内容"},
            uid, sid,
        )
        self.assertIsNotNone(pv)
        self.assertTrue(pv["is_new"])
        self.assertEqual(pv["before"], "")
        self.assertIn("新章", pv["label"])

    def test_structured_preview_shows_fields(self):
        from console_assistant.write_preview import build_write_preview
        pv = build_write_preview(
            "upsert_worldbook_entry",
            {"title": "重力控制", "content": "郑吒的本命能力", "priority": 5},
            1, 123,
        )
        self.assertIsNotNone(pv)
        self.assertEqual(pv["kind"], "worldbook")
        self.assertEqual(pv["label"], "重力控制")
        self.assertIn("郑吒的本命能力", pv["after"])
        self.assertNotIn("before", pv)  # 结构化写不读当前值,只给 after

    def test_unsupported_tool_returns_none(self):
        from console_assistant.write_preview import build_write_preview
        self.assertIsNone(build_write_preview("delete_save", {"save_id": 1}, 1, None))

    def test_title_only_chapter_change_returns_none(self):
        """只改标题(无 content)不做正文 diff → None,退回原始 args 展示。"""
        from console_assistant.write_preview import build_write_preview
        self.assertIsNone(build_write_preview(
            "update_script_chapter", {"chapter_index": 1, "title": "新标题"}, 1, 123,
        ))


if __name__ == "__main__":
    unittest.main()
