"""
_arg_guards.py — tools_dsl 共享参数校验小工具(DRY 收口)。

`require_int_arg`:「拒绝」环的整数参数硬校验闸。收口原先散落在
command_tools_{saves,anchors,phase,imports,persona,misc}.py 里逐字重复的:

    if not isinstance(x, (int, float, str)) or not str(x).lstrip("-").isdigit():
        return "失败: <label> 必须整数"

三环严格区分,不可混用:
  · 「拒绝」环(本函数):非整数 → 返回失败字符串,调用点立即 return 中断。
  · 「纠偏」环:command_dispatcher._coerce_declared_integers(按 schema 就地纠偏)。
  · 「软转」环:command_tools_kb._int(非整数 → None,继续执行)。

接受/拒绝判定与原闸逐位一致 —— 沿用 `str(v).lstrip("-").isdigit()`,故:
  · 合法:int、以及去掉前导 '-' 后全为数字的 str(如 "42" / "-5" / "007")。
  · 拒绝:float(如 30.5 / 30.0,因 str(30.0).isdigit() == False)、None、其它类型、
    以及任何非纯数字 str —— 与原行为完全相同。
"""
from __future__ import annotations


def require_int_arg(value, label, *, fail=None):
    """整数参数硬校验闸。

    合法返回 int(value);非法返回失败字符串。调用点惯例:

        _chk = require_int_arg(args.get("save_id"), "save_id")
        if isinstance(_chk, str):
            return _chk

    失败串默认取 f"失败: {label} 必须整数";个别点措辞不同(如 saves 用
    「必须是整数」/「必填且必须是整数」)时用 fail= 整句覆盖,逐字保持原文案。
    """
    if not isinstance(value, (int, float, str)) or not str(value).lstrip("-").isdigit():
        return fail if fail is not None else f"Failed: {label} must be an integer"
    return int(value)
