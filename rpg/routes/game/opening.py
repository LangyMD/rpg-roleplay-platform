"""routes.game.opening —— /api/opening(开场流水线 · SSE)。

含 rail(贴原著)开场策略(_RAIL_OPENING_INSTRUCTION / _game_opening_policy)。
同步 generator → 异步 SSE 的桥接器收敛到权威 chat_pipeline._common._bridge_sync_generator_to_async
(强版:_Error wrapper 区分「产出项」与「异常」,消除弱版 `isinstance(item, Exception)` 把
generator 正常 yield 的 Exception 实例误判为错误的隐患;并支持 *args/**kwargs 透传)。本模块
仍以本名 re-export 该桥(routes.game.__init__ 依赖此名)。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import Depends
from fastapi.responses import StreamingResponse

from chat_pipeline._common import _bridge_sync_generator_to_async
from routes._deps_fastapi import get_current_user
from state.parsers import _extract_trailing_markdown_options

from ._shared import _client_safe_error, _note_channel_health_failure, router

# ── 游戏流水线 · 开场策略(rail 知识只住游戏层,不进底层 GMAgent)──────────────
# 反馈#73:开了「贴原著」开局仍脱离原著、原著开篇人物(张杰/雇佣兵等)流失。原因:开场默认
# 提示词强制 150-250 字 + max_tokens=600,把已注入的原著开场压成极短原创、丢人物。
# 修复边界:底层 generate_opening 通用化(只收 prompt+预算);这里——游戏这条流水线——按
# steering_strength 决定 rail 时用"忠实重现原著开篇"的提示 + 更大预算。酒馆/编辑器不调此处,零影响。
_RAIL_OPENING_INSTRUCTION = """\
The player chose the "follow the source" steering strength. Using the anchor chapter source text
(follow-the-source tier) in this turn's context bundle, faithfully recreate the source's opening scene
as the player's entry point into the story.

Requirements:
- Keep the source opening's time, place, **characters present and key dialogue/events**. Keep the
  supporting characters and crowd that appear in the source opening too; do not write only the
  protagonist, and do not replace or omit characters who appear in the source opening.
- Keep key lines of dialogue verbatim or in their original meaning. Do not skip or gloss over the
  conflicts, encounters or turns in the source opening.
- Bring the player character into this scene according to their character card / starting point
  (their identity can decide the viewpoint and entry point), but do not let the opening drift away
  from the source.
- Treat the injected source text as authoritative; do not freely write a different opening from
  training memory.
- **Only recreate what actually appears in the injected source text**: do not add plot, endings,
  character fates, promotions or rewards beyond it (stop where the source stops). State write-back
  (memory.facts etc.) should also record only what the source contains; do not invent.

**User director instruction (highest priority)**: if the context contains a high-priority steering
instruction from the player to the GM, follow that intent within the source opening's framework
(scene details / angle of entry), but do not remove or change the main characters and key events.

End with an actionable hook or choice, and do not make decisions for the player.
Length: 500-900 words (the opening needs enough room for the source's characters and setting; do not
compress it into something very short).
"""


def _game_opening_policy(steering_strength: str) -> tuple[str | None, int]:
    """游戏流水线的开场策略。rail(贴原著)→(忠实重现提示, 1600);其它 →(None=底层默认开场, 600)。
    返回 (prompt 覆盖 | None, max_tokens)。底层据此生成,但不认识 rail 本身。"""
    if steering_strength == "rail":
        return (_RAIL_OPENING_INSTRUCTION, 1600)
    return (None, 600)


@router.post("/api/opening")
async def api_opening(
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> StreamingResponse:
    from app import (
        _active_script_id,
        _build_turn_context,
        _ensure_loaded,
        _get_gm,
        _payload_sse,
        _persist_runtime_checkpoint,
        _resolve_persist_target,
        _sse,
        platform_branches,
        platform_knowledge,
        retrieve_context,
    )
    state = _ensure_loaded(api_user)
    gm = _get_gm(api_user)

    async def stream():
        # task 121a: 4 阶段 stage 事件让前端能显示 thinking pill,避免 5-15s 无反馈
        yield _sse("stage", {"phase": "retrieving", "label": "Reading the script lore…"})
        # 修(task 117):走 phase 算法路径 — 不硬编码"第一章"。
        script_id = _active_script_id(api_user)
        if script_id:
            world = state.data.get("world", {}) or {}
            player = state.data.get("player", {}) or {}
            memory = state.data.get("memory", {}) or {}
            events = world.get("known_events") or []
            query_parts = [
                str(player.get("current_location") or ""),
                str(world.get("time") or ""),
                str(memory.get("current_objective") or ""),
                *[str(e) for e in events[:2]],
            ]
            query = " ".join(p for p in query_parts if p).strip() or "开场"
        else:
            query = "开场"

        # P0-1: retrieve_context + build_context_bundle 包进 to_thread,不阻塞 event loop
        def _retrieve_and_build():
            _ctx = retrieve_context(
                query,
                state=state,
                user_id=api_user["id"] if api_user else None,
                script_id=script_id,
            )
            state.set_last_retrieval(_ctx)
            _, _save_id_for_ctx = _resolve_persist_target(api_user)
            _bundle = _build_turn_context(state, query, _ctx, script_id=script_id, save_id=_save_id_for_ctx)
            return _bundle

        yield _sse("stage", {"phase": "building_context", "label": "Assembling context…"})
        bundle = await asyncio.to_thread(_retrieve_and_build)
        # 游戏层决定开场策略:读该存档引导强度,rail→忠实重现原著开篇提示+大预算(#73)。
        _steering = "guided"
        try:
            _, _sid_steer = _resolve_persist_target(api_user)
            if _sid_steer:
                from platform_app.db import connect as _conn_steer
                with _conn_steer() as _db_steer:
                    _row_steer = _db_steer.execute(
                        "select worldline->>'steering_strength' as ss from game_sessions where save_id=%s",
                        (_sid_steer,),
                    ).fetchone()
                if _row_steer and _row_steer.get("ss"):
                    _steering = _row_steer["ss"]
        except Exception:
            _steering = "guided"
        _open_prompt, _open_tokens = _game_opening_policy(_steering)
        yield _sse("status", _payload_sse(api_user))
        yield _sse("stage", {"phase": "generating", "label": "GM is planning the opening…"})
        text = ""
        try:
            # P0-1: generate_opening_stream 是同步 generator,通过 bridge 异步化
            # stop_event 在 SSE 断开时由 bridge finally 设置,让 sync generator 提前退出
            _opening_stop = threading.Event()
            # 流式 ops 围栏抑制(与 chat 主循环同一 StreamFenceGuard):开场同样是
            # 「裸转发 + 落库前清洗」,半截 ```json 会漏给玩家。text 累积不受影响。
            from state import StreamFenceGuard
            _fence_guard = StreamFenceGuard()
            # 流式重试(与 chat 主循环同一包装器):首个非空 chunk 之前的 upstream/
            # ratelimit 失败静默重试(裸字符串流,不发 notice 事件防混入正文)。
            from agents.gm.stream_retry import opening_chunk_commits, stream_with_pretoken_retry

            def _opening_factory():
                return gm.generate_opening_stream(state, retrieved_context=bundle["prompt"], stop_event=_opening_stop,
                                                  prompt=_open_prompt, max_tokens=_open_tokens)

            async for chunk in _bridge_sync_generator_to_async(
                lambda: stream_with_pretoken_retry(
                    _opening_factory, is_commit=opening_chunk_commits,
                    emit_retry_notice=False, stop_event=_opening_stop,
                ),
                stop_event=_opening_stop,
            ):
                text += chunk
                _fence_fw = _fence_guard.feed(chunk)
                if _fence_fw:
                    yield _sse("token", {"text": _fence_fw})
            _fence_tail = _fence_guard.flush()
            if _fence_tail:
                yield _sse("token", {"text": _fence_tail})
            opening = text
            yield _sse("stage", {"phase": "done", "label": ""})
            opening_for_history, opening_options = _extract_trailing_markdown_options(opening)
            # 剥掉 ops JSON 围栏 / 工具元叙述 / 泄漏脚手架,得到给玩家看 + 落历史的干净正文。
            # 复用 chat 路径同一套 stripper(chat_pipeline 落库前也这么洗);结构化解析仍用含 ops
            # 的 opening_for_history(见下方 apply_structured_updates)。根因:开场原先直接存原文,
            # ```json ops 块漏给玩家(基准测出多档开场命中 leak)。
            from state import strip_json_state_ops, strip_leaked_scaffold, strip_meta_tool_preamble
            opening_visible = strip_leaked_scaffold(strip_meta_tool_preamble(strip_json_state_ops(opening_for_history)))
            state.data["history"].append({"role": "assistant", "content": opening_visible})
            # 让开场也走结构化解析,把【询问玩家】+JSON ops 解析进 pending_questions / state
            before_questions = len((state.data.get("permissions") or {}).get("pending_questions") or [])
            try:
                state.apply_structured_updates(opening_for_history)
            except Exception:
                import logging as _logging
                _logging.getLogger(__name__).warning("opening apply_structured_updates failed", exc_info=True)
            after_questions = len((state.data.get("permissions") or {}).get("pending_questions") or [])
            if opening_options and after_questions == before_questions:
                state.add_pending_question("What do you do?", source="gm:opening_options", options=opening_options)
            state.save()
            try:
                persist_user_id, active_save_id = _resolve_persist_target(api_user)
                if api_user and persist_user_id and active_save_id:
                    _open_rt = platform_branches.record_runtime_turn(
                        "",
                        opening_visible,
                        user_id=api_user["id"],
                        state_data=state.data,
                    )
                    # 并发双开:开场已在别处生成(record_runtime_turn 检测活跃指针漂移已原子放弃)。
                    # 发冲突错误让前端刷新,跳过后续 session/messages 写入,不落半个开场。
                    if isinstance(_open_rt, dict) and _open_rt.get("conflict"):
                        yield _sse("error", {
                            "message": "The opening was already generated elsewhere; please refresh and try again.",
                            "kind": "save_conflict",
                        })
                        yield _sse("done", {"status": _payload_sse(api_user), "interrupted": True})
                        return
                    platform_knowledge.ensure_game_session(persist_user_id, active_save_id, state.data)
                    # 写入 messages 表:kb_native 存档 materialize() 从 messages 重建 history,
                    # 若不写,开场白在 messages 表缺失 → materialize 丢开场 → 前端只显示后续对话。
                    try:
                        platform_knowledge.record_turn_messages(
                            persist_user_id,
                            active_save_id,
                            state.data,
                            "",
                            opening_visible,
                        )
                    except Exception:
                        pass
                else:
                    _persist_runtime_checkpoint(state, api_user)
            except Exception:
                _persist_runtime_checkpoint(state, api_user)
            # 渠道健康门控:开场也走成功即清零(与主 chat 流程 persist_turn_phase 同口径)。
            try:
                import model_probe
                model_probe.note_channel_success(gm.api_id, user_id=(api_user or {}).get("id"))
            except Exception:
                pass
            yield _sse("done", {"status": _payload_sse(api_user)})
        except Exception as exc:
            _note_channel_health_failure(exc, gm.api_id, api_user)
            yield _sse("error", {"message": _client_safe_error(
                exc,
                user_id=(api_user or {}).get("id"),
                api_id=getattr(gm, "api_id", "") or "",
                model=getattr(getattr(gm, "_backend", None), "model_name", "") or "",
                scenario="opening",
            ), "partial": text})
            yield _sse("done", {"interrupted": True, "status": _payload_sse(api_user)})

    return StreamingResponse(stream(), media_type="text/event-stream")
