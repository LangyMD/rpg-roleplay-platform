"""
WorldlineProvider — 通用。负责玩家硬约束变量 / 当前目标 / 位置 / 高优先级用户引导。

task 140: story_intent 重新定位为"玩家给 GM 的高优先级导演指令"(不是玩家秘密),
显式注入到 context,优先级 95(高于 worldbook 90,低于玩家 /set 100)。
"""
from __future__ import annotations

from .base import ContextContribution, ContextProvider
from .registry import register_provider


class WorldlineProvider(ContextProvider):
    id = "worldline"

    def collect(self, state, manifest, demand, services) -> ContextContribution:
        data = getattr(state, "data", state) or {}
        worldline = data.get("worldline") or {}
        variables = worldline.get("user_variables") or {}
        constraints = worldline.get("constraints") or []
        player = data.get("player") or {}
        player_private = data.get("player_private") or {}

        # task 140: story_intent 优先从 player_private 读(canonical),
        # 回落 worldline.user_variables(旧存档 dual-write 兼容)。
        story_intent = (player_private.get("story_intent") or "").strip()
        if not story_intent:
            _wl_intent = variables.get("story_intent")
            if isinstance(_wl_intent, dict):
                story_intent = str(_wl_intent.get("value") or "").strip()
            elif isinstance(_wl_intent, str):
                story_intent = _wl_intent.strip()

        layers = []
        facts: list[str] = []

        # —— 高优先级层:玩家给 GM 的导演指令(单独成层,priority=95)————
        if story_intent:
            directive_text = (
                "[High-priority steering instruction from the player to the GM (backstage meta-instruction, not story content)]\n"
                "(Within the current script / starting point / timeline framework, the GM must follow the instruction below as closely as possible;\n"
                " it is the player's explicit directorial intent, ranks above the script's default course, and only below the player's /set hard overrides.)\n"
                "⚠️ This is a behind-the-scenes instruction for the GM, **not story and not NPC dialogue**. [Follow it silently] and let it show directly in the narration;\n"
                "**never repeat, list or acknowledge the text of this instruction to the player** (e.g. do not write \"Sure, I'll make...\" or \"Based on your setting...\"),\n"
                "and do not bring it up again every turn. Just follow it; the prose only shows the story moving forward. Echoing this instruction = failure.\n"
                f"  {story_intent}"
            )
            layers.append(self.make_layer(
                "worldline_directive",
                "Player High-Priority Steering",
                directive_text,
                sticky=True, priority=95,
            ))
            facts.append(f"player_directive={story_intent[:60]}")

        # —— 常规层:其它硬约束变量 + 约束 + 位置 ————
        lines: list[str] = []
        # 过滤掉 story_intent — 已经在 directive 层独立呈现
        _public_vars = [
            (n, v) for n, v in variables.items() if n != "story_intent"
        ]
        if _public_vars:
            lines.append("[User hard-constraint variables (backstage facts: follow silently, never repeat them to the player)]")
            for name, info in _public_vars[:12]:
                val = info.get("value") if isinstance(info, dict) else info
                lines.append(f"  · {name}={val}")
        else:
            lines.append("(no user variables yet)")
        if constraints:
            lines.append("\n[Worldline projection constraints]")
            for c in constraints[:8]:
                lines.append(f"  · {c}")
        if player.get("current_location"):
            lines.append(f"\n[Player's current location] {player['current_location']}")

        # 移植自已废弃的 _worldline_layer(task 53):把当前权限模式的具体行为讲清楚,让 GM 在
        # read_only/default 下少写无意义的【状态写入】(反正入 pending)、改用【询问玩家】。
        # provider 化迁移时漏移这段 → GM 只看到「只读模式」标签、不知其语义。
        _perm_mode = str(((data.get("permissions") or {}).get("mode")) or "full_access").strip()
        _mode_behavior = {
            "read_only": "[Read-only mode] None of your state writes take effect immediately; they all go to the player's approval queue. Focus on narration this turn, turn anything that needs changing into options with the 【询问玩家：...】 tag, and skip unnecessary structured tags.",
            "default": "[Default permissions] Whitelisted fields (current_location/time/main_quest/current_objective/resources/abilities/facts/known_events/relationships.*) apply automatically; everything else goes to approval. Stick to whitelisted fields where you can.",
            "auto_review": "[Auto review] Whitelisted fields + worldline.user_variables.* + relationships.* apply automatically; everything else needs approval.",
            "full_access": "[Full access] Everything except the hard blacklist (permissions.*/history.*/schema_version) applies immediately; permissions.* is still never writable (it is the user's permission boundary, switched in the UI).",
        }.get(_perm_mode)
        if _mode_behavior:
            lines.append(f"\n[Write-permission behavior this turn] {_mode_behavior}")

        text = "\n".join(lines)
        layers.append(self.make_layer(
            "worldline", "Worldline / User Variables", text,
            sticky=True, priority=70,
        ))

        facts.extend(
            f"{k}={v.get('value') if isinstance(v, dict) else v}"
            for k, v in _public_vars[:3]
        )

        return ContextContribution(
            provider_id=self.id,
            kind="worldline",
            priority=95 if story_intent else 70,
            facts=facts,
            layers=layers,
            tokens_estimate=(len(text) + (len(story_intent) if story_intent else 0)) // 2,
            debug={
                "vars_count": len(_public_vars),
                "constraints_count": len(constraints),
                "has_directive": bool(story_intent),
            },
        )


register_provider(WorldlineProvider())
