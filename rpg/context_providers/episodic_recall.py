"""episodic_recall.py — 永恒记忆·情景召回 context provider(酒馆/自由/模组模式)。

原著改编档(novel_adaptation)的情景召回走 NovelProvider→retrieve_context 内的注入,
本 provider **不挂 novel pack**(避免双注入);挂 tavern/freeform/module —— 这些模式
此前完全没有长程召回(用户实锤:「修的是游戏模式,酒馆没得到修复?」→ 属实,补齐)。

语料优先级:
  1. kb_events(谱系 CTE 分支隔离,vector→keyword,复用 kb.episodic.retrieve_episodic);
  2. kb_events 空(酒馆跳过史官=生产常态,75 档仅 4 档有事件)→ state 全量 history
     确定性打分(score_history_messages),排除近因 6 轮窗口已原文注入的 12 条。

feature gate: episodic_recall(与 novel 路径同一 flag,全局已开);无命中=休眠零注入。
"""
from __future__ import annotations

from core.token_estimate import estimate_tokens

from .base import ContextContribution, ContextProvider
from .registry import register_provider

PRIORITY = 78  # 略低于 memory(60 之上为先出;此处按既有语义放在记忆层附近、近因窗口之前)


class EpisodicRecallProvider(ContextProvider):
    id = "episodic_recall"

    def collect(self, state, manifest, demand, services) -> ContextContribution:
        from core.feature_flags import feature_enabled
        user_id = getattr(services, "user_id", None)
        if not feature_enabled("episodic_recall", user_id):
            return ContextContribution.skipped(self.id, "episodic_recall flag 关闭")

        query = (getattr(demand, "retrieval_query", "") or ""
                 ).strip() or (getattr(demand, "player_intent", "") or "").strip()
        if not query:
            return ContextContribution.skipped(self.id, "无查询文本")

        data = getattr(state, "data", None)
        if not isinstance(data, dict):
            return ContextContribution.skipped(self.id, "state.data 不可用")
        save_id = getattr(services, "save_id", None) or data.get("_active_save_id")

        # 合并同池打分:kb_events + 全量 history 单一排序(酒馆 e2e 实锤教训:两级
        # 短路会让一条弱相关 kb 事件压掉 history 里的真答案,模型只好编造)。
        hist = data.get("history") or []
        commit = 0
        if save_id:
            try:
                from platform_app.db import connect
                with connect() as db:
                    cm = db.execute(
                        "select active_commit_id from game_saves where id=%s",
                        (int(save_id),),
                    ).fetchone()
                commit = int((cm or {}).get("active_commit_id") or 0)
            except Exception:
                commit = 0
        from kb.episodic import retrieve_episodic_merged
        hits = retrieve_episodic_merged(
            int(save_id or 0), commit, user_id, query, hist, k=3, exclude_recent=12)
        if not hits:
            return ContextContribution.skipped(self.id, "无召回(休眠)")
        lines: list[str] = []
        for i, h in enumerate(hits, 1):
            if h.get("kind") == "history":
                lines.append(f"{i}. [Turn {h['turn']} · {h['role']}] {h['text']}")
            else:
                meta = h.get("meta") or ""
                lines.append(f"{i}. {h['text']}" + (f"  ({meta})" if meta else ""))
        source = ",".join(sorted({h.get("kind") or "" for h in hits}))

        text = "\n".join(
            ["Relevant past events recalled from the [whole play history] based on this turn's input. Treat them as facts that already happened; do not retell them as if they were happening now:"]
            + lines
        )
        import logging
        logging.getLogger(__name__).info(
            "[episodic_recall] 注入 %d 条 (source=%s, save=%s)", len(lines), source, save_id)
        layer = self.make_layer(
            "episodic_recall", "Relevant Past Events · Full History Recall", text,
            sticky=False, priority=PRIORITY,
        )
        return ContextContribution(
            provider_id=self.id,
            kind="episodic_recall",
            priority=PRIORITY,
            layers=[layer],
            tokens_estimate=estimate_tokens(text),
            debug={"source": source, "hits": len(lines)},
        )


register_provider(EpisodicRecallProvider())
