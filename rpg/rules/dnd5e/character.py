"""
rules.dnd5e.character — 角色卡数据结构与默认值。
"""
from __future__ import annotations

import copy

from .ruleset import (
    ABILITIES,
    SKILL_TO_ABILITY,
    ability_modifier,
    normalize_skill,
    proficiency_bonus,
)

DEFAULT_CHARACTER: dict = {
    "name": "",
    "level": 1,
    "class_name": "scout",   # 仅作叙事标签，规则上不区分职业
    "species": "human",
    "background": "miner",
    "abilities": {"str": 10, "dex": 14, "con": 12, "int": 11, "wis": 13, "cha": 10},
    "proficiency_bonus": 2,
    "skills": {"stealth": "proficient", "investigation": "proficient", "perception": "proficient"},
    "max_hp": 12,
    "hp": 12,
    "ac": 13,
    "inventory": [
        {"id": "shortsword", "name": "Shortsword", "qty": 1, "kind": "weapon"},
        {"id": "shortbow", "name": "Shortbow", "qty": 1, "kind": "weapon"},
        {"id": "torch", "name": "Torch", "qty": 2, "kind": "gear"},
        {"id": "healing_draught", "name": "Healing Draught", "qty": 1, "kind": "consumable"},
    ],
    "conditions": [],   # 简易状态：e.g. ["poisoned", "prone"]
    "features": ["Proficient: Stealth / Investigation / Perception"],
    "weapons": {
        "shortsword": {"attack_bonus": 4, "damage": "1d6+2", "kind": "melee", "name": "Shortsword"},
        "shortbow": {"attack_bonus": 4, "damage": "1d6+2", "kind": "ranged", "name": "Shortbow"},
    },
}


def make_default_character(name: str = "Drifter", level: int = 1) -> dict:
    """生成默认 Ash Mine 探险者角色卡。"""
    char = copy.deepcopy(DEFAULT_CHARACTER)
    char["name"] = name or "Drifter"
    char["level"] = max(1, int(level))
    char["proficiency_bonus"] = proficiency_bonus(char["level"])
    # con 修正调整 max_hp（首级用类似 d8 + con）
    con_mod = ability_modifier(char["abilities"]["con"])
    base_hp = 8 + con_mod
    for _lvl in range(2, char["level"] + 1):
        base_hp += 5 + con_mod
    char["max_hp"] = max(1, base_hp)
    char["hp"] = char["max_hp"]
    return char


def get_ability_score(character: dict, ability: str) -> int:
    abilities = (character or {}).get("abilities", {}) or {}
    return int(abilities.get(ability, 10))


def get_skill_proficiency(character: dict, skill: str) -> str:
    """返回 "" / "proficient" / "expertise"。"""
    skill = normalize_skill(skill)
    skills = (character or {}).get("skills", {}) or {}
    val = skills.get(skill, "")
    if isinstance(val, bool):
        return "proficient" if val else ""
    return str(val or "")


def skill_modifier(character: dict, skill: str) -> int:
    """计算技能检定 mod：属性修正 + 熟练（或专长 x2）。"""
    skill = normalize_skill(skill)
    ability = SKILL_TO_ABILITY.get(skill)
    if not ability:
        return 0
    mod = ability_modifier(get_ability_score(character, ability))
    prof = proficiency_bonus(character.get("level", 1))
    state = get_skill_proficiency(character, skill)
    if state == "expertise":
        mod += prof * 2
    elif state == "proficient":
        mod += prof
    return mod


def saving_throw_modifier(character: dict, ability: str) -> int:
    if ability not in ABILITIES:
        return 0
    mod = ability_modifier(get_ability_score(character, ability))
    saves = (character or {}).get("saves", {}) or {}
    if saves.get(ability):
        mod += proficiency_bonus(character.get("level", 1))
    return mod


def heal(character: dict, amount: int) -> int:
    """回复 HP，不超过 max_hp。返回实际回复量。"""
    amount = max(0, int(amount))
    max_hp = int(character.get("max_hp", 0) or 0)
    cur = int(character.get("hp", 0) or 0)
    new_hp = min(max_hp, cur + amount)
    character["hp"] = new_hp
    return new_hp - cur


def take_damage(character: dict, amount: int) -> int:
    """扣 HP，下限 0。返回实际扣除量。"""
    amount = max(0, int(amount))
    cur = int(character.get("hp", 0) or 0)
    new_hp = max(0, cur - amount)
    character["hp"] = new_hp
    return cur - new_hp


def has_condition(character: dict, cond: str) -> bool:
    return cond in ((character or {}).get("conditions") or [])


# ── Canonical inventory operations ────────────────────────────
# player_character.inventory 是物品的唯一真相源。memory.resources 是派生展示层。

# 中英文别名 → canonical item id（用于解析玩家自然语言）
_ITEM_ALIASES: dict[str, str] = {
    # Torch
    "torch": "torch", "火把": "torch", "火炬": "torch", "提灯": "torch",
    # Healing draught
    "healing draught": "healing_draught", "healing_draught": "healing_draught",
    "急救药剂": "healing_draught", "药剂": "healing_draught", "药水": "healing_draught",
    # Shortsword
    "shortsword": "shortsword", "short sword": "shortsword",
    "短剑": "shortsword", "剑": "shortsword",
    # Shortbow
    "shortbow": "shortbow", "short bow": "shortbow",
    "短弓": "shortbow", "弓": "shortbow",
    # Longsword / Longbow（与短剑/短弓区分，供"多把同类武器共存"消歧）
    "longsword": "longsword", "long sword": "longsword", "长剑": "longsword",
    "longbow": "longbow", "long bow": "longbow", "长弓": "longbow",
    # Antidote（解毒剂，与药剂/药水区分）
    "antidote": "antidote", "解毒剂": "antidote", "解毒药": "antidote",
}


def normalize_item_alias(alias: str) -> str:
    """把任意玩家文本里的物品别名映射到 canonical item id。无匹配返回空串。

    Bug 3：原实现做双向子串匹配（alias_key in key OR key in alias_key），
    叠加单字别名（剑/弓）会误命中——"长剑" 含子串 "剑" → 错配到 shortsword，
    反向 "key in alias_key" 又让玩家文本片段命中更长的别名。
    现规则：
      1. 精确相等优先（dict 命中）。单字别名只能在这一步精确命中。
      2. 仅前向子串：≥2 字的已知别名整体出现在玩家文本里才算匹配，
         取最长匹配，避免短别名抢占（"长剑" 不再被 "剑" 吞掉）。
    """
    if not alias:
        return ""
    key = str(alias).strip().lower()
    if not key:
        return ""
    if key in _ITEM_ALIASES:
        return _ITEM_ALIASES[key]
    best_canonical = ""
    best_len = 0
    for alias_key, canonical in _ITEM_ALIASES.items():
        if len(alias_key) < 2:
            continue  # 单字别名只精确匹配，不参与子串
        if alias_key in key and len(alias_key) > best_len:
            best_canonical = canonical
            best_len = len(alias_key)
    return best_canonical


def find_inventory_item(character: dict, alias: str) -> dict | None:
    """根据 alias 找 inventory 项。
    顺序：canonical id 命中 → name 精确 → name 前向子串（别名整体出现在物品名里，≥2 字）。

    Bug 3：去掉反向 `name_low in alias_low`（"药"/"剑" 等短物品名会被长别名吞掉），
    且单字 alias 不做子串匹配，避免多把同类物品共存时误命中第一条。
    """
    inventory = (character or {}).get("inventory") or []
    raw_low = str(alias or "").strip().lower()
    canonical = normalize_item_alias(alias) or raw_low
    # 1. canonical id 命中
    for item in inventory:
        if str(item.get("id", "")).lower() == canonical:
            return item
    # 2. name 精确（忽略大小写）
    for item in inventory:
        if str(item.get("name", "")).lower() == raw_low:
            return item
    # 3. name 前向子串：alias 作为整体出现在物品名里（要求 ≥2 字防单字误命中）
    if len(raw_low) >= 2:
        for item in inventory:
            name_low = str(item.get("name", "")).lower()
            if name_low and raw_low in name_low:
                return item
    return None


def grant_inventory_item(character: dict, item_id: str, name: str | None = None,
                         qty: int = 1, kind: str = "misc") -> dict:
    """向 player_character.inventory 授予物品（canonical 唯一真相源的"加"操作）。

    与 consume_inventory_item 对称：
      - 按 item_id（非 name）判重：已存在 → qty 累加；否则新建条目。
      - qty <= 0 拒绝（与 consume 的下限校验一致）。
      - 新建时补 name（缺省回退 item_id）/ kind；已存在时不覆盖原有 name/kind，
        仅在原条目缺失时补全。

    返回 {ok, item_id, item_name, qty_before, qty_after, granted, created, error}。
    """
    qty = int(qty or 0)
    if qty <= 0:
        return {"ok": False, "error": "qty must be > 0", "item_id": item_id or "",
                "qty_before": 0, "qty_after": 0, "granted": 0, "created": False}
    item_id = str(item_id or "").strip()
    if not item_id:
        return {"ok": False, "error": "missing item_id",
                "item_id": "", "qty_before": 0, "qty_after": 0, "granted": 0, "created": False}
    inventory = character.setdefault("inventory", [])
    id_low = item_id.lower()
    for item in inventory:
        if str(item.get("id", "")).lower() == id_low:
            qty_before = int(item.get("qty", 0) or 0)
            item["qty"] = qty_before + qty
            if name and not item.get("name"):
                item["name"] = name
            if kind and not item.get("kind"):
                item["kind"] = kind
            return {
                "ok": True, "item_id": item.get("id"), "item_name": item.get("name"),
                "qty_before": qty_before, "qty_after": item["qty"], "granted": qty,
                "created": False, "error": "",
            }
    new_item = {"id": item_id, "name": name or item_id, "qty": qty, "kind": kind or "misc"}
    inventory.append(new_item)
    return {
        "ok": True, "item_id": item_id, "item_name": new_item["name"],
        "qty_before": 0, "qty_after": qty, "granted": qty, "created": True, "error": "",
    }


def consume_inventory_item(character: dict, alias: str, qty: int = 1) -> dict:
    """从 player_character.inventory 消耗物品。

    返回 {ok, item_id, qty_before, qty_after, consumed, error}。
    qty <= 0 时 ok=False。物品数量减到 0 自动从 inventory 中移除。
    """
    qty = max(0, int(qty or 0))
    if qty == 0:
        return {"ok": False, "error": "qty must be > 0"}
    item = find_inventory_item(character, alias)
    if item is None:
        return {"ok": False, "error": f"no {alias!r} in the inventory",
                "item_id": "", "qty_before": 0, "qty_after": 0, "consumed": 0}
    qty_before = int(item.get("qty", 0) or 0)
    if qty_before <= 0:
        return {"ok": False, "error": f"{item.get('name')} is used up",
                "item_id": item.get("id"), "qty_before": 0, "qty_after": 0, "consumed": 0}
    consumed = min(qty, qty_before)
    qty_after = qty_before - consumed
    item["qty"] = qty_after
    # qty 为 0 时从列表移除（保持 inventory 紧凑）
    if qty_after == 0:
        inventory = character.get("inventory") or []
        try:
            inventory.remove(item)
        except ValueError:
            pass
    return {
        "ok": True,
        "item_id": item.get("id"),
        "item_name": item.get("name"),
        "qty_before": qty_before,
        "qty_after": qty_after,
        "consumed": consumed,
        "error": "",
    }


def resources_from_inventory(character: dict) -> list[str]:
    """memory.resources 派生展示。inventory → ['Name ×N', ...]。"""
    inventory = (character or {}).get("inventory") or []
    out: list[str] = []
    for item in inventory:
        qty = int(item.get("qty", 0) or 0)
        if qty <= 0:
            continue
        name = item.get("name") or item.get("id") or ""
        if name:
            out.append(f"{name} ×{qty}")
    return out


def add_condition(character: dict, cond: str) -> bool:
    conds = (character or {}).setdefault("conditions", [])
    if cond not in conds:
        conds.append(cond)
        return True
    return False


def remove_condition(character: dict, cond: str) -> bool:
    conds = (character or {}).setdefault("conditions", [])
    if cond in conds:
        conds.remove(cond)
        return True
    return False
