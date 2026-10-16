"""
RecentChatProvider — 通用最近对话注入。
"""
from __future__ import annotations

from core.token_estimate import estimate_tokens

from .base import ContextContribution, ContextProvider
from .registry import register_provider


class RecentChatProvider(ContextProvider):
    id = "recent_chat"

    def collect(self, state, manifest, demand, services) -> ContextContribution:
        try:
            # include_digest=False:本层标题就是「最近对话」,不能混进已 closed phase 的
            # 前情提要(最旧的开局摘要)。历史由 runtime_phase_digests 层单独注入。
            history = state.history_messages(include_digest=False)
        except Exception:
            history = (getattr(state, "data", state) or {}).get("history") or []
        if not history:
            return ContextContribution.skipped(self.id, "no history")

        formatted_lines: list[str] = []
        for msg in history[-6:]:
            role = msg.get("role") or "user"
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            prefix = "Player" if role == "user" else "GM"
            formatted_lines.append(f"{prefix}: {content[:600]}")
        text = "\n\n".join(formatted_lines) or "(no conversation yet)"
        layer = self.make_layer(
            "recent_chat", "Recent Conversation", text,
            sticky=False, priority=20,  # 低 priority：放在 prompt 末尾
        )
        return ContextContribution(
            provider_id=self.id,
            kind="recent_chat",
            priority=20,
            layers=[layer],
            tokens_estimate=estimate_tokens(text),
            debug={"turns": len(history)},
        )


register_provider(RecentChatProvider())
