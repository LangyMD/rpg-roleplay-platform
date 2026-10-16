"""state/consequence_ledger.py — 后果账本 v1(活世界·柱子2)确定性核心。

设计文档: docs/design/consequence_ledger_v1.md

目标: 玩家的选择在 N 回合后主动回响(欠的债有人来讨、救过的人再出现、许下的
约定到期),不靠 memory/facts 被检索命中碰运气。

原则(与设计文档一致):
- 触发判定/调度/注入 = 确定性代码;只有"兑现的文案"由 GM 生成。
- 本模块三个纯函数只操作 state.data dict,不做任何 IO(DB/网络/时间戳除外的
  wall-clock 读取也不做 —— "turns" 到期靠 state.data["turn"] 与
  created_turn 的差值,不读真实时间)。方便单测、方便 GameState mixin 薄封装调用。

状态结构 (state.data["consequence_ledger"]: list[dict]):
    {
      "id": "cq_a1b2c3",
      "text": "答应雷纳德查清林中兽伤,明天中午前带证据回村",
      "due": {"turns": 5} 或 {"location": "阿托菲村"},
      "created_turn": 12,
      "status": "pending",   # pending | fired
      "fired_turn": None,
      "origin": "gm",        # gm | recorder | player
    }
"""
from __future__ import annotations

import secrets
from typing import Any

from core.text import normalize_for_fp
from state.parsers import _clean_item

# pending 上限:防 LLM 刷屏。超出拒绝并在 updates 里说明。
MAX_PENDING = 20

# 触发后仍纳入注入窗口的回合数(给 GM 连续几回合的兑现窗口)。
FIRED_ECHO_WINDOW = 3


def _ledger(state_data: dict) -> list[dict]:
    """取 / 建 state_data["consequence_ledger"] 列表引用(原地可变)。"""
    ledger = state_data.setdefault("consequence_ledger", [])
    if not isinstance(ledger, list):
        ledger = []
        state_data["consequence_ledger"] = ledger
    return ledger


def _normalize_for_fp(text: str) -> str:
    """指纹归一化:去掉全部标点/空白,只留文字数字。

    生产实测:史官跨回合重提取同一承诺时措辞会漂(「期限约定——」vs「期限——」、
    全角/半角逗号),精确匹配挡不住;归一化吃掉标点差异。措辞用词级漂移由
    recorder 提示词侧的「已登记清单」防(见 recorder._build_user_prompt)。

    归一化规则统一到中立缝 core.text.normalize_for_fp(单一真源);本模块(柱子2)与
    world_heartbeat 共同依赖该缝、而非互相 import,「两柱互不读写」的架构隔离仍成立
    (详见设计文档 §分工)。
    """
    return normalize_for_fp(text)


def _fingerprint(text: str, due: dict) -> tuple[str, str, str]:
    """指纹去重键:归一化 text + due 两个字段(不含 id/turn/origin,同 dedupe_json_ops 思路)。"""
    due = due or {}
    return (
        _normalize_for_fp(text),
        str(due.get("turns", "")),
        str(due.get("location", "")),
    )


def register_consequence(
    state_data: dict,
    *,
    text: str,
    due_turns: int | None = None,
    due_location: str | None = None,
    created_turn: int | None = None,
    origin: str = "gm",
) -> tuple[bool, str]:
    """登记一条待兑现的后果。纯函数,直接改 state_data,不做 IO。

    返回 (ok, message)。message 是给 updates 列表用的中文说明(成功/拒绝原因)。

    校验顺序(设计文档 §6 用例口径):
      1. text 必填
      2. due_turns / due_location 至少给一个,且 turns 必须是正整数
      3. 上限 20 条 pending → 拒绝并说明
      4. 同 text+due 指纹去重 → 拒绝并说明
    """
    text = _clean_item(text or "")
    if not text:
        return False, "Consequence ignored (no text)"

    due: dict[str, Any] = {}
    if due_turns is not None:
        try:
            turns_int = int(due_turns)
        except (TypeError, ValueError):
            return False, f"Consequence ignored (invalid due_turns: {due_turns!r})"
        if turns_int <= 0:
            return False, f"Consequence ignored (due_turns must be a positive integer: {due_turns!r})"
        due["turns"] = turns_int
    location = _clean_item(due_location or "")
    if location:
        due["location"] = location

    if not due:
        return False, "Consequence ignored (needs due_turns or due_location)"

    ledger = _ledger(state_data)

    pending = [e for e in ledger if e.get("status") == "pending"]
    if len(pending) >= MAX_PENDING:
        return False, f"Consequence rejected (already {MAX_PENDING} pending, the maximum)"

    fp = _fingerprint(text, due)
    for e in ledger:
        if _fingerprint(e.get("text", ""), e.get("due") or {}) == fp:
            return False, "Consequence ignored (duplicate: same text and due condition already recorded)"

    turn = int(created_turn if created_turn is not None else state_data.get("turn", 0) or 0)
    entry = {
        "id": f"cq_{secrets.token_urlsafe(6)}",
        "text": text,
        "due": due,
        "created_turn": turn,
        "status": "pending",
        "fired_turn": None,
        "origin": origin if origin in ("gm", "recorder", "player") else "gm",
    }
    ledger.append(entry)
    return True, f"Consequence recorded: {text[:40]}"


def scan_and_fire(state_data: dict) -> list[dict]:
    """扫描 pending 条目,触发到期的(turns 或 location 命中),幂等。

    返回本次新触发的条目列表(浅拷贝)。fired 状态的条目不会再次触发
    (status != "pending" 直接跳过)。
    """
    ledger = _ledger(state_data)
    if not ledger:
        return []

    current_turn = int(state_data.get("turn", 0) or 0)
    current_location = _clean_item(
        (state_data.get("player", {}) or {}).get("current_location", "") or ""
    )

    fired_now: list[dict] = []
    for entry in ledger:
        if entry.get("status") != "pending":
            continue
        due = entry.get("due") or {}
        hit = False
        if "turns" in due:
            try:
                due_turns = int(due.get("turns"))
            except (TypeError, ValueError):
                due_turns = None
            if due_turns is not None:
                created_turn = int(entry.get("created_turn", 0) or 0)
                if current_turn >= created_turn + due_turns:
                    hit = True
        if not hit and "location" in due:
            loc = _clean_item(str(due.get("location") or ""))
            if loc and current_location and loc in current_location:
                hit = True
        if hit:
            entry["status"] = "fired"
            entry["fired_turn"] = current_turn
            fired_now.append(dict(entry))

    return fired_now


def entries_for_injection(state_data: dict) -> list[dict]:
    """本回合注入用的条目集合:本回合刚触发的 + 最近 FIRED_ECHO_WINDOW 回合内
    触发但仍在"兑现窗口"内的(给 GM 连续几回合自然兑现的机会)。

    不做扫描/写入,只读 state_data 当前快照 —— 调用方(provider)应先调
    scan_and_fire 再调本函数,或本函数与 scan_and_fire 在同一次 collect 里
    先后调用(见 consequence_echo.py)。
    """
    ledger = _ledger(state_data)
    if not ledger:
        return []
    current_turn = int(state_data.get("turn", 0) or 0)
    out: list[dict] = []
    for entry in ledger:
        if entry.get("status") != "fired":
            continue
        fired_turn = entry.get("fired_turn")
        if fired_turn is None:
            continue
        try:
            fired_turn_int = int(fired_turn)
        except (TypeError, ValueError):
            continue
        if current_turn - fired_turn_int <= FIRED_ECHO_WINDOW:
            out.append(entry)
    # 按 created_turn 升序(早种下的先呈现),与设计文档示例一致
    out.sort(key=lambda e: e.get("created_turn", 0))
    return out


__all__ = [
    "MAX_PENDING",
    "FIRED_ECHO_WINDOW",
    "register_consequence",
    "scan_and_fire",
    "entries_for_injection",
]
