"""state._mixins.pending — pending writes / pending questions mixin。

承载:
- _pop_pending_write          (按 id / index 弹出 pending_write)
- approve_pending_write       (审批通过 → 调用 apply_state_write_typed)
- reject_pending_write        (拒绝 → 写 audit_log)
- add_pending_question        (GM 询问玩家入队)
- expire_stale_gm_questions   (玩家新一轮时过期旧 GM 询问)
- clear_pending_question      (玩家回答 / 跳过)

注: user_locks / time_jump / _scan_worldline_validation 等留在 GameState 主 class
(它们与 timeline / worldline 强耦合,不适合搬出去)。
"""
from __future__ import annotations

import logging as _logging

from core.clock import now_iso
from state.parsers import _clean_item, _parse_question
from state.permissions import _normalize_permission_mode, _permission_label

_log = _logging.getLogger(__name__)

# GM 自主叙事记忆写入(后果账本 / NPC 议程 / 推测)在非授权模式下入 pending 时用的
# 合成 path 标记 —— 与 generate_image 同套「合成 path 走特殊 approve 分支」模式。
# approve 时按此分派回专用方法(见 _approve_narrative_op_pending),不走
# apply_state_write_typed 的字段写入路径(这些 op 不是 path=value 字段写入)。
_NARRATIVE_OP_PATHS = frozenset({
    "consequence", "npc_agenda", "hypothesis",
    "confirm_hypothesis", "reject_hypothesis",
})


class PendingMixin:
    """pending writes / pending questions 管理。"""

    def _pop_pending_write(self, *, id: str | None = None, index: int | None = None) -> dict | None:
        """按 id 优先 / index fallback 弹出 pending_write。两者都不命中返回 None。"""
        permissions = self.data.setdefault("permissions", {})
        pending = permissions.setdefault("pending_writes", [])
        if id:
            for i, item in enumerate(pending):
                if str(item.get("id", "")) == str(id):
                    return pending.pop(i)
            return None
        if index is not None and 0 <= int(index) < len(pending):
            return pending.pop(int(index))
        return None

    def approve_pending_write(self, index: int | None = None, *, id: str | None = None) -> str:
        item = self._pop_pending_write(id=id, index=index)
        if item is None:
            return "Failed: pending write not found"
        path = str(item.get("path", ""))

        # ── Phase 1 生图门控：generate_image pending 不走 _set_path，而是入队生图 ──
        if path == "generate_image":
            return _approve_image_pending(item)

        # GM 自主叙事记忆写入(consequence/npc_agenda/hypothesis/...)pending:按 op
        # 重放对应专用方法(这些不是 path=value 字段写入,不能走 apply_state_write_typed)。
        if path in _NARRATIVE_OP_PATHS:
            return self._approve_narrative_op_pending(item)

        # Bug 5：直接传 typed value，不走 spec 字符串往返；防止 list/dict 被 str() 污染。
        result = self.apply_state_write_typed(
            path=path,
            value=item.get("value"),
            source=f"{item.get('source', 'gm')}:approved",
            append=bool(item.get("append")),
            overwrite=bool(item.get("overwrite")),
            force=True,
        )
        # Bug 5 (retest硬要求 #3/#4)：memory.resources 是 inventory 的派生层。
        # 任何对 memory.resources 的审批写入完成后，立刻从 canonical
        # player_character.inventory 重写一遍 —— 防止 GM 的待审值与 canonical
        # 不一致时产生"两条 Torch"这种数据病。
        if path == "memory.resources" and (self.data.get("player_character") or {}).get("inventory"):
            try:
                self.sync_resources_from_inventory()
            except Exception:
                pass
        return result

    def reject_pending_write(self, index: int | None = None, *, id: str | None = None) -> str:
        item = self._pop_pending_write(id=id, index=index)
        if item is None:
            return "Failed: pending write not found"
        permissions = self.data.setdefault("permissions", {})
        permissions.setdefault("audit_log", []).append({
            "ts": now_iso(),
            "path": item.get("path", ""),
            "value": item.get("value", ""),
            "source": f"{item.get('source', 'gm')}:rejected",
            "mode": _normalize_permission_mode(permissions.get("mode", "full_access")),
            "turn": self.data.get("turn", 0),
        })
        permissions["audit_log"] = permissions["audit_log"][-200:]
        return f"状态写入拒绝：{item.get('path', '')}"

    def add_pending_narrative_op(self, op: str, value: dict, *, source: str, display: str) -> str:
        """把 GM 自主叙事记忆写入(consequence/npc_agenda/hypothesis/confirm_/reject_
        hypothesis)入 pending_writes 队列 —— 与 apply_state_write_typed 的字段 pending
        同队列、同前端审批 UI。approve 时按 op 分派回专用方法(_approve_narrative_op_pending)。

        根因:这些 op 原直调 register_consequence / upsert_npc_agenda / add_hypothesis
        等专用方法,完全绕过 apply_state_write_typed 的权限闸门 —— read_only 也拦不住。
        而它们【确实进 GM 上下文注入】(consequence_echo / npc_agenda / memory provider
        消费),有真实叙事影响,故 read_only 承诺「任何 LLM 自动写入都入 pending」对它们
        必须成立。value 里的字段必须 JSON 可序列化(随存档持久化):set 类(extra_known)
        由调用方转 list 存,approve 时重建 set。"""
        import secrets as _secrets
        permissions = self.data.setdefault("permissions", {})
        mode = _normalize_permission_mode(permissions.get("mode", "full_access"))
        pending = {
            "id": _secrets.token_urlsafe(8),
            "path": op,          # 合成标记;approve 按 op 分派(非真实 state path)
            "op": op,
            "value": value,
            "source": source,
            "turn": self.data.get("turn", 0),
            "risk": "medium",
            "field": display,
            "from": "",
            "to": display,
            "reason": f"{_permission_label(mode)} does not allow the GM to write narrative memory automatically",
        }
        permissions.setdefault("pending_writes", []).append(pending)
        permissions["pending_writes"] = permissions["pending_writes"][-20:]
        return f"状态写入待审：{display}"

    def _approve_narrative_op_pending(self, item: dict) -> str:
        """审批通过一条 GM 叙事记忆写入 pending(add_pending_narrative_op 入队的)。
        approve = 用户已授权 → 直接调专用方法落地(绕过权限闸门,不会二次入 pending)。"""
        op = str(item.get("op") or item.get("path") or "")
        value = item.get("value") or {}
        src = f"{item.get('source', 'gm')}:approved"
        if op == "consequence":
            ok, msg = self.register_consequence(
                text=value.get("text", ""),
                due_turns=value.get("due_turns"),
                due_location=value.get("due_location"),
                origin="gm",
            )
            return f"状态写入：{msg}" if ok else msg
        if op == "npc_agenda":
            extra = value.get("extra_known") or []
            ok, msg = self.upsert_npc_agenda(
                name=value.get("name", ""),
                goal=value.get("goal"),
                stance=value.get("stance"),
                extra_known=set(extra) if extra else None,
            )
            return f"状态写入：{msg}" if ok else msg
        if op == "hypothesis":
            mid = self.add_hypothesis(
                text=value.get("text", ""),
                source=src,
                time_label=value.get("time_label"),
                characters=value.get("characters"),
            )
            return f"推测登记：{mid}"
        if op == "confirm_hypothesis":
            hid = value.get("id", "")
            if hid and self.confirm_hypothesis(hid, source=src):
                return f"推测确认：{hid}"
            return f"推测确认失败（id 不存在或非 active）：{hid}"
        if op == "reject_hypothesis":
            hid = value.get("id", "")
            if hid and self.reject_hypothesis(hid):
                return f"推测拒绝：{hid}"
            return f"推测拒绝失败（id 不存在）：{hid}"
        return f"Failed: unknown pending op: {op}"

    def add_pending_question(self, text: str, source: str = "gm", options: list | None = None) -> bool:
        if options is None:
            question, parsed_options = _parse_question(text)
        else:
            question = _clean_item(text)
            parsed_options = [_clean_item(str(x)) for x in options if _clean_item(str(x))]
        if not question:
            return False
        permissions = self.data.setdefault("permissions", {})
        questions = permissions.setdefault("pending_questions", [])
        import secrets as _secrets
        item = {
            "id": _secrets.token_urlsafe(8),
            "question": question,
            "options": parsed_options[:4],
            "source": source,
            "turn": self.data.get("turn", 0),
        }
        # 比较时忽略 id（防止"同样的问题"被重复 push）
        def _same(a, b):
            return (a.get("question") == b.get("question")
                    and a.get("options") == b.get("options"))
        if not any(_same(item, q) for q in questions):
            questions.append(item)
            permissions["pending_questions"] = questions[-8:]
            return True
        return False

    def expire_stale_gm_questions(self, current_turn: int | None = None, reason: str = "next_turn") -> int:
        """玩家进入新一轮(发新 chat 消息)时,把**未回答的旧 GM 询问**过期掉。

        旧版 bug:GM 在 turn N 发询问 ("如何利用井口脱险?"),玩家不点选项直接打字
        "投降" 推进到 turn N+1;GM 在 N+1 再发新询问 → UI "2 项待确认" 同时挂两个,
        玩家很困扰。

        新行为:每次新 chat 处理前,把 turn < current_turn 且 source.startswith("gm")
        / source=="rules_engine" 等系统询问标记过期,从 pending_questions 移除,
        转到 audit_log 留痕。玩家显式回答 / clear 的不受影响(已经从列表 pop 掉)。

        玩家自己 add 的 (source 不含 gm/rules_engine) 不动 (玩家发的笔记 / 提问)。

        返回:过期了几条。
        """
        permissions = self.data.setdefault("permissions", {})
        questions = permissions.setdefault("pending_questions", [])
        if not questions:
            return 0
        cur = int(current_turn if current_turn is not None else self.data.get("turn", 0) or 0)
        keep: list[dict] = []
        expired: list[dict] = []
        # 哪些 source 算系统询问 → 新一轮自动过期。
        # 反馈#61:GM 主询问(ask_player_choice)用 source="agent:choice"、锚点用 "gm_generated"、
        # 配置卡用 "agent:config_card" —— 它们都【不】匹配旧列表的 "gm" → 上轮未答的 GM 询问
        # 不被过期、与本轮新询问同时挂(玩家自行输入走向后「第一轮+第二轮询问」并存)。补全。
        system_sources = ("gm", "gm_generated", "agent", "rules_engine", "curator",
                          "curator:clarify", "extractor", "set_parser")
        for q in questions:
            q_turn = int(q.get("turn") or 0)
            q_source = str(q.get("source") or "")
            is_system = any(q_source == s or q_source.startswith(s + ":") for s in system_sources)
            if is_system and q_turn < cur:
                expired.append(q)
            else:
                keep.append(q)
        if not expired:
            return 0
        permissions["pending_questions"] = keep
        # audit
        audit = permissions.setdefault("audit_log", [])
        audit.append({
            "ts": now_iso(),
            "kind": "pending_questions_expired",
            "source": "expire_stale_gm_questions",
            "reason": reason,
            "current_turn": cur,
            "expired_count": len(expired),
            "expired": [
                {"id": q.get("id"), "turn": q.get("turn"), "source": q.get("source"),
                 "question": (q.get("question") or "")[:80]}
                for q in expired
            ],
        })
        if len(audit) > 200:
            permissions["audit_log"] = audit[-200:]
        return len(expired)

    def clear_pending_question(self, index: int | None = None, *, id: str | None = None, choice: str | None = None) -> dict | None:
        """同 _pop_pending_write：按 id 优先，index fallback。
        choice：玩家选择的答案，写进 audit_log 留痕（默认 None = 强制跳过）。
        """
        permissions = self.data.setdefault("permissions", {})
        questions = permissions.setdefault("pending_questions", [])
        popped = None
        if id:
            for i, q in enumerate(questions):
                if str(q.get("id", "")) == str(id):
                    popped = questions.pop(i)
                    break
        elif index is not None and 0 <= int(index) < len(questions):
            popped = questions.pop(int(index))
        if popped is not None:
            permissions.setdefault("audit_log", []).append({
                "ts": now_iso(),
                "kind": "question_answered",
                "question": popped.get("question", ""),
                "choice": choice or "(skipped)",
                "source": popped.get("source", "gm"),
                "turn": self.data.get("turn", 0),
            })
            permissions["audit_log"] = permissions["audit_log"][-200:]
        return popped


# ── Phase 1: generate_image pending 审批辅助函数（模块级，不在 mixin 内）─────────

def _approve_image_pending(item: dict) -> str:
    """处理 path=="generate_image" 的 pending_write 审批。

    不走 apply_state_write_typed / _set_path（生图不是状态字段写入），
    而是用 pending value（即工具的 args）重新入队生图，origin="api_direct"
    （玩家点击 approve = 显式授权，等价于 ui_button 触发）。

    普通 pending_write 审批路径完全不受影响：只有 path=="generate_image" 走此分支。
    整合前 import platform_app.image_jobs 可能失败（A/B 并行开发）——返回友好错误。
    """
    try:
        from platform_app.image_jobs import enqueue_image_generation
    except ImportError as exc:
        _log.warning("[pending] _approve_image_pending: import failed: %s", exc)
        return f"Failed: image generation module is not ready ({exc})"

    value: dict = item.get("value") or {}
    prompt: str = str(value.get("prompt") or "").strip()
    if not prompt:
        return "Failed: the pending image prompt is empty; cannot queue it"

    kind: str = str(value.get("kind") or "chat")
    api_id: str | None = value.get("api_id") or None
    model: str | None = value.get("model") or None
    extra: dict = value.get("extra") or {}
    user_id_raw = value.get("user_id")

    user_id: int = 0
    if user_id_raw is not None:
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            pass

    if not user_id:
        return "Failed: the pending image request has no user_id; cannot queue it"

    try:
        result = enqueue_image_generation(
            user_id,
            prompt,
            kind,
            api_id=api_id,
            model=model,
            origin="api_direct",  # 玩家审批 = 视为 api_direct（不再计入自主计数）
            extra=extra if extra else None,
        )
        image_id = result.get("image_id")
        _log.info(
            "[pending] approved image_pending image_id=%s user_id=%s kind=%s",
            image_id, user_id, kind,
        )
        return (
            f"Image generation approved: image_id={image_id} queued (status=pending). "
            f"The URL is pushed over SSE when it finishes. prompt={prompt!r}"
        )
    except Exception as exc:
        _log.exception("[pending] _approve_image_pending enqueue failed")
        return f"Failed: could not queue image generation - {exc}"
