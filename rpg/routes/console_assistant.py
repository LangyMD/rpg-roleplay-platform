"""console_assistant.py — 侧栏控制台助手路由 (/api/console_assistant/*)。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from platform_app.api._deps import json_response
from routes._deps_fastapi import get_current_user
from schemas._common import COMMON_ERROR_RESPONSES, GenericOkResponse, OkResponse
from schemas.console_assistant import (
    ConsoleAssistantChatRequest,
    ConsoleAssistantConfirmRequest,
    ConsoleAssistantContinueRequest,
    ConsoleAssistantDeleteConversationRequest,
)

router = APIRouter()


@router.get("/api/console_assistant/ping")
async def api_console_assistant_ping() -> JSONResponse:
    """task 48: 给前端探测后端是否就绪,200 = 真后端可用 (前端切走 mock)。"""
    return json_response({"ok": True, "service": "console_assistant", "version": "1"})


@router.get("/api/console_assistant/conversations")
async def api_console_assistant_conversations(
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """task 111: 列当前用户所有对话。"""
    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return json_response({"items": []})
    from console_assistant import list_conversations
    from console_assistant.conversations import list_conversations_pg
    items = list_conversations(user_id)
    seen = {it.get("id") for it in items}
    # 进程内 dict 在 worker 重启后为空 → 并入 PG 持久化的对话(刷新/换 worker 也能列出历史会话)。
    for it in list_conversations_pg(user_id):
        if it.get("id") not in seen:
            items.append(it)
            seen.add(it.get("id"))
    items.sort(key=lambda r: r.get("last_used", ""), reverse=True)
    return json_response({"items": items})


@router.get("/api/console_assistant/conversations/{conversation_id}/messages")
async def api_console_assistant_conversation_messages(
    conversation_id: str,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """取某对话的可渲染历史(用于刷新后还原侧栏 agent 会话)。

    conv['messages'] 是 LLM 格式 [{role,content}],其中工具结果以 assistant 消息 `[tool …]`
    的形式夹在中间(给模型看的)。这里还原成前端可渲染的简洁会话:只保留用户消息 + 每轮最终回答,
    跳过工具结果中间态(避免一堆裸 tool 文本)。Redis 兜底,跨 worker / 重启(6h 内)可还原。"""
    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return json_response({"ok": False, "error": "Login required"}, status_code=401)
    cid = str(conversation_id or "").strip()
    if not cid:
        return json_response({"ok": False, "error": "conversation_id is required"}, status_code=400)
    from console_assistant.conversations import _get_or_create_conversation
    _cid, conv = _get_or_create_conversation(user_id, cid)
    # 优先用 ui_turns(含每轮工具调用:名/参数/状态/结果)→ 刷新后工具历史不丢、可还原折叠块。
    ui_turns = conv.get("ui_turns")
    if isinstance(ui_turns, list) and ui_turns:
        out = []
        for tnu in ui_turns:
            if not isinstance(tnu, dict):
                continue
            role = tnu.get("role") or "assistant"
            text = str(tnu.get("text") or "")
            tools = tnu.get("tools") if isinstance(tnu.get("tools"), list) else []
            if not text.strip() and not tools:
                continue
            out.append({"role": role, "text": text, "tools": tools})
        return json_response({"ok": True, "conversation_id": _cid, "messages": out})
    # 兜底(旧对话无 ui_turns):仅文本还原。
    out = []
    for m in (conv.get("messages") or []):
        role = m.get("role")
        content = str(m.get("content") or "")
        if role == "assistant" and content.startswith("[tool "):
            continue  # 工具结果中间态,不回灌
        if not content.strip():
            continue
        out.append({"role": role, "text": content, "tools": []})
    return json_response({"ok": True, "conversation_id": _cid, "messages": out})


@router.post("/api/console_assistant/new_conversation", response_model=GenericOkResponse, responses=COMMON_ERROR_RESPONSES)
async def api_console_assistant_new_conversation(
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """task 111: 开新对话, 返新 conversation_id。"""
    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return json_response({"ok": False, "error": "Login required"}, status_code=401)
    from console_assistant import new_conversation
    new_id = new_conversation(user_id)
    return json_response({"ok": True, "conversation_id": new_id})


@router.post("/api/console_assistant/delete_conversation", response_model=OkResponse, responses=COMMON_ERROR_RESPONSES)
async def api_console_assistant_delete_conversation(
    body: ConsoleAssistantDeleteConversationRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """task 111: 删除某对话。"""
    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return json_response({"ok": False, "error": "Login required"}, status_code=401)
    body_dict = body.model_dump(exclude_none=True)
    cid = str(body_dict.get("conversation_id") or "").strip()
    if not cid:
        return json_response({"ok": False, "error": "conversation_id is required"}, status_code=400)
    from console_assistant import delete_conversation
    ok = delete_conversation(user_id, cid)
    return json_response({"ok": ok})


@router.post("/api/console_assistant/chat")
async def api_console_assistant_chat(
    body: ConsoleAssistantChatRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> StreamingResponse:
    """task 48: 侧栏助手主聊天 SSE endpoint。

    body: { message: str, conversation_id?: str, page_context?: dict }
    SSE: meta / token / tool_call / tool_result / confirmation_required / error / done
    """
    from app import _ensure_loaded, _resolve_console_assistant_backend
    body_dict = body.model_dump(exclude_none=True)
    message = str(body_dict.get("message") or "").strip()
    conversation_id = body_dict.get("conversation_id")
    if isinstance(conversation_id, str):
        conversation_id = conversation_id.strip() or None
    else:
        conversation_id = None
    page_context = body_dict.get("page_context") if isinstance(body_dict.get("page_context"), dict) else None

    if not message:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':'Empty message'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )

    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':'Login required'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )

    # 注意:这里 state_provider 用 _ensure_loaded — 只有 save scope 工具用得到。
    def _sp(env):
        try:
            if env.save_id is None:
                return None
            return _ensure_loaded(api_user)
        except Exception:
            return None

    # 解析 backend
    try:
        backend = _resolve_console_assistant_backend(api_user)
    except Exception as exc:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':f'Backend initialization failed: {exc}'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )

    from console_assistant import stream_chat as _stream_chat
    # 接入站点统一模型参数(与 GM 一致):max_tokens 走用户 settings.max_tokens 偏好,不再写死 1200。
    try:
        from app import _chat_max_tokens
        _mt = _chat_max_tokens(api_user)
    except Exception:
        _mt = 1200

    def _gen():
        yield from _stream_chat(
            user_id=user_id,
            message=message,
            conversation_id=conversation_id,
            page_context=page_context,
            backend=backend,
            state_provider=_sp,
            max_tokens=_mt,
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")


def _editor_panel_model(user_id: int) -> tuple[str | None, str | None]:
    """续写 / 改写 / 内联补全默认跟随「编辑器 AI 面板」选的模型
    (user_preferences.console_assistant_model_override = {api_id, model},与右栏聊天同源,见 app.py)。
    否则 editor.* 偏好从没有任何 UI 写入、永远落 resolve_api_and_model 的 fallback,跟用户在面板里选的
    模型不一致 → 续写可能用了未配置/不同的模型 → 返空「啥也没看到」(群反馈 耀月余辉)。无 → (None, None)。"""
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            row = db.execute(
                "select preferences from user_preferences where user_id = %s", (int(user_id),),
            ).fetchone()
        prefs = (row and row.get("preferences")) or {}
        ov = prefs.get("console_assistant_model_override") if isinstance(prefs, dict) else None
        if isinstance(ov, dict):
            return (ov.get("api_id") or None, ov.get("model") or None)
    except Exception:
        pass
    return (None, None)


@router.post("/api/console_assistant/autocomplete")
async def api_console_assistant_autocomplete(
    request: Request,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """编辑器内联续写(Copilot ghost text):据光标前文给【一句】短续写,作者按 Tab 采纳。

    body: { before, script_id?, chapter_index? }。owner-scoped + 用户自有模型/key(云端隔离)。
    非流式、短输出(max_tokens 小)、上下文精简(只 before + 写作规范)以求低延迟低成本。
    """
    try:
        body = await request.json()
    except Exception:
        return json_response({"ok": False, "error": "Request body must be valid JSON"}, status_code=400)
    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return json_response({"ok": False, "error": "Login required"}, status_code=401)
    before = str(body.get("before") or "")[-1500:]
    if not before.strip():
        return json_response({"ok": True, "text": ""})

    rules = ""
    script_id = body.get("script_id")
    if script_id is not None:
        try:
            sid = int(script_id)
        except (TypeError, ValueError):
            return json_response({"ok": False, "error": "Invalid script_id"}, status_code=400)
        try:
            from platform_app.db import connect, init_db
            from platform_app.perms import script_owned
            init_db()
            with connect() as db:
                if not script_owned(db, sid, user_id):
                    return json_response({"ok": False, "error": "Not allowed to modify this script: only the original author can use AI continuation."}, status_code=403)
                row = db.execute("select writing_rules from scripts where id=%s", (sid,)).fetchone()
                rules = str((row.get("writing_rules") if row else "") or "").strip()[:1000]
        except Exception:
            return json_response({"ok": False, "error": "Script ownership check failed"}, status_code=200)
        script_id = sid
    else:
        script_id = None

    try:
        from agents._harness import resolve_api_and_model
        _ov_api, _ov_model = _editor_panel_model(user_id)
        api_id, model_real = resolve_api_and_model(
            user_id, api_pref_key="editor.api_id", model_pref_key="editor.model_real_name",
            api_id_override=_ov_api, model_override=_ov_model,
        )
    except Exception:
        return json_response({"ok": False, "error": "No usable model configured"}, status_code=200)
    if not api_id or not model_real:
        return json_response({"ok": False, "error": "No usable model configured"}, status_code=200)

    try:
        from agents.gm import GameMaster
        backend = GameMaster(api_id=str(api_id), model=str(model_real), user_id=user_id)._backend
    except Exception:
        return json_response({"ok": False, "error": "Model backend initialization failed"}, status_code=200)

    sys_prompt = (
        "You are a fiction autocomplete engine. Task: following the prose at the author's cursor, write a **short** continuation "
        "that comes right after it (about 5-25 words, at most one sentence) for the author to accept with Tab. Strict rules: "
        "(1) Output only the continuation itself; never repeat existing text, and add no quotes, explanations, titles or leading ellipses; "
        "(2) Match the preceding text exactly in tone, person, tense and style; "
        "(3) If the last sentence is unfinished, complete it naturally; if it is finished, start a new sentence that follows on; "
        "(4) Write in the same language as the existing narration; do not switch languages without reason."
    )
    if rules:
        sys_prompt += "\n\n[Author's writing guidelines (must follow)]\n" + rules
    user_prompt = "[Preceding text - continue right after its last character]\n" + before

    text = ""
    try:
        for chunk in backend.stream(sys_prompt, [{"role": "user", "content": user_prompt}], max_tokens=80):
            if chunk:
                text += chunk
            if len(text) > 240:
                break
    except Exception as exc:
        import logging
        logging.getLogger("console_assistant").info("autocomplete failed: %s", type(exc).__name__)
        from agents.provider_errors import classify_provider_error
        known = classify_provider_error(exc)
        return json_response({"ok": False, "error": (known[1] if known else "Continuation failed")}, status_code=200)

    # 清洗:去首尾空白/引号/省略号前缀;去掉模型可能回声的上文尾巴。
    text = text.strip().strip('「」“”"\'').lstrip("….—- ").strip()
    text = text[:160]

    try:
        usage = getattr(backend, "last_usage", None) or {}
        if usage and (usage.get("input_tokens") or usage.get("output_tokens")):
            from platform_app.usage import record_usage
            record_usage(
                user_id=user_id, save_id=None, context_run_id=None,
                api_id=str(getattr(backend, "api_id", None) or api_id),
                model_real_name=str(getattr(backend, "model_name", None) or model_real),
                usage=usage, metadata={"kind": "editor_autocomplete", "script_id": script_id},
                scenario="assistant",
            )
    except Exception:
        pass

    return json_response({"ok": True, "text": text})


@router.post("/api/console_assistant/confirm")
async def api_console_assistant_confirm(
    body: ConsoleAssistantConfirmRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> StreamingResponse:
    """task 58: 对一个 pending destructive 工具调用做决策, 返 SSE 流。

    body: { conversation_id: str, call_id: str, decision: 'approve'|'reject',
            page_context?: dict }
    SSE: 与 /chat endpoint 同款 (meta / tool_call / tool_result / token /
         confirmation_required / navigation_required / error / done)

    旧 JSON 协议已弃用 — 修复:用户点确认后 LLM 必须基于工具结果续写,
    否则对话直接断在工具结果。
    """
    from app import _ensure_loaded, _resolve_console_assistant_backend
    body_dict = body.model_dump(exclude_none=True)
    conversation_id = str(body_dict.get("conversation_id") or "").strip()
    call_id = str(body_dict.get("call_id") or "").strip()
    decision = str(body_dict.get("decision") or "").strip().lower()
    page_context = body_dict.get("page_context") if isinstance(body_dict.get("page_context"), dict) else None
    if not conversation_id or not call_id or decision not in {"approve", "reject"}:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':'conversation_id / call_id / decision are required; decision must be approve or reject'}, ensure_ascii=False)}\n\n",
                  "event: done\ndata: {}\n\n"]),
            media_type="text/event-stream",
            status_code=400,
        )

    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':'Login required'}, ensure_ascii=False)}\n\n",
                  "event: done\ndata: {}\n\n"]),
            media_type="text/event-stream",
            status_code=401,
        )

    def _sp(env):
        try:
            if env.save_id is None:
                return None
            return _ensure_loaded(api_user)
        except Exception:
            return None

    try:
        backend = _resolve_console_assistant_backend(api_user)
    except Exception as exc:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':f'Backend initialization failed: {exc}'}, ensure_ascii=False)}\n\n",
                  "event: done\ndata: {}\n\n"]),
            media_type="text/event-stream",
        )

    from console_assistant import apply_confirmation_stream as _apply_stream

    def _gen():
        yield from _apply_stream(
            user_id=user_id,
            conversation_id=conversation_id,
            call_id=call_id,
            decision=decision,
            page_context=page_context,
            backend=backend,
            state_provider=_sp,
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ── MD 编辑器:AI 续写/改写正文(流式纯文本,无工具)──────────────────
# 像 Cursor 写代码:LLM 只产正文文本片段,前端决定插哪。本端点只负责流式产文本。

_CONTINUE_BEFORE_CAP = 4000   # before 截到末尾这么多字
_CONTINUE_AFTER_CAP = 1500    # after 截到开头这么多字
_CONTINUE_SELECTION_CAP = 4000

_CONTINUE_SYSTEM_PROMPT = (
    "You are a fiction prose writing assistant. **Output only the plain-text passage to insert into / replace in the manuscript**: "
    "no explanations, no markdown, do not repeat the surrounding text, and do not wrap it in quotes.\n"
    "\n"
    "[Top priority] If an [Instruction] is given, follow it strictly; it overrides every default behavior "
    "(including the default of simply continuing onward) - write what it asks for, the way it asks. "
    "For anything the instruction does not cover, still follow [Consistent style] below.\n"
    "\n"
    "[Consistent style] Your output must blend seamlessly into the context, keeping what the context already uses:\n"
    "  - person and tense (first/third person, past/present tense);\n"
    "  - point of view and narrative distance (omniscient/limited, close to the inner voice or coolly observed);\n"
    "  - tone and register (literary or colloquial, formal or casual);\n"
    "  - word choice and sentence rhythm (mix of long and short sentences, punctuation density, paragraph pacing);\n"
    "  - dialogue style and punctuation (quote style, how dialogue and action are interleaved);\n"
    "  - content intensity (keep explicitness or restraint consistent with the context unless the [Instruction] says otherwise "
    "- this platform allows adult content).\n"
    "Treat before/after/selection only as context that may be truncated.\n"
    "\n"
    "[Consistent lore] If [Relevant lore] is given (this script's existing worldbook / characters / terms / point in time), "
    "draw on it and stay faithful: characters act true to their profiles, use the established terms and place names, and never contradict it. "
    "But do not invent brand-new characters, factions, places or major lore beyond [Relevant lore] and the surrounding text - "
    "take needed details from the given lore first, and where it is silent make reasonable, non-conflicting inferences instead of inventing from scratch. "
    "Without [Relevant lore], continue sensibly from the surrounding text and do not force in major new lore that conflicts with the script.\n"
    "\n"
    "- continue mode: write a bridging passage between [Before] and [After] that follows on from [Before] and connects naturally to [After]; "
    "if an [Instruction] is given, follow it as [Top priority], otherwise simply continue onward, keeping [Consistent style] throughout.\n"
    "- rewrite mode: rewrite the [Selected text] into a new version according to the [Instruction], and output only the new version; "
    "the rewrite must still keep [Consistent style] with the surrounding text."
)


def _build_continue_user_prompt(
    *, before: str, after: str, selection: str, instruction: str, mode: str,
    environment: str = "",
) -> str:
    """把 before/after/selection/instruction 组织进 user_prompt,清楚标注每段。
    environment:阶段2 注入的「相关设定」环境块(可空),放最前供 LLM 援引保持忠实一致。"""
    parts: list[str] = []
    if environment:
        parts.append(environment)
    parts.append(f"[Mode] {'rewrite' if mode == 'rewrite' else 'continue'}")
    if before:
        parts.append(f"[Before] (text before the cursor; may be truncated)\n{before}")
    if mode == "rewrite" and selection:
        parts.append(f"[Selected text] (rewrite this into a new version)\n{selection}")
    if after:
        parts.append(f"[After] (text after the cursor; may be truncated)\n{after}")
    if instruction:
        parts.append(f"[Instruction (top priority, overrides defaults)]\n{instruction}")
    if mode == "rewrite":
        parts.append("Output only the rewritten new version of the [Selected text]; no explanations, and do not repeat the surrounding text.")
    else:
        parts.append("Write a bridging passage between [Before] and [After]; output only the newly added text.")
    return "\n\n".join(parts)


@router.post("/api/console_assistant/continue")
async def api_console_assistant_continue(
    body: ConsoleAssistantContinueRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> StreamingResponse:
    """MD 编辑器「AI 续写/改写正文」流式端点(纯文本,无工具)。

    body: { before, after, instruction?, selection?, mode?='continue'|'rewrite',
            script_id?, api_id?, model? }
    SSE: token{text} / done{} / error{message}
    """
    body_dict = body.model_dump(exclude_none=True)
    before = str(body_dict.get("before") or "")
    after = str(body_dict.get("after") or "")
    instruction = str(body_dict.get("instruction") or "").strip()
    selection = str(body_dict.get("selection") or "")
    mode = str(body_dict.get("mode") or "continue").strip().lower()
    if mode not in ("continue", "rewrite"):
        mode = "continue"
    script_id = body_dict.get("script_id")
    api_id_in = (str(body_dict.get("api_id")).strip() or None) if body_dict.get("api_id") else None
    model_in = (str(body_dict.get("model")).strip() or None) if body_dict.get("model") else None
    _ci_in = body_dict.get("chapter_index")
    try:
        chapter_index = int(_ci_in) if _ci_in is not None else None
    except (TypeError, ValueError):
        chapter_index = None

    def _err(message: str):
        return StreamingResponse(
            iter([
                f"event: error\ndata: {json.dumps({'message': message}, ensure_ascii=False)}\n\n",
                "event: done\ndata: {}\n\n",
            ]),
            media_type="text/event-stream",
        )

    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return _err("Login required")

    # 截断:before 取末尾,after 取开头(光标处上下文最相关)
    before = before[-_CONTINUE_BEFORE_CAP:]
    after = after[:_CONTINUE_AFTER_CAP]
    selection = selection[:_CONTINUE_SELECTION_CAP]

    # 严格 owner 鉴权(给了 script_id 才校验):既防滥用又给用量归属
    if script_id is not None:
        try:
            sid = int(script_id)
        except (TypeError, ValueError):
            return _err("Invalid script_id")
        try:
            from platform_app.db import connect, init_db
            from platform_app.perms import script_owned
            init_db()
            with connect() as db:
                owned = script_owned(db, sid, user_id)
        except Exception:
            return _err("Script ownership check failed; please try again later")
        if not owned:
            return _err("Not allowed to modify this script: only the original author can use AI continue/rewrite.")
        script_id = sid
    else:
        script_id = None

    # 阶段2:装配「相关设定」环境块 —— 续写/改写忠于该剧本既有世界书/人物/词条/时点,
    # 按 chapter_index 防剧透截断(空白剧本/未关联 script → 跳过,退化为纯局部续写)。失败不影响续写。
    environment = ""
    if script_id is not None:
        try:
            from console_assistant.editor_context import build_editor_environment
            _scan = "\n".join([before, selection, after]).strip()
            environment = build_editor_environment(script_id, _scan, chapter_index)
        except Exception:
            environment = ""

    # 模型解析:body 给了 api_id+model 就用;否则跟随「编辑器 AI 面板」选的模型(与右栏聊天同源);
    # 再否则回退到 editor.* 偏好 / agent.* / 用户首个可用模型 / 默认。
    if not api_id_in or not model_in:
        _ov_api, _ov_model = _editor_panel_model(user_id)
        api_id_in = api_id_in or _ov_api
        model_in = model_in or _ov_model
    try:
        from agents._harness import resolve_api_and_model
        api_id, model_real = resolve_api_and_model(
            user_id,
            api_pref_key="editor.api_id",
            model_pref_key="editor.model_real_name",
            api_id_override=api_id_in,
            model_override=model_in,
        )
    except Exception:
        return _err(
            "No usable model found. Configure and test a model under Settings -> API settings, then try again."
        )
    if not api_id or not model_real:
        return _err(
            "No usable model found. Configure and test a model under Settings -> API settings, then try again."
        )

    # 构造 backend(复用 GM 的 backend 抽象);纯文本流式只用 backend.stream(无工具)
    try:
        from agents.gm import GameMaster
        backend = GameMaster(
            api_id=str(api_id), model=str(model_real), user_id=user_id,
        )._backend
    except Exception as exc:
        from agents.provider_errors import classify_provider_error
        known = classify_provider_error(exc)
        return _err(known[1] if known else "Model backend initialization failed; check your API settings and try again.")

    system_prompt = _CONTINUE_SYSTEM_PROMPT
    user_prompt = _build_continue_user_prompt(
        before=before, after=after, selection=selection,
        instruction=instruction, mode=mode, environment=environment,
    )

    def _gen():
        try:
            for chunk in backend.stream(
                system_prompt,
                [{"role": "user", "content": user_prompt}],
                max_tokens=2000,
            ):
                if chunk:
                    yield f"event: token\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            import logging
            logging.getLogger("console_assistant").exception(
                "continue stream failed: %s", type(exc).__name__,
            )
            from agents.provider_errors import classify_provider_error
            known = classify_provider_error(exc)
            msg = known[1] if known else "AI continuation failed; please try again later."
            yield f"event: error\ndata: {json.dumps({'message': msg}, ensure_ascii=False)}\n\n"
        else:
            # 用量归属(失败静默,不影响流):scenario=assistant,归到 script_id
            try:
                usage = getattr(backend, "last_usage", None) or {}
                if usage and (usage.get("input_tokens") or usage.get("output_tokens")):
                    from platform_app.usage import record_usage
                    record_usage(
                        user_id=user_id,
                        save_id=None,
                        context_run_id=None,
                        api_id=str(getattr(backend, "api_id", None) or api_id),
                        model_real_name=str(getattr(backend, "model_name", None) or model_real),
                        usage=usage,
                        metadata={"kind": "editor_continue", "mode": mode,
                                  "script_id": script_id},
                        scenario="assistant",
                    )
            except Exception:
                pass
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")
