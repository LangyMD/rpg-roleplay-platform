"""
command_tools_ui_action.py — task 109b-2

3 个 "UI action" 工具, 由 console_assistant 给 LLM 用:

  ui_describe_page()       — 返回当前页面 ui_atlas snapshot (从 pageContext 拿)
  ui_set_field(form_id, field_key, value)  — 填字段 (前端 React state 同步)
  ui_click(form_id, action_label)          — 点按钮

设计要点:
  · 这 3 个工具的 executor 不直接做事 — 它返回一个特殊 dict
    {"__ui_action__": "set_field|click", ...args}
  · console_assistant 主循环检测到 __ui_action__ 后, yield 一个 SSE
    event: ui_action, 前端 console-assistant-panel 监听后调
    window.__UI_ATLAS.setField / click — DOM 直接生效, React state 同步
  · 工具 result 立刻给 LLM 一个 ack 字符串, LLM 不阻塞等前端
  · 因为是"通过用户浏览器代为执行", 权限完全跟随用户在 UI 上能做的事 (用户
    自己能填能点的, agent 才能填能点)。安全边界由**后端**按 permission_mode
    把关:read_only / default 模式下 ui_set_field 直接拒绝(见 _t_ui_set_field
    的权限闸门)。确定性缝优先后端 —— 前端 ui-atlas.js 的 setField 实际零检查,
    绝不能把它当安全边界(旧注释误称"由前端在 onSet 检查",已纠正)。
"""
from __future__ import annotations

from typing import Any

from tools_dsl.command_dispatcher import ToolSpec, get_registry


def _current_permission_mode(user_id: int) -> str:
    """读当前用户活跃存档的权限模式(参照 apply_ops 现行读法:
    state.data["permissions"]["mode"],经 _normalize_permission_mode 归一)。

    ui_set_field 是 user scope 工具,executor 只拿 (user_id, args) 没有 state,
    故复用 app._ensure_loaded 取当前档 GameState(与 console_assistant 路由的
    state_provider 同源)。ensure_gm=False 避免顺带装 GM。

    拿不到状态时返回 "full_access"(fail-open):UI 代填不是游戏态写入,拿不到
    模式(如非游戏页 / 尚无存档)时不阻断正常代填;真读到 read_only/default 才拒。
    单测可 monkeypatch 本函数控制模式。"""
    try:
        import app as _ui
        from state.permissions import _normalize_permission_mode
        state = _ui._ensure_loaded({"id": int(user_id)}, ensure_gm=False)
        return _normalize_permission_mode(
            (state.data.get("permissions") or {}).get("mode", "full_access")
        )
    except Exception:
        return "full_access"


# 允许所有 origin 调用 — 因为这些工具本质是"代用户点鼠标"。
# 安全边界由后端 permission_mode 把关(见 _t_ui_set_field:read_only/default 拒绝),
# 不指望前端(ui-atlas.js 零检查)。
_UI_ORIGINS = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat", "llm_chat_json_op",
    "console_assistant",
})
# ui_click 是 destructive=True 工具 — 安全不变量: destructive 工具不允许 llm_chat。
# llm 可通过 console_assistant / llm_set / ui_button 触发点击,但不能通过 llm_chat 直接调。
_UI_CLICK_ORIGINS = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat_json_op",
    "console_assistant",
})


def _t_ui_describe_page(user_id: int, args: dict) -> str:
    """返回当前页面 UI atlas snapshot.

    实际 atlas 由前端 ui-atlas.js 维护, 通过 pageContext.ui_atlas 推到 console_assistant,
    所以 atlas 已经在 LLM 看到的 system prompt 里。这个工具主要是给 LLM 一个
    "我要看一眼当前页面" 的语义入口, 实际返回是 ack 字符串提示。
    """
    return ("The current page's UI Atlas has been injected into the context via pageContext.ui_atlas. "
            "Read the ui_atlas section in the system prompt directly; no need to request it again. "
            "The atlas contains: page (route), open_modals (open dialogs), "
            "forms (fields and their current values), top_actions (clickable buttons).")


def _t_ui_set_field(user_id: int, args: dict) -> str | dict[str, Any]:
    """填某 form 的某字段。返回特殊 __ui_action__ payload 让 console_assistant
    转成 SSE event 推到前端。"""
    form_id = str(args.get("form_id") or "").strip()
    field_key = str(args.get("field_key") or "").strip()
    value = args.get("value")
    if not form_id:
        return "Failed: form_id is required (take it from ui_atlas.forms[].id)"
    if not field_key:
        return "Failed: field_key is required (take it from ui_atlas.forms[].fields[].key)"
    if value is None:
        return "Failed: value is required (string / number / boolean)"
    # 权限闸门(后端权威,不指望前端 ui-atlas.js 零检查):read_only / default 模式
    # 下不允许助手代填表单字段。read 法参照 apply_ops(state.permissions.mode)。
    # 失败串走 dispatcher「失败: ...」惯例(_RESULT_FAILURE_RE 识别)。
    mode = _current_permission_mode(user_id)
    if mode in ("read_only", "default"):
        return (
            f"Failed: the current permission mode is {mode}, which does not allow the assistant to fill in form fields (ui_set_field). "
            f"Switch to full access (full_access), or fill in the field on the page yourself."
        )
    # 返回的 dict 会被 console_assistant 主循环识别为 UI action
    return {
        "__ui_action__": "set_field",
        "form_id": form_id,
        "field_key": field_key,
        "value": value,
        "ack": f"Asked the front end to fill field '{field_key}' = {value!r} on '{form_id}'",
    }


def _t_ui_click(user_id: int, args: dict) -> str | dict[str, Any]:
    """点击某 form 的某 action 按钮 (或 global 区按钮)。

    form_id="global" 时 action_label 是 page-level 按钮 (如 "新游戏"、"导入剧本");
    其他 form_id 是 modal 内的按钮 (如 "创建并进入"、"取消")。
    """
    form_id = str(args.get("form_id") or "").strip()
    action_label = str(args.get("action_label") or "").strip()
    if not form_id:
        return "Failed: form_id is required (use the modal id for buttons inside a modal, 'global' for page-level buttons)"
    if not action_label:
        return "Failed: action_label is required (take it from ui_atlas.forms[].top_actions[].label)"
    return {
        "__ui_action__": "click",
        "form_id": form_id,
        "action_label": action_label,
        "ack": f"Asked the front end to click '{action_label}' on '{form_id}'",
    }


def register_ui_action_tools() -> None:
    """task 109b: 注册到全局 dispatcher。在 ensure_registered() 里调一次。"""
    reg = get_registry()

    reg.register(ToolSpec(
        name="ui_describe_page",
        description=(
            "Inspect the current page's UI structure (forms / fields / buttons). "
            "The actual atlas is already injected into the system prompt via pageContext; "
            "just read the ui_atlas section directly instead of calling this tool every time."
        ),
        input_schema={"type": "object", "properties": {}, "required": []},
        executor=_t_ui_describe_page,
        scope="user",
        origins=_UI_ORIGINS,
        destructive=False,
        intent_keywords=("ui", "page", "describe", "页面", "atlas"),
    ))

    reg.register(ToolSpec(
        name="ui_set_field",
        description=(
            "Fill in a field of a form on the current page (types into an input/select/textarea on the user's behalf). "
            "form_id and field_key must come from ui_atlas.forms[*].id / .fields[*].key; "
            "never make them up. Prefer the label text as field_key (e.g. 'Save name'). "
            "value is a string / number / boolean. For a select field you may pass the option label or value."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "form_id":   {"type": "string", "description": "The form's id, from ui_atlas"},
                "field_key": {"type": "string", "description": "The field's key (usually its label text)"},
                "value":     {"description": "Value to fill in (string/number/bool)"},
            },
            "required": ["form_id", "field_key", "value"],
        },
        executor=_t_ui_set_field,
        scope="user",
        origins=_UI_ORIGINS,
        destructive=False,
        intent_keywords=("fill", "set", "input", "type", "填", "填写", "输入"),
        input_examples=(
            {"form_id": "newgame", "field_key": "Save name", "value": "Fog Harbor investigation"},
            {"form_id": "newgame", "field_key": "Script", "value": "The Lighthouse Gate"},
            {"form_id": "card-edit", "field_key": "Name", "value": "Stella"},
        ),
    ))

    reg.register(ToolSpec(
        name="ui_click",
        description=(
            "Click a button on the current page (a mouse click on the user's behalf). "
            "form_id='global' is for page-level buttons (e.g. 'New game', 'Refresh'); "
            "other form_ids are for buttons inside a modal (e.g. 'Create and enter', 'Cancel'). "
            "action_label must come from ui_atlas.forms[*].top_actions[*].label. "
            "destructive=true because it may trigger irreversible actions such as submit/create/delete - "
            "in default permission mode it first yields confirmation_required so the user can confirm."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "form_id":      {"type": "string"},
                "action_label": {"type": "string"},
            },
            "required": ["form_id", "action_label"],
        },
        executor=_t_ui_click,
        scope="user",
        origins=_UI_CLICK_ORIGINS,  # destructive=True 不允许 llm_chat (安全不变量)
        destructive=True,  # 点提交按钮可能产生不可逆动作 (创建存档/删存档等)
        intent_keywords=("click", "submit", "press", "create", "confirm", "点", "提交", "创建", "确定"),
        input_examples=(
            {"form_id": "newgame", "action_label": "Create and enter"},
            {"form_id": "global", "action_label": "New game"},
            {"form_id": "card-edit", "action_label": "Save"},
        ),
    ))
