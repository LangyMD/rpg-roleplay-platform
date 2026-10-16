"""RATH v3/v4 离线简报桥:玩家回归回合注入离线世界纪要(确定性聚合,零 LLM)。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BR = (ROOT / "rath" / "briefing.py").read_text(encoding="utf-8")
RET = (ROOT / "retrieval" / "assemble.py").read_text(encoding="utf-8")  # 拆包后 retrieve_context 住 retrieval/assemble.py

sys.path.insert(0, str(ROOT))
from rath.briefing import build_offline_briefing  # noqa: E402


def test_briefing_deterministic_and_bounded():
    assert "rath\\_%%" in BR, "只聚合 RATH 产物"
    assert "MAX_BRIEF_CHARS = 700" in BR, "纪要有界"
    assert "MIN_GAP_MINUTES = 120" in BR, "连续对话不打扰(间隔<2h 不注入)"
    assert "role = 'user'" in BR, "窗口起点含玩家消息"
    assert "branch_commits" in BR and "greatest" in BR, (
        "kb_native 档不写 flat messages,玩家活动须以 branch_commits 为主源(353 prod 实锤)")
    assert "retired_at_commit is null" in BR, "尊重 tombstone"
    assert "order by id desc" in BR and "reversed" in BR, (
        "离线很久时最近的事优先入选(取最新60条反转,预算从最新日组往前装)")
    assert "截断保底" in BR, "最新日组独自超预算不返回 None"
    # v4 起收尾指导句被提到模块级 TAIL_TEXT 常量(供预算计入复用),不再是函数体内字面量。
    assert "do not recount them all in one go" in BR, "GM 指令:自然提及不照本宣科"
    body = BR[BR.find("def build_offline_briefing"):]
    assert "TAIL_TEXT" in body, "收尾句须通过 TAIL_TEXT 拼进最终输出"
    assert "call_agent" not in BR and "llm" not in BR.lower().replace("零 llm", ""), "零 LLM 确定性拼装"


def test_briefing_wired_into_retrieval_gated():
    i = RET.find("离线世界纪要")
    assert i != -1, "必须接进材料装配"
    seg = RET[i:i + 1200]
    assert "rath_experiments" in seg and "'running','paused'" in seg.replace(" ", ""), "只对绑定活跃实验的档注入"
    assert "非致命" in seg, "失败不阻断回合"


# ── P1(A8):离线简报水位游标(last_briefed_at)────────────────────────
# finding「since 随每次玩家活动前移,频繁短间隔玩家永远拿不到离线纪要」的回归测试。
# 用 mock db(不连库)验证行为:since 优先取游标而非玩家活动时间;120min 的打扰判定仍然
# 只看真实玩家活动;成功产出后必须回写游标。

def test_briefing_source_wires_last_briefed_at_cursor():
    assert "last_briefed_at" in BR
    body = BR[BR.find("def build_offline_briefing"):]
    assert "update rath_experiments set last_briefed_at" in body, "产出后必须回写游标"
    assert "TAIL_TEXT" in body and "used = len(header) + len(TAIL_TEXT)" in BR, (
        "尾部指令句必须计入 700 字预算(否则实际输出可超预算约一成)")


class _Result:
    def __init__(self, one=None, many=None):
        self._one = one
        self._many = many or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _MockDB:
    """按 SQL 关键字分派的假连接,记录每次调用供断言。"""

    def __init__(self, *, last_briefed_at, player_activity, gap_minutes, kb_rows):
        self.last_briefed_at = last_briefed_at
        self.player_activity = player_activity
        self.gap_minutes = gap_minutes
        self.kb_rows = kb_rows
        self.calls: list[tuple[str, object]] = []
        self.committed = False
        self.since_param = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        s = sql.lower()
        if "last_briefed_at" in s and "select" in s and "rath_experiments" in s:
            return _Result(one={"id": 42, "last_briefed_at": self.last_briefed_at})
        if "greatest(" in s and "messages" in s:
            return _Result(one={"ts": self.player_activity})
        if "extract(epoch from (now() - %s))/60" in sql:
            return _Result(one={"m": self.gap_minutes})
        if "kb_events" in s:
            self.since_param = params[1] if params else None
            return _Result(many=self.kb_rows)
        if s.strip().startswith("update rath_experiments set last_briefed_at"):
            return _Result()
        raise AssertionError(f"未预期的 SQL(mock 未覆盖): {sql!r}")

    def commit(self):
        self.committed = True


def test_since_prefers_last_briefed_cursor_over_player_activity():
    """短间隔玩家的核心修复:窗口起点必须是游标,不是每回合都前移的玩家活动时间。"""
    cursor = "2026-01-01T10:00:00+00:00"
    activity = "2026-01-05T09:00:00+00:00"  # 明显更晚;若被误用,游标窗口内的事件会被跳过
    db = _MockDB(
        last_briefed_at=cursor, player_activity=activity, gap_minutes=200,
        kb_rows=[{"logical_key": "rath_hb_1", "story_time": "第2日", "summary": "某事发生"}],
    )
    out = build_offline_briefing(db, 99)
    assert out is not None
    assert db.since_param == cursor, "窗口起点必须优先取游标(否则短间隔玩家永久错过纪要窗口)"


def test_since_falls_back_to_player_activity_when_no_cursor_yet():
    """首次简报(从未成功产出过)没有游标,退回旧行为:窗口起点=玩家最近活动。"""
    activity = "2026-01-01T00:00:00+00:00"
    db = _MockDB(
        last_briefed_at=None, player_activity=activity, gap_minutes=200,
        kb_rows=[{"logical_key": "rath_scene_1", "story_time": "第1日", "summary": "一场相遇"}],
    )
    out = build_offline_briefing(db, 99)
    assert out is not None
    assert db.since_param == activity


def test_gap_check_still_uses_real_player_activity_not_cursor():
    """"连续对话不打扰"判定不能被游标绕过——距真实玩家活动 <120min 就该 None,
    哪怕游标很旧(否则每回合都会把陈年游标事件灌进来,变成另一种打扰)。"""
    db = _MockDB(
        last_briefed_at="2000-01-01T00:00:00+00:00",
        player_activity="2026-01-01T00:00:00+00:00", gap_minutes=10, kb_rows=[],
    )
    out = build_offline_briefing(db, 99)
    assert out is None
    assert not any(sql.lower().startswith("select logical_key") for sql, _ in db.calls)


def test_successful_briefing_advances_cursor():
    db = _MockDB(
        last_briefed_at=None, player_activity="2026-01-01T00:00:00+00:00", gap_minutes=200,
        kb_rows=[{"logical_key": "rath_scene_1", "story_time": "第1日", "summary": "一场相遇"}],
    )
    out = build_offline_briefing(db, 99)
    assert out is not None
    assert db.committed, "产出纪要后必须提交游标回写(否则短间隔玩家问题复发)"
    assert any(
        sql.strip().lower().startswith("update rath_experiments set last_briefed_at")
        for sql, _ in db.calls
    )


def test_no_experiment_row_skips_cursor_write_but_still_returns_briefing():
    """save 没有 running/paused 实验(理论上调用方已挡过,防御式兜底):没有 exp_id 就不该
    尝试回写游标,但已经拼好的纪要仍然正常返回(读路径与写路径互不阻塞)。"""
    db = _MockDB(
        last_briefed_at=None, player_activity="2026-01-01T00:00:00+00:00", gap_minutes=200,
        kb_rows=[{"logical_key": "rath_scene_1", "story_time": "第1日", "summary": "一场相遇"}],
    )
    db.execute_orig = db.execute

    def _no_exp(sql, params=None):
        s = sql.lower()
        if "last_briefed_at" in s and "select" in s and "rath_experiments" in s:
            return _Result(one=None)
        return db.execute_orig(sql, params)

    db.execute = _no_exp
    out = build_offline_briefing(db, 99)
    assert out is not None
    assert not db.committed, "没有 exp_id 时不应尝试写游标"
