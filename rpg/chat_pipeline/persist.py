"""Phase 5:落档 record_turn + save + DB + done。拆包自 chat_pipeline.py,行为零变化。"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from state import strip_json_state_ops, strip_leaked_scaffold, strip_meta_tool_preamble

from ._common import (
    _TOOL_MARKUP_FINISH_REASONS,
    PipelineContext,
    SSEEvent,
    _content_policy_advice,
    _gm_mode_of,
    _is_content_filter_reason,
    _last_usage_of,
    _norm_finish_reason,
    log,
)

# 空回合兜底文案:分诊本身出异常时才用(分诊是纯函数,正常走不到)。
_EMPTY_FALLBACK_MESSAGE = "The model didn't write any story text this turn. Please try again."

# 沉浸感确定性兜底(用户头号反馈):结尾"旁白向玩家显式提问下一步"的句子。中英两套,各自只命中
# 明确的决策反问,且必须是旁白行(不在引号内,绝不动角色台词)。
_TRAILING_Q_ZH = re.compile(
    r"(你|您)[^。！？\n]{0,16}(接下来|下一步|打算|准备|会|想|要不要|是否|如何|怎么)"
    r"[^。\n]{0,18}(做|办|应对|行动|选择|决定|应付)?[?？]\s*$"
)
_TRAILING_PLEAD_ZH = re.compile(r"(请|轮到|该)\s*(你|玩家)[^。\n]{0,10}(决定|选择|定夺|行动|出招)")
_TRAILING_Q_EN = re.compile(
    r"^(?:\W*)(?:(?:so|now|then|well)\s*,?\s*)?"
    r"(?:(?:what|how)\s+(?:do|will|would|should|shall|are)\s+you\s+(?:going\s+to\s+)?"
    r"(?:do|respond|react|proceed|handle|choose|decide|reply|answer|play)\b"
    r"|what(?:'s|\s+is)\s+your\s+(?:next\s+)?(?:move|call|choice|decision|plan)\b)"
    r"[^?\n]{0,40}\?\W*$",
    re.IGNORECASE,
)
_TRAILING_PLEAD_EN = re.compile(   # 整行即这句话才算(锚定首尾),避免误伤叙述句
    r"^\W*(?:(?:so|now|then|well)\s*,?\s*)?"
    r"(?:(?:it'?s|it\s+is)\s+(?:now\s+)?your\s+(?:move|turn|call|choice)"
    r"|the\s+(?:choice|decision|next\s+move)\s+is\s+(?:now\s+)?yours"
    r"|(?:the\s+rest\s+is\s+)?(?:over|up)\s+to\s+you)\W*$",
    re.IGNORECASE,
)
_QUOTE_CHARS_ZH = ("「", "」", "“", "”", "‘", "’", "\"", "『", "』")
# 英文行里 ’ 常是撇号(What’s),不能当引号;只认双引号类。
_QUOTE_CHARS_EN = ("「", "」", "“", "”", "\"", "『", "』")


def _is_trailing_decision_prompt(line: str) -> bool:
    """一行是否为旁白向玩家显式提问下一步(中/英)。纯函数。"""
    s = (line or "").strip()
    if not s:
        return False
    if (not any(c in s for c in _QUOTE_CHARS_ZH)) and len(s) <= 60 and (
            _TRAILING_Q_ZH.search(s) or _TRAILING_PLEAD_ZH.search(s)):
        return True
    norm = s.replace("\u2019", "'")
    if (not any(c in s for c in _QUOTE_CHARS_EN)) and len(s) <= 120 and (
            _TRAILING_Q_EN.search(norm) or _TRAILING_PLEAD_EN.search(norm)):
        return True
    return False


def _strip_trailing_decision_prompts(text: str) -> str:
    """剥掉结尾连续的「你接下来想怎么做?」/ "What do you do?" 类旁白问句;不会把整段删空。"""
    lines = (text or "").rstrip().split("\n")
    changed = False
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if _is_trailing_decision_prompt(last):
            lines.pop()
            changed = True
            continue
        break
    if changed:
        new = "\n".join(lines).rstrip()
        if new:  # 不要把整段删空(防极端情况)
            return new
    return text


def _as_int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _empty_turn_diagnosis(
    ctx: PipelineContext, raw_len: int, *, regex_emptied: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    """空回合(清洗后没有正文)的确定性分诊 → (reason, 给玩家的文案, 证据 facts)。

    只读现成的确定性信号,不猜正文:
      · ctx.gm._backend.last_usage 的 finish_reason / output_tokens / reasoning_tokens / max_tokens
        (与 _stop_reason_notice 共用 _last_usage_of;每回合入口已清零,读到的是本回合的)
      · state.data 的 _turn_reasoning(思考流)/ _turn_tool_ops(工具调用),本回合 Phase 4 累积
      · ctx.turn_tool_errors(工具调用标记解析失败 / DSML 解析出 0 个调用)
    regex_emptied:清洗到输出正则之前还有正文、被玩家自己的输出正则整段换空了(stripped_to_empty 的
    特例,单列 output_regex_emptied —— 这种情况重试没用,得去改正则)。
    优先级自上而下,先命中先返回:
      output_regex_emptied > stripped_to_empty > reasoning_exhausted > length > content_filter > tool_markup_unparsed
      > tool_only > reasoning_only > upstream_empty
    无工具路径(stream())不发思考事件、部分服务也不回传 reasoning_tokens,所以 length 且看不到
    思考信号时文案仍点明「多半是思考占满」。
    """
    lu = _last_usage_of(ctx)
    state_data = getattr(getattr(ctx, "state", None), "data", None) or {}
    try:
        reasoning_chars = sum(len(str(x or "")) for x in (state_data.get("_turn_reasoning") or []))
    except Exception:
        reasoning_chars = 0
    try:
        tool_count = len(state_data.get("_turn_tool_ops") or [])
    except Exception:
        tool_count = 0
    tool_errors = len(getattr(ctx, "turn_tool_errors", None) or [])
    fr = _norm_finish_reason(lu.get("finish_reason"))
    out_tokens = _as_int(lu.get("output_tokens"))
    reasoning_tokens = _as_int(lu.get("reasoning_tokens"))
    max_tokens = _as_int(lu.get("max_tokens")) or _as_int(getattr(ctx, "gm_max_tokens", 0))
    try:
        gm = getattr(ctx, "gm", None)
    except Exception:
        gm = None
    facts: dict[str, Any] = {
        "api_id": str(getattr(gm, "api_id", "") or ""),
        "model": str(getattr(getattr(gm, "_backend", None), "model_name", "") or ""),
        "finish_reason": str(lu.get("finish_reason") or ""),
        "out_tokens": out_tokens,
        "reasoning_tokens": reasoning_tokens,
        "max_tokens": max_tokens,
        "reasoning_chars": reasoning_chars,
        "tool_count": tool_count,
        "tool_errors": tool_errors,
        "raw_len": int(raw_len or 0),
    }
    has_reasoning = reasoning_tokens > 0 or reasoning_chars > 0
    cap = f" (limit {max_tokens} tokens)" if max_tokens else ""
    # 不引用具体控件名:设置页叫「最大生成 token」、酒馆参数抽屉叫「最大输出 Tokens」,两处都在「模型参数」下。
    raise_cap = (" You can raise the maximum output tokens under Model parameters, or lower the reasoning effort / "
                 "switch to a model without thinking, then try again.")

    if raw_len > 0 and regex_emptied:
        return ("output_regex_emptied",
                "The model wrote story text, but an output regex script you enabled replaced all of it with nothing. "
                "Retrying will do the same; please check that script's find and replace rules.", facts)
    if raw_len > 0:
        return ("stripped_to_empty",
                "This turn the model only output state instructions or internal markers, with no story text. "
                "Simply trying again usually works.", facts)
    if fr == "length" and has_reasoning:
        used = f" (about {reasoning_tokens} tokens of thinking)" if reasoning_tokens else ""
        return ("reasoning_exhausted",
                f"The model spent this turn's whole output budget{cap} on thinking{used} and hit the limit "
                "before it started writing the story." + raise_cap,
                facts)
    if fr == "length":
        return ("length",
                f"The model used up this turn's output budget{cap} without writing a single word of story text; "
                "most likely its thinking filled the budget (some services don't send the thinking back, so it isn't shown here)."
                + raise_cap,
                facts)
    if _is_content_filter_reason(fr):
        return ("content_filter",
                "This turn was blocked by the model's content policy, so no story text was generated. "
                + _content_policy_advice(), facts)
    if tool_errors > 0 or fr in _TOOL_MARKUP_FINISH_REASONS:
        return ("tool_markup_unparsed",
                "The model tried to call a tool, but the call it wrote could not be parsed, so no story text was written this turn. "
                "You can just retry; if it keeps happening, try another model or provider.", facts)
    if tool_count > 0:
        return ("tool_only",
                f"This turn the model only called tools ({tool_count} times) and didn't go on to write the story. "
                "You can just retry.", facts)
    if has_reasoning:
        return ("reasoning_only",
                "This turn the model only output its thinking, with no story text. You can just retry; if it keeps happening, "
                "lower the reasoning effort under Model parameters in Settings, or switch models.", facts)
    return ("upstream_empty",
            "The model service returned nothing this turn: no story text, no thinking and no tool calls. Most likely the relay "
            "or the provider had a temporary problem; please try again, and switch providers if it keeps happening.", facts)


async def persist_turn_phase(
    ctx: PipelineContext,
    *,
    payload_fn: Callable[[dict[str, Any] | None], dict[str, Any]],
    persist_chat_turn: Callable[..., None],
    build_usage_payload: Callable[..., dict[str, Any] | None],
) -> AsyncIterator[SSEEvent]:
    """Phase 5: 落档 (chat turn / runtime turn / DB messages) + 发 usage / updates / done。"""
    state = ctx.state
    api_user = ctx.api_user
    message_for_model = ctx.message_for_model
    response = ctx.response
    bundle = ctx.bundle
    gm = ctx.gm
    updates = getattr(ctx, "_updates", []) or []

    visible_response = strip_json_state_ops(response)
    # 确定性兜底:剥掉 GM 在 native tool_use 前泄漏进正文的英文"工具预告"元叙述
    # (例:"Let me mark the anchors that have been satisfied...")。不依赖 GM 听提示词。
    visible_response = strip_meta_tool_preamble(visible_response)
    # 确定性兜底(反馈 #77):弱模型把检索/世界线脚手架块(=== 时间线检索锚点 === 等)+ 内部推理
    # 直接吐进正文 → 整块剥掉。这些 header 是后端注入的隐形上下文,正常叙事永不产出,零误伤。
    visible_response = strip_leaked_scaffold(visible_response)

    # 确定性玩家选项兜底(用户反馈"选项有时不弹"):整个选择机制原本只在 GM 主动调 ask_player_choice
    # 时才弹 —— GM 常把选项直接写进正文 markdown 列表却不调工具 → 前端无 chips。这里【确定性】解析
    # 正文结尾的选项列表(≥2 项),把它移出正文、合成一个 pending_question 走选择组件。不靠 GM 听话。
    # 仅当本回合 GM 没有已给出结构化选择(避免重复)时才兜底;过期清理已在回合开头跑过,故 pending
    # 里只剩本回合的。放在沉浸感剥句之前:先把列表抽走,残留的"你想怎么做?"问句再被下面的剥句清掉。
    _auto_choice_opts: list[str] = []
    try:
        from state.parsers import _extract_trailing_markdown_options
        _existing_pqs = ((state.data.get("permissions") or {}).get("pending_questions") or [])
        _has_choice = any((q.get("options") or q.get("choices")) for q in _existing_pqs)
        if not _has_choice:
            _body, _opts = _extract_trailing_markdown_options(visible_response)
            if len(_opts) >= 2:
                visible_response = _body
                _auto_choice_opts = _opts
    except Exception:
        pass

    # 沉浸感确定性兜底(用户头号反馈):剥掉结尾"旁白向玩家显式提问下一步"的句子
    # ——只命中明确的决策反问(你接下来想怎么做 / 你打算如何应对 / 请玩家决定 等),
    # 且必须是旁白行(不在引号内,绝不动角色台词)。不依赖 GM 听提示词。
    try:
        visible_response = _strip_trailing_decision_prompts(visible_response)
    except Exception:
        pass

    # 落实上面确定性解析出的玩家选项(列表已移出正文)→ 合成选择组件。source 用 "gm:" 前缀,
    # 使其与开场的 gm:opening_options 一样被 expire_stale_gm_questions 视为系统来源、下回合自动清理
    # (system_sources 含 "gm";"auto" 不在其中会导致 chips 永不过期变残留)。
    if _auto_choice_opts:
        try:
            state.add_pending_question("What do you do?", source="gm:auto_choice", options=_auto_choice_opts)
        except Exception:
            pass

    # 反馈#93:用户自定义输出正则(SillyTavern regex,输出/显示作用域)—— 对清洗后的可见正文做确定性
    # find/replace。安全在 state.regex_scripts 内(每条脚本线程超时 + try/except,异常/超时跳过,绝不断轮)。
    _before_output_regex = visible_response
    try:
        from state.regex_scripts import apply_output_regex
        _rx_uid = int(api_user.get("id")) if api_user and api_user.get("id") else 0
        if _rx_uid:
            visible_response = apply_output_regex(visible_response, _rx_uid)
    except Exception:
        pass

    # task 128: GM 返回空时不写 history (避免出现"GM 主代理"标题但内容空的诡异消息),
    # 改为 yield error 让用户清楚知道并能重试。常见原因:
    #   · LLM 触发 safety filter (Gemini 对暴力/儿童虐待场景敏感)
    #   · backend stream 提前 EOF / 超时
    #   · 工具循环耗尽但没产出 text block
    # task 31/27: /set 命令已在 Phase 1 持久化 (directive_updates 非空),
    # 此时 GM 返空是正常的 — 不应 error，直接 done。
    if not visible_response.strip():
        if ctx.directive_updates:
            # /set 已落盘，GM 空响应无需报错
            yield ("done", {"status": payload_fn(api_user), "interrupted": False, "empty": True})
        elif ctx.tavern_character_set:
            # 酒馆角色卡工具成功但 first_mes 为空 — 正常干净结束,不报 error
            yield ("done", {"status": payload_fn(api_user), "interrupted": False, "empty": True})
        else:
            # 确定性分诊:此前这里是写死的「可能触发了安全过滤 / 上下文出错,换个说法」,而最常见的
            # 成因(思考模型把单轮输出上限吃光)换说法根本没用;现场信号也一条没留。
            try:
                # raw_len 按去空白后算:原始输出只有空白 = 上游确实没给东西,不该判成「清洗后为空」。
                _reason, _msg, _facts = _empty_turn_diagnosis(
                    ctx, len((response or "").strip()),
                    regex_emptied=bool((_before_output_regex or "").strip()),
                )
            except Exception:
                _reason, _msg, _facts = "unknown", _EMPTY_FALLBACK_MESSAGE, {}
            _mode = _gm_mode_of(state)
            _pid = ctx.persist_user_id or ctx.early_persist_user_id
            _sid = ctx.active_save_id or ctx.early_active_save_id
            log.warning(
                "[chat] WARN: GM 返回空响应 reason=%s api_id=%s model=%s finish_reason=%s out_tokens=%s "
                "reasoning_tokens=%s max_tokens=%s reasoning_chars=%s tools=%s tool_errors=%s mode=%s "
                "len(raw)=%s user_msg='%s' save_id=%s",
                _reason, _facts.get("api_id"), _facts.get("model"), _facts.get("finish_reason"),
                _facts.get("out_tokens"), _facts.get("reasoning_tokens"), _facts.get("max_tokens"),
                _facts.get("reasoning_chars"), _facts.get("tool_count"), _facts.get("tool_errors"),
                _mode or "?", len(response or ""), message_for_model[:80], _sid,
            )
            # 证据落库:空回合也实际花了玩家的输入 + 思考 token。写一条 chat token_usage,metadata 带
            # empty_response/reason,生产上能直接按 reason 统计成因分布。只在游戏台发 usage SSE(footer
            # 显示本轮用量);酒馆页把 usage 挂在「最后一条消息」下面,空回合那条是上一回合的 GM 回复,
            # 会把这轮的用量错挂过去,所以酒馆只落库不发。
            _usage = None
            try:
                _usage = build_usage_payload(
                    api_user, gm, bundle, message_for_model, _pid, _sid, ctx.context_run_id,
                    extra_metadata={"empty_response": True, "reason": _reason},
                )
            except Exception:
                _usage = None
            if _usage and _mode != "tavern_gm":
                yield ("usage", _usage)
            yield ("error", {"message": _msg, "kind": "empty_response", "reason": _reason})
            yield ("done", {"status": payload_fn(api_user), "interrupted": False, "empty": True})
        return
    persist_chat_turn(
        api_user, state, message_for_model, visible_response,
        persist_user_id=ctx.persist_user_id, active_save_id=ctx.active_save_id,
    )
    # 渠道健康门控(韧性战役):本回合走到这里 = GM 主响应流式成功完成,清零该
    # (user_id, api_id) 的被动失败计数,别让早前的暂时性 502/限流继续把渠道钉在 degraded。
    try:
        import model_probe
        model_probe.note_channel_success(
            getattr(gm, "api_id", ""), user_id=(api_user or {}).get("id"),
        )
    except Exception:
        pass
    usage_payload = build_usage_payload(
        api_user, gm, bundle, message_for_model,
        ctx.persist_user_id, ctx.active_save_id, ctx.context_run_id,
    )
    if usage_payload:
        yield ("usage", usage_payload)
    # 跨渠道 fallback 发生过 → 玩家必须知情(模型质量可能有差异),附进本回合 updates。
    if getattr(ctx, "fallback_note", ""):
        updates = list(updates or []) + [str(ctx.fallback_note)]
    yield ("updates", {"items": updates})
    yield ("done", {"status": payload_fn(api_user), "interrupted": False, "usage": usage_payload})
