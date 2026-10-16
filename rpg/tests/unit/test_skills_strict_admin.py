"""skills 导入 / 运行必须走 get_current_admin_strict。

普通 get_current_admin 在 local 模式会短路放行(连 user=None 都放),而 /api/skills/{id}/run
接受 cmd=["python3", "-c", ...] —— 等于本地端口上的未鉴权代码执行。MCP 路由早已改用 strict,
skills 漏了;这里锁住两条 skills 路由的依赖。
"""
from __future__ import annotations

import unittest

from fastapi.routing import APIRoute


def _dep_calls(dependant, out):
    for d in dependant.dependencies:
        out.add(d.call)
        _dep_calls(d, out)
    return out


class TestSkillsRoutesUseStrictAdmin(unittest.TestCase):
    def test_import_and_run_depend_on_strict_admin(self):
        from routes import skills
        from routes._deps_fastapi import get_current_admin, get_current_admin_strict

        routes = {r.path: r for r in skills.router.routes if isinstance(r, APIRoute)}
        for path in ("/api/skills/import", "/api/skills/{skill_id}/run"):
            with self.subTest(path=path):
                self.assertIn(path, routes)
                calls = _dep_calls(routes[path].dependant, set())
                self.assertIn(get_current_admin_strict, calls)
                self.assertNotIn(get_current_admin, calls)


if __name__ == "__main__":
    unittest.main()
