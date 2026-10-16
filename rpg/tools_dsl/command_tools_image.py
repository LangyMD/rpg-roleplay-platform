"""command_tools_image.py — Phase 1-C: generate_image 工具 + 确定性门控。

ToolSpec 语义：
  scope   = "save"         — 复用 save 级用户围栏（用户只能对自己存档发起生图）
  origins = llm_chat / autonomous_agent / ui_button / api_direct
            （不含 llm_set / mcp_call / console_assistant）

门控逻辑（确定性，不靠 LLM 自觉）：
  - chat_pipeline.py run_gm_phase 起点初始化 state.data["_turn_images_generated"] = 0
  - executor 读 args["__call_origin__"]（调用方显式注入）：
      * ui_button / api_direct          → 不计数，直接入队
      * llm_chat / autonomous_agent（缺省 / 未注入） → 计数
  - 自主 origin 且 count >= 1 → 入 pending_writes，返回"待确认"
  - 自主 origin 且 count == 0 → count+1，入队，返回 {image_id, status}

强制性：即使 permission_mode=full_access，第 2 张也 pending（executor 主动入队，
  绕过 _write_path_allowed 的自动放行）。

注册：由 register_image_tools() 调用，在 command_tools_register.ensure_registered 末尾追加。
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

log = logging.getLogger(__name__)

# ── 自主 origin 集合（计数 / 门控）────────────────────────────────────────
_AUTONOMOUS_ORIGINS: frozenset[str] = frozenset({"llm_chat", "autonomous_agent"})

# ── 不计数 origin 集合（用户主动触发 = 隐式审批）──────────────────────────
_UNRESTRICTED_ORIGINS: frozenset[str] = frozenset({"ui_button", "api_direct"})


# ── config_card pending_question 写入器 ─────────────────────────────────────
# 前端 ConfirmStrip / 阻塞弹窗据 kind=="config_card" 渲染「模型/Key 配置引导卡」。
# 写入路径与 ask_player_choice 完全一致(state.data["permissions"]["pending_questions"]),
# 故无需任何额外的前端传输改动 —— 同一份 permissions 随回合 done/status state 下发。

def append_config_card(
    state: Any,
    *,
    capability: str,
    mode: str,
    model: str = "",
    api_id: str = "",
    hard: bool = False,
    question: str,
    options: list[str] | None = None,
) -> str:
    """向玩家弹一张「配置引导卡」(config_card pending_question)。

    返回写入的卡 id(cfg_<token>)。调用方据自身语义返回面向用户的文案。

    复用 ask_player_choice 的 id/turn/state 习惯:
      id   = "cfg_" + token_urlsafe(8)
      turn = state.data.get("turn", 0)
      写入 state.data["permissions"]["pending_questions"]。
    """
    permissions: dict[str, Any] = state.data.setdefault("permissions", {})
    pending: list = permissions.setdefault("pending_questions", [])
    # 去重:同 capability 已有未应答的 config_card → 跳过,不堆叠/不重弹。
    for _q in pending:
        if (
            isinstance(_q, dict)
            and _q.get("kind") == "config_card"
            and _q.get("capability") == capability
            and not _q.get("answered")
        ):
            existing_id = str(_q.get("id") or "")
            log.info(
                "[config_card] dedup skip capability=%s mode=%s (existing cid=%s)",
                capability, mode, existing_id,
            )
            return existing_id
    cid = f"cfg_{secrets.token_urlsafe(8)}"
    card: dict[str, Any] = {
        "id": cid,
        "kind": "config_card",
        "capability": capability,
        "mode": mode,
        "model": model or "",
        "api_id": api_id or "",
        "hard": bool(hard),
        "question": question,
        "options": [str(o) for o in (options or [])],
        "source": "agent:config_card",
        "turn": state.data.get("turn", 0),
    }
    pending.append(card)
    permissions["pending_questions"] = pending[-32:]  # 上限防膨胀(与 pending_writes 一致)
    log.info(
        "[config_card] appended cid=%s capability=%s mode=%s hard=%s model=%s api_id=%s",
        cid, capability, mode, hard, model, api_id,
    )
    return cid


# ── executor ──────────────────────────────────────────────────────────────

def _execute_generate_image(state: Any, args: dict[str, Any]) -> str | dict[str, Any]:
    """generate_image save 级 executor。

    origin 解析：
      args["__call_origin__"] 由调用方（API 端点 / ui_button handler）显式注入。
      LLM 生成的 tool_use args 不会包含此字段 → 默认为 "llm_chat"（触发计数门控）。
    """
    from platform_app.image_jobs import enqueue_image_generation

    prompt: str = str(args.get("prompt") or "").strip()
    if not prompt:
        return "Failed: prompt must not be empty"

    kind: str = str(args.get("kind") or "chat").strip()
    size: str | None = args.get("size") or None
    api_id: str | None = args.get("api_id") or None
    model: str | None = args.get("model") or None
    origin: str = str(args.get("__call_origin__") or "llm_chat")

    # ── 用户 ID：save 级 executor 签名是 (state, args)，user_id 不直传。
    # dispatcher 已将 env.save_id 无条件注入 args["save_id"]（覆盖 LLM 传值）。
    # 从 game_saves 表用 save_id 反查 user_id — 单次 DB 点查，仅在执行生图时触发。
    user_id: int = 0
    save_id_raw = args.get("save_id")
    if save_id_raw is not None:
        try:
            from platform_app.db import connect, init_db
            init_db()
            with connect() as _db:
                _row = _db.execute(
                    "SELECT user_id FROM game_saves WHERE id = %s",
                    (int(save_id_raw),),
                ).fetchone()
            if _row:
                user_id = int(_row["user_id"])
        except Exception as _uid_exc:
            log.warning("[image_gate] user_id lookup failed save_id=%s: %s", save_id_raw, _uid_exc)
    if not user_id:
        return "Failed: cannot determine user_id (save_id=%s); image generation aborted" % save_id_raw

    extra: dict[str, Any] = {}
    if size:
        extra["size"] = size
    ref: str | None = args.get("ref") or None
    if ref:
        extra["ref"] = ref

    # ── 入队前·生图模型配置门控(确定性,先于一切门控/入队)────────────────────
    # 只对自主 origin(llm_chat / autonomous_agent)做引导:用户主动触发(ui_button /
    # api_direct)视为已知自己在干什么,不弹卡、直接走原逻辑。
    if origin in _AUTONOMOUS_ORIGINS:
        from core.llm_backend import (
            _model_in_catalog,
            first_user_model,
            resolve_preferred_model,
        )
        # (a) LLM 显式指定了模型,但该模型不在用户 catalog → 阻塞式配置卡,不入队。
        if model and not _model_in_catalog(user_id, model):
            append_config_card(
                state,
                capability="image",
                mode="model_not_configured",
                model=model,
                api_id=api_id or "",
                hard=True,
                question=(
                    f"The image model '{model}' you want to use is not configured in your account yet. "
                    f"Pick an existing model or add an API key for it."
                ),
            )
            return f"[Image generation paused] Model '{model}' is not configured; the model configuration prompt has been shown."
        # (b) 未指定模型,且用户从未设默认生图模型 → 询问 / 缺 Key 引导,不入队。
        if not model and resolve_preferred_model(user_id, "image_gen.model_real_name") is None:
            default = first_user_model(user_id)
            if default:
                _api, _model = default
                append_config_card(
                    state,
                    capability="image",
                    mode="ask_default",
                    model=_model,
                    api_id=_api,
                    hard=False,
                    question=f"You haven't set a default image model yet. Generate with the detected '{_model}'?",
                    options=[f"Generate with {_model}", "Open model settings"],
                )
                return (
                    f"[Image generation awaiting confirmation] No default image model is set yet; "
                    f"asked the user whether to use the detected '{_model}'."
                )
            # 完全没有可用凭证 → 缺 Key 引导卡(非阻塞),不入队。
            append_config_card(
                state,
                capability="image",
                mode="missing_key",
                hard=False,
                question="You haven't configured an API key for an image model yet. Set one up and you can generate images.",
            )
            return "[Image generation not configured] The user has no API key for an image model yet; the setup guide has been shown, and images can be generated once it is configured."

    # ── 确定性门控 ─────────────────────────────────────────────────────────
    if origin in _AUTONOMOUS_ORIGINS:
        count: int = int(state.data.get("_turn_images_generated") or 0)
        if count >= 1:
            # 第 2 张及以上：入 pending_writes，不生图
            pw_id = secrets.token_urlsafe(8)
            permissions: dict[str, Any] = state.data.setdefault("permissions", {})
            pending: list = permissions.setdefault("pending_writes", [])
            pending.append({
                "id": pw_id,
                "path": "generate_image",
                "value": {
                    "prompt": prompt,
                    "kind": kind,
                    "api_id": api_id,
                    "model": model,
                    "extra": extra,
                    "user_id": user_id,
                    # 审批时以 api_direct 执行（视为玩家已手动审批）
                    "__approved_origin__": "api_direct",
                },
                "source": "gm:image",
                "reason": f"Image #{count + 1} this turn needs the player's confirmation before it is generated",
            })
            permissions["pending_writes"] = pending[-32:]  # 上限防膨胀
            log.info(
                "[image_gate] 第 %d 张图 pending user_id=%s pw_id=%s",
                count + 1, user_id, pw_id,
            )
            return (
                f"[Image generation gate] {count} image(s) already generated this turn; image #{count + 1} was added to the review queue "
                f"(id={pw_id}) and will run once the player confirms. prompt={prompt!r}"
            )
        # count == 0：自主调用第 1 张，计数后入队
        state.data["_turn_images_generated"] = count + 1

    # ── save_id 透传：dispatcher 已把 env.save_id 注入 args["save_id"]（覆盖 LLM 传值）
    # user_id 查询时已用过 save_id_raw；直接复用，转为 str 传给 enqueue。
    enqueue_save_id: str | None = str(save_id_raw) if save_id_raw is not None else None

    # ── 反馈#74:聊天内生图记录所属 assistant 消息索引,刷新后据此确定性还原(不再靠前端
    # localStorage + 有竞态的 SSE 映射)。本回合 user+assistant 由 record_turn 在回合末才追加,
    # 故此刻 state.history 仅含既往回合;本回合 assistant 的未来索引 = len(history)+1。
    _msg_index: int | None = None
    if kind == "chat":
        try:
            _hist = (getattr(state, "data", {}) or {}).get("history") or []
            _msg_index = len(_hist) + 1
        except Exception:
            _msg_index = None

    # ── 入队 ──────────────────────────────────────────────────────────────
    try:
        result = enqueue_image_generation(
            user_id,
            prompt,
            kind,
            api_id=api_id,
            model=model,
            origin=origin,
            extra=extra if extra else None,
            save_id=enqueue_save_id,
            message_index=_msg_index,
        )
        # 每日配额超限
        if result.get("error") == "quota_exceeded":
            log.warning(
                "[image_gate] quota_exceeded user=%s save_id=%s",
                user_id, enqueue_save_id,
            )
            return "Image generation failed (quota): today's image generation limit has been reached; try again tomorrow."

        image_id = result.get("image_id")
        log.info(
            "[image_jobs] generate_image enqueued image_id=%s user=%s kind=%s origin=%s save_id=%s",
            image_id, user_id, kind, origin, enqueue_save_id,
        )
        # 闭环(用户:生图后 LLM 不知道好没好)——LLM 自主路径上【确定性】等真实结果,把成功/失败
        # 回灌进 agentic 工具循环(不靠模型自己去轮询=不违背 harness 确定性铁律);手动路径
        # (ui_button/api_direct)仍即时返回回执,前端走 SSE 浮窗,不阻塞用户。
        if image_id and origin in _AUTONOMOUS_ORIGINS:
            from platform_app.image_jobs import wait_for_image
            _r = wait_for_image(int(image_id))
            _st = _r.get("status")
            if _st == "done":
                return f"Image generated (image_id={image_id}): the image was inserted into this turn's conversation; you can continue the narration with it in mind."
            if _st == "failed":
                return f"Image generation failed (image_id={image_id}): {_r.get('error') or 'unknown error'}. Adjust the prompt and retry, or tell the user honestly."
            if _st == "cancelled":
                return f"Image generation was cancelled (image_id={image_id})."
            return f"The image is still generating in the background (image_id={image_id}) and will appear in the conversation automatically later; carry on with this turn, no need to wait."
        return f"Image generation queued: image_id={image_id}, status=pending. The URL is pushed over SSE once it is done."
    except Exception as exc:
        log.exception("[image_jobs] enqueue_image_generation failed")
        return f"Failed: error while queueing image generation - {exc}"


# ── ToolSpec 工厂 ─────────────────────────────────────────────────────────

def _make_generate_image_spec():
    """返回 generate_image ToolSpec。延迟导入避免循环。"""
    from tools_dsl.command_dispatcher import ToolSpec

    return ToolSpec(
        name="generate_image",
        description=(
            "Generate an image asynchronously. Returns an image_id immediately after submission; the URL is pushed over SSE once the image is done."
            "\nAutonomous calls are limited to 1 image per turn; from the 2nd image on, the player must approve before it runs."
            "\nui_button / api_direct origins are not subject to the per-turn limit (a user-initiated trigger counts as approved)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text prompt for the image (required)",
                },
                "kind": {
                    "type": "string",
                    "enum": ["cover", "avatar", "card", "chat", "game", "persona"],
                    "description": (
                        "Image purpose: cover = script cover, avatar = user/character avatar, "
                        "card = character card portrait, chat = chat illustration, game = game scene, persona = persona image"
                    ),
                    "default": "chat",
                },
                "size": {
                    "type": "string",
                    "description": "Image size (provider-specific, e.g. '1024x1024'). If omitted, the provider decides.",
                },
                "api_id": {
                    "type": "string",
                    "description": "Image provider (doubao / dashscope / openai / vertex_ai). If omitted, falls back to the user's preference.",
                },
                "model": {
                    "type": "string",
                    "description": "Specific model name (e.g. 'doubao-seedream-4-x'). If omitted, the provider decides.",
                },
                "ref": {
                    "type": "string",
                    "description": "Optional related ID (e.g. card_id / save_id), only for record-keeping; does not affect generation.",
                },
            },
            "required": ["prompt"],
        },
        executor=_execute_generate_image,
        scope="save",
        origins=frozenset({
            "llm_chat",
            "autonomous_agent",
            "ui_button",
            "api_direct",
        }),
        destructive=False,
        intent_keywords=("生图", "画图", "插画", "封面", "头像", "立绘",
                         "image", "draw", "illustration", "cover", "avatar", "portrait"),
        side_effect_topics=(),  # 生图完成由 worker SSE 推送，不走 tool side_effect
        input_examples=(
            {"prompt": "A red-haired mage standing in an ancient library", "kind": "chat"},
            {"prompt": "An abandoned castle at sunset, epic fantasy style", "kind": "cover"},
        ),
    )


# ── 注册入口 ──────────────────────────────────────────────────────────────

def register_image_tools() -> None:
    """注册 generate_image 工具到全局 registry。幂等（二次注册静默跳过）。"""
    from tools_dsl.command_dispatcher import get_registry
    registry = get_registry()
    spec = _make_generate_image_spec()
    if not registry.has(spec.name):
        registry.register(spec)
        log.info("[command_tools_image] registered tool: %s", spec.name)
