"""
demo.py — 主入口：CLI 游戏循环

运行方式：
    cd rpg/
    ../rpg_env/bin/python demo.py

命令：
    /save    — 手动存档
    /status  — 显示玩家状态
    /debug   — 显示上轮召回内容
    q / 退出 — 存档并退出
"""
from __future__ import annotations

import sys
from pathlib import Path

# 加载 .env（位于项目根目录，rpg/ 的上一级）
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # dotenv 不可用时直接读环境变量

from agents.gm import GameMaster
from retrieval import retrieve_context
from state import GameState

DIVIDER   = "─" * 52
THIN_DIV  = "·" * 52


def _print_gm(text: str):
    print()
    print(DIVIDER)
    print(text)
    print(DIVIDER)
    print()


def setup_character(state: GameState) -> None:
    """首次进入时，引导玩家创建角色"""
    print()
    print("=" * 52)
    print("  Generic RPG Demo")
    print("=" * 52)
    print()
    print("The story is about to begin.")
    print("You are about to enter this world and be drawn into it.")
    print()
    print(THIN_DIV)
    print()

    name = input("What is your name?\n> ").strip()
    if not name:
        name = "Nameless"

    print()
    print("What role do you play in this story?")
    print("  1. A courier for an old European family, carrying messages between factions")
    print("  2. An intelligence liaison for the Earth Federation's Pacific branch")
    print("  3. A minor noble of the exiled Wiser Empire")
    print("  4. Custom...")
    print()
    choice = input("Choose (1-4):\n> ").strip()

    roles = {
        "1": "European family courier",
        "2": "Earth Federation Pacific intelligence liaison",
        "3": "Exiled Wiser Empire noble",
    }
    if choice in roles:
        role = roles[choice]
    else:
        role = input("Describe your role:\n> ").strip() or "Passerby"

    print()
    background = input(f"In a sentence or two, why did {name} come here? (optional)\n> ").strip()
    if not background:
        background = "No clear reason; they just came."

    state.setup_player(name, role, background)
    state.save()
    print()
    print(THIN_DIV)


def game_loop(state: GameState, gm: GameMaster) -> None:
    last_context = ""

    # 开场白
    print("\nGenerating the opening...")
    opening_ctx = retrieve_context("开场", verbose=False)
    opening     = gm.generate_opening(state, retrieved_context=opening_ctx)
    _print_gm(opening)

    # 游戏主循环
    while True:
        try:
            user_input = input(f"[{state.player_name}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[Saved and exited]")
            state.save()
            break

        if not user_input:
            continue

        # ── 内置命令 ──
        if user_input.lower() in ("q", "quit", "exit", "退出"):
            print("[Saved and exited]")
            state.save()
            break

        if user_input == "/save":
            state.save()
            print("[Saved]")
            continue

        if user_input == "/status":
            print()
            print(state.short_summary())
            print()
            continue

        if user_input == "/debug":
            print()
            print("=== Last turn's retrieved context ===")
            print(last_context or "(nothing retrieved this turn)")
            print()
            continue

        if user_input.startswith("/loc "):
            loc = user_input[5:].strip()
            if loc:
                state.update_location(loc)
                print(f"[Location updated: {loc}]")
            continue

        if user_input.startswith("/rel "):
            # /rel 角色名 状态
            parts = user_input[5:].strip().split(" ", 1)
            if len(parts) == 2:
                state.update_relationship(parts[0], parts[1])
                print(f"[Relationship updated: {parts[0]} -> {parts[1]}]")
            continue

        # ── 正常游戏输入 ──
        last_context = retrieve_context(user_input, verbose=False)
        response     = gm.respond(user_input, last_context, state)
        state.record_turn(user_input, response)
        state.save()
        _print_gm(response)


def main():
    state = GameState.load_or_new()

    if state.is_new:
        setup_character(state)

    try:
        gm = GameMaster()
    except ValueError as e:
        print(f"[Error] {e}")
        sys.exit(1)
    except Exception as e:
        if "401" in str(e) or "authentication" in str(e).lower():
            print("[Error] Invalid API key (401).")
            print("Set a valid ANTHROPIC_API_KEY in the .env file at the project root:")
            print("  ANTHROPIC_API_KEY=<your Anthropic API key>")
        else:
            print(f"[Error] {e}")
        sys.exit(1)

    game_loop(state, gm)


if __name__ == "__main__":
    main()
