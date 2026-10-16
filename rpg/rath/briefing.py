"""rath/briefing.py — 离线世界简报(RATH→游戏的确定性桥,v3)。

「以假乱真」的最后一环:玩家离开期间世界在转(RATH tick 落 kb_events),但玩家回到
游戏时感知不到——召回是被动的。本模块在玩家【回归回合】把离线期间的世界纪要
确定性聚合(零 LLM),作为材料注入 GM:NPC 可以自然提及这些事,世界显得真的活过。

铁律:只读 kb_events(rath_% 产物),游戏 state 只读不写;纪要≤700字;确定性拼装。
(唯一的写:rath_experiments.last_briefed_at——RATH 自身实验表的簿记游标,与
last_viewed_at 同族,不是游戏 state。)

P1 修复(finding「离线简报 since 随每次玩家活动前移」):since 若直接取"玩家最近
活动"、每回合都会前移,玩家平均间隔<2h 时该判定永久为真→纪要功能对活跃玩法永久
失效。引入独立游标 last_briefed_at,窗口起点优先取它;120min 的"连续对话不打扰"
判定仍然只看真实玩家活动间隔,两者解耦。
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAX_BRIEF_CHARS = 700
MIN_GAP_MINUTES = 120  # 上次玩家回合距今 < 2h 不注入(连续对话不打扰)
TAIL_TEXT = (
    "(The above are facts that have already happened. Let NPCs mention or discuss them at natural moments - greetings, small talk, reports; "
    "do not recount them all in one go, and never say anything immersion-breaking like \"while you were away\".)"
)


def build_offline_briefing(db, save_id: int) -> str | None:
    """玩家回归回合的离线世界纪要。无新产物/间隔太短 → None。

    窗口起点=游标 last_briefed_at(有则优先)或上次玩家消息时间;事件按 story_time
    (世界日)分组,场景(scene)优先、心跳(hb)限量;输出确定性文本段供 GM 材料装配。
    成功产出后回写游标,下次窗口从这里续,不会因为玩家高频互动永久跳过。"""
    # 游标源:该存档当前进行中/暂停的 RATH 实验(create_experiment 保证同一存档最多一个)。
    exp_row = db.execute(
        "select id, last_briefed_at from rath_experiments "
        "where save_id=%(sid)s and status in ('running','paused') "
        "order by id desc limit 1",
        {"sid": int(save_id)},
    ).fetchone()
    exp_id = int((exp_row or {}).get("id") or 0)
    last_briefed_at = (exp_row or {}).get("last_briefed_at")
    # 玩家活动时间源:kb_native 档不写 flat messages,回合的权威痕迹是 branch_commits
    # (RATH 铁律离线不写 game state=不建 commit,故 commit 时间恒等于玩家侧活动);
    # messages 兜底旧档,取两者最新。
    last = db.execute(
        """
        select greatest(
            (select max(created_at) from messages where save_id = %(sid)s and role = 'user'),
            (select max(created_at) from branch_commits where save_id = %(sid)s)
        ) as ts
        """,
        {"sid": int(save_id)},
    ).fetchone()
    player_last_activity = (last or {}).get("ts")
    if player_last_activity is None:
        return None
    # 间隔判定不变:必须是"连续对话不打扰"——只看玩家真实活动的间隔,不受游标影响。
    gap = db.execute(
        "select extract(epoch from (now() - %s))/60 as m", (player_last_activity,)).fetchone()
    if float((gap or {}).get("m") or 0) < MIN_GAP_MINUTES:
        return None
    # 窗口起点:游标优先(有过成功简报就从那里续),否则退回玩家活动时间(首次简报)。
    since = last_briefed_at or player_last_activity
    # 取【最新】60 条再反转回时间正序:离线很久时窗口内事件可能远超预算,
    # 回归的玩家该听到的是最近的事,不是刚离开时的旧闻。
    rows = db.execute(
        r"""
        select logical_key, story_time, summary from kb_events
        where save_id = %s and logical_key like 'rath\_%%'
          and retired_at_commit is null and created_at > %s
          and coalesce(summary, '') <> ''
        order by id desc limit 60
        """,
        (int(save_id), since),
    ).fetchall()
    rows = list(reversed(rows or []))
    if not rows:
        return None
    by_day: dict[str, list[str]] = {}
    order: list[str] = []
    for r in rows:
        day = str(r.get("story_time") or "").strip() or "(time unknown)"
        if day not in by_day:
            by_day[day] = []
            order.append(day)
        is_scene = "scene" in str(r.get("logical_key") or "")
        txt = str(r.get("summary") or "").strip()
        if is_scene:
            by_day[day].insert(0, txt[:160])  # 场景优先且给更长篇幅
        elif len(by_day[day]) < 4:
            by_day[day].append(txt[:100])
    header = "=== Offline world digest (what happened in the world on its own while the player was away) ==="
    segs = [f"◆ {day}\n" + "\n".join("  · " + t for t in by_day[day][:4]) for day in order]
    # 预算从最新的日组往前装(最近的事优先入选),输出仍按时间正序。
    # P2 修复:收尾指导句(TAIL_TEXT)固定会拼进最终输出,却从未计入 used——
    # 之前只算 header+picked,导致最终文本可超 MAX_BRIEF_CHARS 约一成。收尾句长度
    # 现在从一开始就占预算,贪心装填因此更保守但不再超编。
    picked: list[str] = []
    used = len(header) + len(TAIL_TEXT)
    for seg in reversed(segs):
        if used + len(seg) > MAX_BRIEF_CHARS:
            break
        picked.append(seg)
        used += len(seg)
    picked.reverse()
    if not picked and segs:
        picked = [segs[-1][:MAX_BRIEF_CHARS]]  # 最新日组独自超预算:截断保底,不空手而归
    if not picked:
        return None
    lines = [header, *picked, TAIL_TEXT]
    result = "\n".join(lines)
    # 成功产出后回写游标(P1):下次窗口从这里续,不再从"玩家最近活动"重新起算。
    if exp_id:
        try:
            db.execute(
                "update rath_experiments set last_briefed_at = now() where id=%s", (exp_id,))
            if hasattr(db, "commit"):
                db.commit()
        except Exception:
            log.debug("[rath] briefing 游标回写跳过(非致命)")
    return result
