"""
context_agent.py — Demand Resolver + ContextProvider 调度器。

重构后职责仅两条：
  1. Demand Resolver — 把玩家自然语言翻成结构化 Demand（intent / constraints /
     rule_candidate_actions / retrieval_query / clarifying_question 等）。
  2. 按当前 session 的 ContentPack manifest，调度 ContextProvider 收集
     ContextContribution，再交给 build_context_bundle 组装 prompt。

context_agent 本身不再硬编码"小说时间线锚点 / ChapterFact 检索 / 模组房间
等"任何具体数据源。换 ContentPack 不需要改 context_agent，只要在 manifest 里
声明 context_providers 列表。
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from context_engine import build_context_bundle
from context_providers import (
    Demand,
    ProviderServices,
    resolve_content_pack,
    run_providers,
)
from kb.recall import (
    retrieve_fn_compat,  # P5:统一召回 flag 门控包装(默认 off=委托 retrieve_context)
)
from retrieval import retrieve_context  # noqa: F401 (retrieve_fn_compat 内部委托;保留以兼容)
from timeline_index import timeline_filter_for_label
from timeline_state import (
    detect_time_directives,
    is_recall_framing,
    looks_like_time_value,
    mentions_time_without_intent,
)

log = logging.getLogger(__name__)

# curator harness 调用的瞬时错误特征(命中则重试一次再降级):超时/连接/限流/网关。
_TRANSIENT_MARKERS = (
    "timeout", "timed out", "temporarily", "connection", "reset", "econn",
    "429", "500", "502", "503", "504", "rate limit", "overloaded", "unavailable",
)


def _is_transient_err(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    m = str(exc).lower()
    return any(k in m for k in _TRANSIENT_MARKERS)

AGENT_PROMPT = """\
You are the Demand Resolver sub-agent. Your only job is to translate the player's natural-language input into
a structured "demand ledger" for this turn, which the system validates before feeding it to the main GM.

Boundaries: you **do not write prose, do not change state directly, do not advance the timeline, and do not make
decisions for the main GM** -- you only extract demands and draw up the context / retrieval plan.

Steps:
1. Parse the chapter, year, date, phase, location and character intent in the player's input.
2. If the player asks for a time jump, set timeline_target but do not advance it yourself; /set is a hard constraint handled against the current state.
3. Separate hard constraints (must be satisfied) from soft preferences (better satisfied, but negotiable).
4. List the candidate actions available this turn (narration / question / state write) so the main GM decides within that range.
5. Define acceptance: in which respects this turn's GM output counts as a success.
6. Assess your own confidence; when unsure, fill clarifying_question so the system can ask the player first.

You MUST return JSON (no markdown fences, no explanatory text):

{
  "intent": "the player's intent in one sentence",
  "active_goal": "what the player really wants to achieve this turn (the underlying intent, not the literal words)",
  "hard_constraints": ["constraints that must be satisfied (violating one means this turn failed)"],
  "soft_preferences": ["preferences that should be satisfied but are negotiable"],
  "target_entities": ["names of the characters / factions involved"],
  "target_location": "target location; empty if none",
  "target_time": "target time; empty if none",
  "timeline_target": "the target label if the player requests a time jump, otherwise an empty string",
  "retrieval_query": "a short query for retrieval",
  "retrieval_plan": {
    "must_include": ["facts that must enter the main GM's context"],
    "should_include": ["helpful but optional material"]
  },
  "candidate_actions": [
    "2-5 concrete things the GM can do this turn (e.g. 'narrate: <character> pushes open the door of <place> and the room is described' / 'ask: observe first or go straight in?' / 'write state: player.current_location=<place>'). Angle-bracket placeholders in the examples MUST be replaced with real names from this game; do not copy them"
  ],
  "rule_candidate_actions": [
    "(only when the current scene runs a 5E-compatible rules module) candidate actions that trigger system rules. Each has at least a kind field, e.g.:",
    "  {\"kind\":\"skill_check\",\"skill\":\"stealth\",\"target\":\"minecart_track\",\"dc_hint\":13,\"reason\":\"player says they sneak closer\"}",
    "  {\"kind\":\"attack\",\"target\":\"ash_skulker_1\",\"weapon\":\"shortsword\"}",
    "  {\"kind\":\"saving_throw\",\"ability\":\"con\",\"dc_hint\":12,\"reason\":\"poison_fog\"}",
    "  {\"kind\":\"investigate\",\"target\":\"collapsed_shaft\",\"skill\":\"investigation\",\"dc_hint\":12}",
    "  {\"kind\":\"move\",\"target\":\"rest_cavern\"}",
    "The GM **cannot roll dice itself**; if the intent is vague, leave the actions empty and let the GM ask or offer options."
  ],
  "acceptance": [
    "this turn's GM output succeeds if these conditions hold; each must be verifiable (e.g. 'the GM responds in the prose to the player's request to go to <target place>' / 'events of the source this game has not reached yet are not treated as having happened'). Only reference names, places and times that actually appear in this game's context"
  ],
  "risk_flags": ["risks that could cause misalignment (e.g. 'pending_jump awaiting confirmation; do not narrate into the future')"],
  "confidence": 0.85,
  "clarifying_question": "",
  "reason": "why you planned this turn this way (never shown to the player)"
}

confidence thresholds:
- >= 0.7: clear intent, call the main GM normally
- 0.5-0.7: ambiguous but workable; write the ambiguity into risk_flags
- < 0.5: unclear intent; record your doubt in clarifying_question -- the main GM will still go ahead with the most reasonable reading this turn (the pipeline no longer stops to wait; only genuinely mutually exclusive choices are put to the player by the main GM via a question op)

How to write clarifying_question: a direct closed question + 2-3 candidate answers.
E.g. (replace the placeholders with real names from this game): "Do you want <character> to watch from outside the door first, or push it open right away? (A) Watch (B) Push the door open (C) Back off"
"""


def run_context_agent(
    state,
    user_input: str,
    stop_requested: Callable[[], bool] | None = None,
    llm_curator: Callable[[str, str], str] | None = None,
    user_id: int | None = None,
    script_id: int | None = None,
    book_id: int | None = None,
    save_id: int | None = None,  # task 107E: 给 RuntimePhaseDigestProvider 用
    api_id_override: str | None = None,
    model_override: str | None = None,
    budget_chars: int | None = None,  # v1.82.0: 主 GM 模型窗口换算出的层预算;None = 不求解
) -> Generator[dict[str, Any], None, None]:
    """Demand Resolver + ContextProvider 调度。

    LLM 调用优先级(harness 适配):
    1. 显式传入 `llm_curator` 回调 → 使用回调(兼容老 caller / 测试 monkeypatch)
    2. 传入 `api_id_override`+`model_override` → 内部走 `_harness.call_agent_json`
       (provider 透明 + Anthropic 强 schema + 统一 retry 降级)
    3. 上述都没 → 本地确定性规则,curator_plan 仅含 directives 信息
    """
    stop_requested = stop_requested or (lambda: False)
    started = time.time()
    steps: list[dict[str, Any]] = []

    def step(phase: str, message: str, status: str = "running", **data: Any) -> dict[str, Any]:
        payload = {
            "phase": phase,
            "message": message,
            "status": status,
            "elapsed_ms": int((time.time() - started) * 1000),
            **data,
        }
        steps.append(payload)
        return {"type": "step", "step": payload}

    def stopped() -> bool:
        if not stop_requested():
            return False
        yield_step = step("aborted", "The player stopped the context sub-agent; the main GM will not be called this turn.", "stopped")
        steps[-1] = yield_step["step"]
        return True

    use_harness = (llm_curator is None) and bool(api_id_override or user_id)
    mode = (
        "llm_structured" if llm_curator
        else ("harness_structured" if use_harness else "local_fallback")
    )
    yield step(
        "prompt",
        f"Loading the context sub-agent prompt (mode: {mode}).",
        "done",
        prompt=AGENT_PROMPT,
        mode=mode,
        request_isolated=True,
        writes_chat_history=False,
    )
    if stopped():
        yield {"type": "stopped", "steps": steps}
        return

    is_set = _is_set_command(user_input)
    directives = [] if is_set else detect_time_directives(user_input or "")
    if is_set:
        yield step("intent", "Detected a /set override; building context from the user's hard constraints already written.", "done")
    elif directives:
        for directive in directives:
            state.request_time_jump(directive.target, directive.raw)
        yield step(
            "intent",
            f"Detected a timeline request: {directives[0].target}",
            "done",
            directives=[directive.__dict__ for directive in directives],
        )
    else:
        yield step("intent", "No explicit time jump found; keeping the currently locked timeline.", "done")
    if stopped():
        yield {"type": "stopped", "steps": steps}
        return

    curator_plan: dict[str, Any] = {}
    # 引导强度权威源 = game_sessions.worldline.steering_strength(与 retrieval.py:463-468 同源)。
    _steering_strength = "guided"
    if save_id:
        try:
            from platform_app.db import connect as _conn_ss
            with _conn_ss() as _db_ss:
                _row_ss = _db_ss.execute(
                    "select worldline from game_sessions where save_id=%s", (save_id,)
                ).fetchone()
                _wl_ss = (_row_ss or {}).get("worldline") if _row_ss else None
                if isinstance(_wl_ss, dict):
                    _steering_strength = _wl_ss.get("steering_strength") or "guided"
        except Exception:
            pass
    task_prompt_text = _curator_task_prompt(state, user_input, directives,
                                            steering_strength=_steering_strength)
    if llm_curator:
        yield step(
            "llm_curator",
            "Calling the LLM sub-agent to work out this turn's context needs.",
            "running",
            request_isolated=True,
            expected_output="json",
            shared_with_main_gm=False,
        )
        llm_text = _call_llm_curator(
            llm_curator,
            task_prompt_text,
            stop_requested,
        )
        if llm_text is None:
            yield {"type": "stopped", "steps": steps}
            return
        curator_plan = _parse_curator_json(llm_text)
        target = _normalize_timeline_target(curator_plan.get("timeline_target", ""))
        # LLM 子代理(便宜直连模型)也可能把回忆/闪回误判成跳跃(行者无疆实测)。门控:输入是回忆叙述
        # 或 target 不像时点(含人称从句)→ 不发起跳跃,与确定性 detect_time_directives 同口径。
        # v1.73.2 补第三条同口径闸:输入里的年份/章号是**叙述里顺带提到**的(既无跳跃动词、
        # 整条输入也不只是那个时点),确定性侧已判定不是指令,LLM 侧不许绕过它自己发起跳跃
        # ——否则修了确定性检测,子代理照样把「NPC 背景: 1968年…」读成跳转。
        if (target and not directives and not is_set
                and not is_recall_framing(user_input)
                and not mentions_time_without_intent(user_input)
                and looks_like_time_value(target)):
            state.request_time_jump(target, user_input)
        yield step(
            "llm_curator",
            curator_plan.get("intent") or "The LLM sub-agent has finished its context assessment.",
            "done",
            raw=llm_text,
            plan=curator_plan,
        )
    elif use_harness:
        yield step(
            "llm_curator",
            f"Calling the curator through the unified harness (api={api_id_override or 'auto'}, model={model_override or 'auto'}).",
            "running",
            request_isolated=True,
            expected_output="json",
            shared_with_main_gm=False,
            transport="agent_harness",
        )
        harness_err: dict = {}
        try:
            llm_text = _call_curator_via_harness(
                user_id=user_id,
                api_id_override=api_id_override,
                model_override=model_override,
                system_prompt=AGENT_PROMPT,
                user_prompt=task_prompt_text,
                stop_requested=stop_requested,
                err_sink=harness_err,
            )
        except _CuratorStopped:
            yield {"type": "stopped", "steps": steps}
            return
        if llm_text is None:
            # Option A:把真实原因(403/401/余额/限流…)明确告诉用户,不再静默「调用失败」。
            _emsg = harness_err.get("message")
            if _emsg:
                _notice = (f"Sub-agent call failed: {_emsg}"
                           f" (provider {harness_err.get('api')} · model {harness_err.get('model')})."
                           f" Falling back to local rules for this turn.")
            else:
                _notice = "Sub-agent call failed (network / timeout etc.); falling back to local rules for this turn."
            curator_plan = _local_fallback_plan(directives, user_input, reason=_notice)
            yield step(
                "llm_curator",
                _notice,
                "done",
                plan=curator_plan,
                fallback=True,
            )
        else:
            curator_plan = _parse_curator_json(llm_text)
            target = _normalize_timeline_target(curator_plan.get("timeline_target", ""))
            # 遗漏修复(审计 P2):harness 路径(所有 BYOK 主路径)漏了 llm_curator 分支已有的两道门 →
            # 玩家写「回想起…」等回忆叙述时会触发假时间跳跃(v1.26.4 只修了 llm_curator 分支)。对齐:
            # is_recall_framing 抑制回忆、looks_like_time_value 拒含人称从句的非时间值。
            if (target and not directives and not is_set
                    and not is_recall_framing(user_input) and looks_like_time_value(target)):
                state.request_time_jump(target, user_input)
            yield step(
                "llm_curator",
                curator_plan.get("intent") or "The LLM sub-agent has finished its context assessment.",
                "done",
                raw=llm_text,
                plan=curator_plan,
            )
    else:
        curator_plan = _local_fallback_plan(directives, user_input,
                                            reason="No llm_curator was passed and no api_id_override was given.")

    # 5E-compatible：当前为模组场景时，补一份本地关键词回退的 rule_candidate_actions。
    # LLM 已返回 rule_candidate_actions 时优先用它，否则用本地匹配确保规则层不会缺动作。
    scene = state.data.get("scene") or {}
    if scene.get("module_id"):
        try:
            from rules_bridge import suggest_rule_actions as _suggest_rule_actions
            local_actions = _suggest_rule_actions(user_input, state)
        except Exception:
            local_actions = []
        existing = curator_plan.get("rule_candidate_actions") or []
        if not existing:
            curator_plan["rule_candidate_actions"] = local_actions
        else:
            # 合并：以 (kind, skill, target) 为主键去重，LLM 优先
            seen = {(a.get("kind"), a.get("skill"), a.get("target")) for a in existing}
            for a in local_actions:
                key = (a.get("kind"), a.get("skill"), a.get("target"))
                if key not in seen:
                    existing.append(a)
                    seen.add(key)
            curator_plan["rule_candidate_actions"] = existing[:8]

    # ── ContentPack manifest 解析 ───────────────────────────────
    manifest = resolve_content_pack(state, script_id=script_id)
    yield step(
        "manifest",
        f"Resolved ContentPack: kind={manifest.get('kind')} · id={manifest.get('id')}",
        "done",
        manifest_kind=manifest.get("kind"),
        manifest_id=manifest.get("id"),
        context_providers=list(manifest.get("context_providers") or []),
        retrieval_policy=manifest.get("retrieval_policy"),
        gm_policy=manifest.get("gm_policy"),
    )
    if stopped():
        yield {"type": "stopped", "steps": steps}
        return

    # ── Demand：把 curator_plan 包成结构化 Demand ──────────────
    demand = _demand_from_curator_plan(curator_plan, user_input)

    # ── ContextProvider 调度 ────────────────────────────────────
    services = ProviderServices(
        user_id=user_id,
        script_id=script_id,
        book_id=book_id,
        save_id=save_id,  # task 107E
        retrieve_fn=retrieve_fn_compat,  # P5:flag off→retrieve_context;on→recall;shadow→双跑
        timeline_filter_fn=timeline_filter_for_label,
    )
    contributions, used_ids = run_providers(state, manifest, demand, services)

    # 每个 provider 一个 step
    for contrib in contributions:
        if contrib.applied:
            yield step(
                f"provider:{contrib.provider_id}",
                f"{contrib.provider_id} contributed {len(contrib.layers)} layers, {len(contrib.facts)} facts",
                "done",
                provider_id=contrib.provider_id,
                kind=contrib.kind,
                priority=contrib.priority,
                facts=contrib.facts[:6],
                tokens_estimate=contrib.tokens_estimate,
                debug=contrib.debug,
                warnings=contrib.warnings,
            )
        else:
            sk_msg = contrib.debug.get("skipped") or contrib.debug.get("error") or "skipped"
            yield step(
                f"provider:{contrib.provider_id}",
                f"{contrib.provider_id} skipped ({sk_msg})",
                "skipped",
                provider_id=contrib.provider_id,
                warnings=contrib.warnings,
                debug=contrib.debug,
            )
    if stopped():
        yield {"type": "stopped", "steps": steps}
        return

    # ── 组装 GM prompt ─────────────────────────────────────────
    # 把 contributions 透传给 build_context_bundle；同时保留旧 curator_plan
    # 字段做向后兼容（GM prompt 渲染层暂时还在读 curator_plan.candidate_actions）。
    # Novel retrieval contribution 的 layers 里有 retrieval text；如果存在，取出
    # 作为 retrieved_context 兼容 build_context_bundle 旧签名。
    retrieved_context = _pick_retrieval_text(contributions)
    bundle = build_context_bundle(
        state, user_input, retrieved_context,
        curator_plan=curator_plan,
        script_id=script_id, book_id=book_id,
        contributions=contributions,
        manifest=manifest,
        # v1.82.0: 预算来自**主 GM** 的模型窗口(不是 curator 的)——这份 bundle 进的是
        # 主 GM 的 prompt。拿不到窗口时 caller 传 None,求解跳过,行为与改动前一致。
        budget_chars=budget_chars,
    )
    cache = bundle["debug"].get("cache_plan", {})
    yield step(
        "assembly",
        "Main GM context manifest built; layers assembled from manifest + contributions.",
        "done",
        estimated_tokens=bundle["debug"].get("estimated_tokens", 0),
        layer_count=len(bundle["debug"].get("layers", [])),
        cache_plan=cache,
        active_content_pack=manifest.get("id"),
        providers_used=used_ids,
    )

    yield {
        "type": "result",
        "retrieved_context": retrieved_context,
        "bundle": bundle,
        "steps": steps,
        "agent_prompt": AGENT_PROMPT,
        "curator_plan": curator_plan,
        "active_content_pack": manifest,
        "providers_used": used_ids,
        "contributions": [c.to_dict() for c in contributions],
    }


def _resolve_need_retrieval(plan: dict[str, Any], user_input: str) -> bool:
    """Q Phase 3 司命 RAG 闸判定。**确定性优先**(遵守 harness 确定性铁律:不纯靠 LLM 遵守提示词):
    - 司命 LLM 显式给了 need_retrieval(bool/"false"/0)→ 信它(schema-enforced 的 Anthropic 最可靠)。
    - 弱模型(flash)常整字段省略 → 落确定性启发式:短输入 + 无目标实体 + 无目标地点 + 无时间跳转
      → 纯对话/情绪/简单互动,跳过检索;否则检索(宁可多检索不漏关键素材)。
    """
    raw = plan.get("need_retrieval")
    if raw is not None:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw != 0
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower() not in ("false", "0", "no", "否")
    # 司命没给(flash 常省)→ 确定性兜底。**只看玩家输入文本本身**,不看 curator 的
    # target_entities —— 实测弱模型会把在场 NPC 全填进 target_entities(即便玩家只是点头),
    # 那个信号被污染、不可用。改用输入文本的「提问/求设定」标记 + 长度。
    text = (user_input or "").strip()
    # 显式提问/求原著设定/剧情信号 → 必检索
    _LORE_MARK = ("?", "？", "为什么", "怎么", "如何", "是谁", "什么", "哪", "历史", "来历",
                  "由来", "背景", "设定", "原著", "讲讲", "讲述", "告诉我", "介绍", "规则",
                  "发生了", "之前", "当年", "据说", "传说", "典故")
    # English equivalents (matched on the lower-cased input padded with spaces → whole-word-ish)
    _LORE_MARK_EN = (" why ", " how ", " who is ", " who was ", " who are ", " what ", " where ",
                     " which ", " history", " background", " lore", " origin", " tell me",
                     " explain", " describe", " rules", " happened", " before ", " legend",
                     " rumor", " rumour", " the story of", " used to ")
    if any(m in text for m in _LORE_MARK):
        return True
    _low = f" {text.lower()} "
    if any(m in _low for m in _LORE_MARK_EN):
        return True
    # 去新地点 / 时间跳转 → 检索(这些字段污染少)
    if str(plan.get("target_location") or "").strip() or str(plan.get("timeline_target") or "").strip():
        return True
    # 短输入且无 lore 信号 → 纯对话/情绪/简单动作,跳过检索
    from core.token_estimate import is_cjk_text
    if (len(text) <= 18) if is_cjk_text(text) else (len(text.split()) <= 10):
        return False
    return True


def _demand_from_curator_plan(curator_plan: dict[str, Any], user_input: str) -> Demand:
    """把 LLM/本地 curator_plan dict 包成 Demand 结构体，供 providers 使用。"""
    plan = curator_plan or {}
    return Demand(
        player_intent=str(plan.get("intent") or "").strip() or (user_input or "")[:200],
        active_goal=str(plan.get("active_goal") or ""),
        hard_constraints=list(plan.get("hard_constraints") or []),
        soft_preferences=list(plan.get("soft_preferences") or []),
        target_entities=list(plan.get("target_entities") or []),
        target_location=str(plan.get("target_location") or ""),
        target_time=str(plan.get("target_time") or ""),
        timeline_target=str(plan.get("timeline_target") or ""),
        retrieval_query=_retrieval_query(user_input, plan),
        need_retrieval=_resolve_need_retrieval(plan, user_input),
        retrieval_needs={
            "must_include": list((plan.get("retrieval_plan") or {}).get("must_include")
                                  or plan.get("must_include") or []),
            "should_include": list((plan.get("retrieval_plan") or {}).get("should_include") or []),
        },
        rule_candidate_actions=list(plan.get("rule_candidate_actions") or []),
        risk_flags=list(plan.get("risk_flags") or []),
        confidence=float(plan.get("confidence", 1.0) or 1.0),
        clarifying_question=str(plan.get("clarifying_question") or ""),
        reason=str(plan.get("reason") or ""),
        raw_curator_plan=plan,
    )


def _pick_retrieval_text(contributions) -> str:
    """从 contributions 提取小说检索文本，向后兼容旧 build_context_bundle 签名。
    模组场景没有 novel_retrieval，返回空串。"""
    for c in contributions:
        if c.provider_id == "novel_retrieval" and c.applied:
            for layer in c.layers:
                if layer.get("id") == "novel_retrieval":
                    return layer.get("content", "") or ""
            if c.retrieval_items:
                return c.retrieval_items[0].get("text", "") or ""
    return ""


def _timeline_message(label: str, anchor: dict[str, Any]) -> str:
    if anchor.get("anchor_chapter"):
        return (
            f"Timeline anchored to chapter {anchor.get('anchor_chapter')}; "
            f"retrieval window {anchor.get('chapter_min')} - {anchor.get('chapter_max')}."
        )
    return f"No exact source anchor matched: {label}"


def _preview(text: str, limit: int = 180) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")


_RECENT_BUDGET = 2400   # 【最近对话】块总预算(字符)
_RECENT_PER_MSG = 600   # 单条消息上限:一条长正文不许吃光预算,保证多轮都进得来


def _recent_dialogue_json(state) -> str:
    """渲染【最近对话】块 —— **保尾不保头**。

    行者无疆报「子代理有时候抽风认为现在在小说序章-生化危机-激光通道」根因:
      ① `history_messages()` 会把**已 closed phase 的前情提要顶在最前面**(最旧的
         开局摘要),这里却按「最近对话」语义使用;
      ② 再对 `json.dumps(...)` 做**头部**截断 `[:2400]`。
    两者相乘 = 预算被开局摘要吃光,当前回合原文**一条都进不来**(save 268 实测
    前情提要 json 2409 字符 > 2400,玩家已在第 116 章,子代理却只看得到第 1-12 回合
    的激光通道)。玩家输入本身带场景信号时子代理还能纠正,一点「继续」这种无信号
    输入就照着开局摘要往下编 —— 这就是「有时候」。

    修法:①不要前情提要(历史另有 runtime_phase_digests 层专门注入)②从**最新**
    一条往回装,装不下的丢最旧的,永远保证最后一轮玩家输入+GM 正文在里面。
    """
    try:
        msgs = state.history_messages(limit_turns=3, include_digest=False)
    except TypeError:  # 老 state 实现(测试替身)没有 include_digest
        msgs = state.history_messages(limit_turns=3)
    from core.token_estimate import CJK_CHARS_PER_TOKEN, cjk_chars_to_budget, estimate_tokens
    picked: list[dict[str, Any]] = []
    budget = _RECENT_BUDGET
    for msg in reversed(msgs or []):
        if not isinstance(msg, dict):
            continue
        text = str(msg.get("content") or "")
        # 预算按「中文字符当量」计(token 口径):英文同等预算可装 ~2.5x 字符
        _per = cjk_chars_to_budget(text, _RECENT_PER_MSG)
        if len(text) > _per:
            text = text[:_per] + "…"
        cost = int(estimate_tokens(text) * CJK_CHARS_PER_TOKEN) + 24  # json 的 role/引号/逗号开销
        if picked and cost > budget:
            break
        picked.append({"role": msg.get("role") or "user", "content": text})
        budget -= cost
    picked.reverse()
    return json.dumps(picked, ensure_ascii=False)


def _curator_task_prompt(state, user_input: str, directives: list[Any],
                         steering_strength: str = "guided") -> str:
    world = state.data.get("world", {})
    memory = state.data.get("memory", {})
    local_directives = [getattr(d, "target", "") for d in directives]
    # fork 收编(行者无疆「永远默认在修炼」):此前 curator 完全不看 steering_strength,
    # 无论 rail/guided/free 都拿 main_quest 造 canon acceptance → 发散局玩家被当 rail railroad,
    # 日常/亲密场景也被强拉回主线。mode 打通:free 不强推主线,guided 温和,rail 才收束。
    _main = f"{memory.get('main_quest', '')} / {memory.get('current_objective', '')}"
    _ss = (steering_strength or "guided").strip().lower()
    if _ss == "free":
        goal_block = [
            "[Current objective / main quest (background only; do not push it in free mode)]",
            _main,
            "[Steering = free] The player is improvising freely. This turn's acceptance covers only what the player "
            "actually asked for / the scene they are in. **Never** invent acceptance points unrelated to the player's "
            "action this turn, such as 'advance the main quest / cultivation progress'; for everyday / intimate / resting "
            "scenes unrelated to the main quest, acceptance may contain only 'respond faithfully to the scene the player "
            "raised', or be empty.",
        ]
    elif _ss == "rail":
        goal_block = [
            "[Current objective / main quest]",
            _main,
            "[Steering = rail (follow the source)] You may set acceptance around the main quest and steer the plot "
            "to converge toward the source's course.",
        ]
    else:  # guided（默认）
        goal_block = [
            "[Current objective / main quest]",
            _main,
            "[Steering = guided] You may gently advance toward the main quest, but when the player clearly wanders off "
            "(everyday life / intimacy / rest) the player's intent comes first; **do not** create acceptance that drags "
            "the current scene back to the main quest.",
        ]
    return "\n".join([
        "Assess the context selection for this RPG turn before generation; return JSON only.",
        "",
        "[Player input]",
        user_input or "",
        "",
        "[Current timeline]",
        str(world.get("time", "")),
        "",
        "[Timeline requests detected locally]",
        json.dumps(local_directives, ensure_ascii=False),
        "",
        "[Override rule]",
        "Player input starting with /set means the user is explicitly rewriting the setting, timeline, world or persona; it MUST be passed to the main GM as a hard constraint and must not be ignored because the original timeline is locked.",
        "",
        *goal_block,
        "",
        "[Recent dialogue] (chronological; the last entry is the newest)",
        _recent_dialogue_json(state),
        "",
        "Output JSON only, no Markdown.",
    ])


def _is_set_command(text: str) -> bool:
    return bool(re.match(r"^\s*/(?:set|设定|设置)\s+", text or "", re.I))


class _CuratorStopped(Exception):
    """用户主动停止 curator,通过异常打断调用链。"""


def _local_fallback_plan(directives: list[Any], user_input: str, *,
                         reason: str = "") -> dict[str, Any]:
    return {
        "intent": "Parsed by local rules",
        "timeline_target": getattr(directives[0], "target", "") if directives else "",
        "retrieval_query": user_input,
        "must_include": [],
        "risk_flags": ["LLM sub-agent not enabled; deterministic rules only."],
        "reason": reason or "No LLM channel available.",
        "rule_candidate_actions": [],
    }


_CURATOR_TOOL_SCHEMA = {
    "name": "emit_curator_plan",
    "description": "Emit this RPG turn's Demand Ledger as a structured object.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "active_goal": {"type": "string"},
            "hard_constraints": {"type": "array", "items": {"type": "string"}},
            "soft_preferences": {"type": "array", "items": {"type": "string"}},
            "target_entities": {"type": "array", "items": {"type": "string"}},
            "target_location": {"type": "string"},
            "target_time": {"type": "string"},
            "timeline_target": {"type": "string"},
            "retrieval_query": {"type": "string"},
            "retrieval_plan": {
                "type": "object",
                "properties": {
                    "must_include": {"type": "array", "items": {"type": "string"}},
                    "should_include": {"type": "array", "items": {"type": "string"}},
                },
            },
            "candidate_actions": {"type": "array", "items": {"type": "string"}},
            "rule_candidate_actions": {
                "type": "array",
                "items": {"type": "object"},
            },
            "acceptance": {"type": "array", "items": {"type": "string"}},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
            "clarifying_question": {"type": "string"},
            "reason": {"type": "string"},
        },
        # iter#8: acceptance / candidate_actions / hard_constraints 提升为 required
        # (允许空数组,但必须出现该字段)。Demand Resolver 投了 700+ 行产出高价值结构,
        # 之前一半轮次为空,GM 又只说"参考",闭环断在子代理这一层。
        "required": ["intent", "retrieval_query", "confidence",
                     "acceptance", "candidate_actions", "hard_constraints"],
    },
}


def _call_curator_via_harness(
    *,
    user_id: int | None,
    api_id_override: str | None,
    model_override: str | None,
    system_prompt: str,
    user_prompt: str,
    stop_requested: Callable[[], bool],
    err_sink: dict | None = None,
) -> str | None:
    """走统一 agent harness 调 curator。

    优先级:override > user_preferences("context_agent.api_id"/"model_real_name")> 默认。
    返回原始文本(JSON);失败/超时返回 None;stop_requested 触发抛 _CuratorStopped。
    err_sink:可选 dict,失败时把 {category,message,api,model} 写入,供调用方给用户明确报错(非静默降级)。
    """
    from agents._harness import call_agent_json, resolve_api_and_model

    api_id, model = resolve_api_and_model(
        user_id,
        api_pref_key="context_agent.api_id",
        model_pref_key="context_agent.model_real_name",
        api_id_override=api_id_override,
        model_override=model_override,
    )

    def _do_call() -> str:
        # 瞬时错误(超时/网络/限流/网关)重试一次再放弃,减少「换模型也容易触发降级」(群反馈)。
        # 关键:把真实异常 log 出来——旧实现 except 直接吞成 None,导致「不知道是网络还是什么」。
        attempts = 2
        for attempt in range(attempts):
            try:
                text, _usage = call_agent_json(
                    api_id=api_id,
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    user_id=user_id,
                    tool_schema=_CURATOR_TOOL_SCHEMA,  # 三通道都启用强 schema
                    max_tokens=1200,
                    timeout_sec=45,   # 30→45:慢 BYOK provider 不至于一上来就超时降级
                    agent_kind="curator",
                    no_think=True,  # 结构化微任务禁深思(268 实锤族:思考模型吃光预算正文恒空)
                )
                return text or ""
            except Exception as exc:
                transient = _is_transient_err(exc)
                log.warning(
                    "[context_agent] curator harness 失败 (try %d/%d, api=%s model=%s, transient=%s): %s: %s",
                    attempt + 1, attempts, api_id, model, transient,
                    type(exc).__name__, str(exc)[:240],
                )
                if transient and attempt + 1 < attempts:
                    time.sleep(0.6)
                    continue
                raise
        return ""

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="curator-harness")
    future = executor.submit(_do_call)
    try:
        while not future.done():
            if stop_requested():
                future.cancel()
                raise _CuratorStopped()
            time.sleep(0.03)
        try:
            return future.result()
        except Exception as exc:
            # 分类真实错误写入 err_sink,供上层给用户明确提示(403/401/余额/限流…),不再静默降级。
            if err_sink is not None:
                try:
                    from agents.provider_errors import classify_provider_error
                    cls = classify_provider_error(exc)
                    if cls:
                        err_sink["category"], err_sink["message"] = cls[0], cls[1]
                    err_sink.setdefault("api", api_id)
                    err_sink.setdefault("model", model)
                except Exception:
                    pass
            return None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _call_llm_curator(
    llm_curator: Callable[[str, str], str],
    task_prompt: str,
    stop_requested: Callable[[], bool],
) -> str | None:
    """轮询 future + 监听 stop。

    LLM 请求一旦发出无法在 HTTP 层硬中断（SDK 没暴露 cancel token），
    所以 stop_requested 触发后我们立即"放弃等待结果"，让上层马上响应用户。
    后台请求会继续跑完（继续计费），但返回的内容会被丢弃，不会进入存档/SSE。
    用更短的 poll 间隔（30ms）让 stop 响应快。
    """
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="curator")
    future = executor.submit(llm_curator, AGENT_PROMPT, task_prompt)
    try:
        while not future.done():
            if stop_requested():
                # 注意：future.cancel() 对已经在跑的请求不会真正取消
                # 后台请求会继续到完成；我们不再等待结果
                future.cancel()
                return None
            time.sleep(0.03)  # 之前 0.12s，现在 30ms 提高 stop 响应度
        return future.result()
    finally:
        # wait=False：不阻塞当前线程；如果 future 还在跑，由后台线程自然完成
        executor.shutdown(wait=False, cancel_futures=True)


def _parse_curator_json(text: str) -> dict[str, Any]:
    """task 79：Demand Ledger schema 解析。向后兼容旧 curator_plan 6 字段。"""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.I | re.M).strip()
    match = re.search(r"\{.*\}", raw, re.S)
    if match:
        raw = match.group(0)
    try:
        data = json.loads(raw)
    except Exception:
        return {
            "intent": "The LLM sub-agent's reply could not be parsed; fell back to rule-based retrieval.",
            "active_goal": "",
            "hard_constraints": [],
            "soft_preferences": [],
            "target_entities": [],
            "target_location": "",
            "target_time": "",
            "timeline_target": "",
            "retrieval_query": "",
            "retrieval_plan": {"must_include": [], "should_include": []},
            "candidate_actions": [],
            "acceptance": [],
            "risk_flags": ["curator_json_parse_failed"],
            "confidence": 0.0,
            "clarifying_question": "",
            "reason": (text or "")[:300],
        }
    # retrieval_plan 嵌套对象处理 + 向后兼容老 must_include 顶层字段
    rp_raw = data.get("retrieval_plan") or {}
    must_include = _string_list(
        (rp_raw.get("must_include") if isinstance(rp_raw, dict) else None)
        or data.get("must_include")
    )
    should_include = _string_list(
        rp_raw.get("should_include") if isinstance(rp_raw, dict) else None
    )
    # confidence: 接受 number 或 string；0.0-1.0 范围裁剪
    try:
        conf = float(data.get("confidence", 1.0))
    except Exception:
        conf = 1.0
    conf = max(0.0, min(1.0, conf))
    return {
        "intent": str(data.get("intent") or ""),
        "active_goal": str(data.get("active_goal") or ""),
        "hard_constraints": _string_list(data.get("hard_constraints")),
        "soft_preferences": _string_list(data.get("soft_preferences")),
        "target_entities": _string_list(data.get("target_entities")),
        "target_location": str(data.get("target_location") or ""),
        "target_time": str(data.get("target_time") or ""),
        "timeline_target": str(data.get("timeline_target") or ""),
        "retrieval_query": str(data.get("retrieval_query") or ""),
        "retrieval_plan": {
            "must_include": must_include,
            "should_include": should_include,
        },
        # 向后兼容：保留顶层 must_include 让旧 _context_agent_decision 渲染不破
        "must_include": must_include,
        "candidate_actions": _string_list(data.get("candidate_actions")),
        # 5E-compatible 规则动作候选。LLM 返回 dict 列表；解析时只接受 dict（容错过滤）。
        "rule_candidate_actions": _rule_actions_list(data.get("rule_candidate_actions")),
        # 与 GM prompt 渲染上限对齐(rules_text.py:65 只渲染 acceptance[:6])。存 8 渲 6 →
        # 第 7/8 条 GM 从没见过却被 verify_acceptance 检查 → 必然假 unmet + 白烧一次 retry。
        # 收敛到 6:GM 所见 == verifier 所查,单一真相。
        "acceptance": _string_list(data.get("acceptance"))[:6],
        "risk_flags": _string_list(data.get("risk_flags")),
        "confidence": conf,
        "clarifying_question": str(data.get("clarifying_question") or "").strip(),
        "reason": str(data.get("reason") or ""),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()][:8]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


_VALID_RULE_KINDS = {
    "skill_check", "investigate", "attack", "saving_throw", "move", "short_rest",
    "trap_check", "use_item", "speak", "wait",
}


def _rule_actions_list(value: Any) -> list[dict]:
    """规则候选动作。只接受 dict 列表；过滤无效项。"""
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if not kind or kind not in _VALID_RULE_KINDS:
            continue
        # 浅复制，限制字段长度
        clean: dict = {"kind": kind}
        for key in ("skill", "ability", "target", "target_name", "weapon", "reason"):
            v = item.get(key)
            if isinstance(v, str) and v.strip():
                clean[key] = v.strip()[:120]
        for key in ("dc", "dc_hint"):
            try:
                if item.get(key) is not None:
                    clean[key] = int(item[key])
            except (TypeError, ValueError):
                continue
        if "advantage" in item:
            clean["advantage"] = bool(item.get("advantage"))
        if "disadvantage" in item:
            clean["disadvantage"] = bool(item.get("disadvantage"))
        out.append(clean)
        if len(out) >= 8:
            break
    return out


def _normalize_timeline_target(value: str) -> str:
    value = " ".join((value or "").split()).strip()
    if not value:
        return ""
    if re.fullmatch(r"\d{1,5}", value):
        return f"第{value}章"
    return value


def _retrieval_query(user_input: str, plan: dict[str, Any]) -> str:
    parts = [
        user_input or "",
        _normalize_timeline_target(plan.get("timeline_target", "")),
        plan.get("retrieval_query", ""),
        " ".join(plan.get("must_include", []) or []),
    ]
    return "\n".join(part for part in parts if str(part).strip())
