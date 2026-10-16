"""platform_app.workspace.snapshot — 新存档【初始 state 快照】构建(包化搬家)。

⚠️ 出生点/进度信号病灶区:_build_initial_snapshot 逐字搬家,含 worldline.progress_chapter
写入、_apply_script_opening 从锚点章节派生情境、_scrub_berlin_default 清 DEFAULT_STATE。
纯机械搬家,逐字复制,零行为变化(仅在函数体内 lazy 相对 import 加深一层 . -> ..)。
"""
from __future__ import annotations

import re
from typing import Any

from state.core import _extract_secret_sections, _strip_secret_sections

from ..db import connect


def _build_initial_snapshot(
    user_id: int,
    script_id: int,
    new_card: dict[str, Any] | None,
    character: dict[str, Any] | None,
    *,
    birthpoint: dict[str, Any] | None = None,
    identity: dict[str, Any] | None = None,
    story_intent: str | None = None,
    player_origin: str | None = None,
    identity_known: bool | None = None,
) -> dict[str, Any]:
    """根据 UI 选择构造新存档的初始 state。任何异常退到空白快照。"""
    try:
        from state import GameState
        state = GameState.new()
    except Exception:
        return {"history": [], "turn": 0}

    name = role = background = ""
    # task 91: 没传 new_card/character 时,默认拿用户的"默认 persona",
    # 没有就回退到最近的 user_character_card。避免新建存档总是空玩家。
    # 修(实锤:菲莉丝/周镇北档 player 被酒馆导入的芙兰朵露卡顶替):调用方给了完整
    # identity 却没显式选角色卡时,identity 就是玩家本体 —— 不该再落 task 91 的
    # 「默认 persona」回退去抓卡库里无关的最近一张卡。
    if (not isinstance(new_card, dict) and not isinstance(character, dict)
            and isinstance(identity, dict) and str(identity.get("name") or "").strip()):
        name = str(identity.get("name") or "").strip()
        role = str(identity.get("role") or "").strip()
        background = str(identity.get("background") or "").strip()
    elif not isinstance(new_card, dict) and not isinstance(character, dict):
        try:
            from .. import user_cards as _ucards
            personas = _ucards.list_personas(user_id).get("items", [])
            default_p = next((p for p in personas if p.get("is_default")), None) or (personas[0] if personas else None)
            if default_p:
                character = {"kind": "persona", "id": default_p.get("id")}
            else:
                cards = _ucards.list_user_cards(user_id).get("items", [])
                if cards:
                    character = {"kind": "user_card", "id": cards[0].get("id")}
        except Exception:
            pass
    # task 137: 详细角色卡字段（外貌/性格/语气/别名），setup_player 后再单独写入
    # task 138: secrets 字段 *不再* 放入 player namespace,改成 _extra_private 收集到
    # player_private.secrets。同时把 personality/appearance/background 里的 ## 秘密 段
    # 用 _extract_secret_sections 抽走 → player_private.secrets;原字段用 _strip_secret_sections
    # 剥离后保留 NPC 可观察部分。这样 short_summary 注入 GM prompt 时秘密物理上不存在。
    _extra_card_fields: dict[str, str] = {}
    _extra_private_secrets: list[str] = []

    def _absorb_card_secrets(card: dict[str, Any]) -> None:
        """从一张 user_card / script_card / persona dict 抽出秘密 → _extra_private_secrets,
        同时把 personality/appearance/background 里的秘密段 strip 后写回 _extra_card_fields。
        通用底座 — 不依赖具体剧本字段名。"""
        # 1. 直接的 secrets 字段(角色卡 schema 里独立的"秘密"字段)→ player_private
        _sec_raw = str(card.get("secrets") or "").strip()
        if _sec_raw and _sec_raw not in _extra_private_secrets:
            _extra_private_secrets.append(_sec_raw)
        # 2. personality / appearance / background 里嵌入的 ## 秘密 / ## 隐藏 / ## 元知识 …段
        #    → 抽到 player_private.secrets, 原字段保留 strip 后的剩余
        for _f in ("appearance", "personality", "background"):
            _v = str(card.get(_f) or "").strip()
            if not _v:
                continue
            _hidden_sections = _extract_secret_sections(_v)
            for _h in _hidden_sections:
                if _h and _h not in _extra_private_secrets:
                    _extra_private_secrets.append(_h)
            _stripped = _strip_secret_sections(_v)
            if _stripped:
                _extra_card_fields[_f] = _stripped
        # 3. speech_style / aliases 一般 NPC 可观察,直接保留
        for _f in ("speech_style", "aliases"):
            _v = str(card.get(_f) or "").strip()
            if _v:
                _extra_card_fields[_f] = _v

    if isinstance(new_card, dict):
        name = str(new_card.get("name") or "").strip()
        role = str(new_card.get("role") or "").strip()
        # background 也 strip 一遍秘密段(玩家在向导里手填可能也写 ## 秘密)
        _new_bg = str(new_card.get("background") or "").strip()
        if _new_bg:
            for _h in _extract_secret_sections(_new_bg):
                if _h and _h not in _extra_private_secrets:
                    _extra_private_secrets.append(_h)
            background = _strip_secret_sections(_new_bg)
        else:
            background = ""
    elif isinstance(character, dict):
        # best-effort：从已有 persona / character card 取 name + role + background
        kind = str(character.get("kind") or "").strip()
        cid = character.get("id")
        try:
            cid_int = int(cid) if cid is not None else None
        except (TypeError, ValueError):
            cid_int = None
        if cid_int is not None:
            try:
                if kind == "persona":
                    from .. import user_cards as _ucards
                    p = _ucards.get_persona(user_id, cid_int) or {}
                    name = str(p.get("name") or "").strip()
                    role = str(p.get("role") or "").strip()
                    _p_bg = str(p.get("background") or "").strip()
                    for _h in _extract_secret_sections(_p_bg):
                        if _h and _h not in _extra_private_secrets:
                            _extra_private_secrets.append(_h)
                    background = _strip_secret_sections(_p_bg) if _p_bg else ""
                elif kind == "user_card":
                    from .. import user_cards as _ucards
                    c = _ucards.get_user_card(user_id, cid_int) or {}
                    name = str(c.get("name") or "").strip()
                    role = str(c.get("identity") or "").strip()
                    # background 优先取 personality（详细设定），其次 appearance
                    _bg_src = str(c.get("personality") or c.get("appearance") or "").strip()
                    background = _strip_secret_sections(_bg_src) if _bg_src else ""
                    _absorb_card_secrets(c)
                elif kind == "script_card":
                    from .. import knowledge as _know
                    c = _know.get_character_card(user_id, script_id, cid_int) or {}
                    name = str(c.get("name") or "").strip()
                    role = str(c.get("identity") or "").strip()
                    _bg_src = str(c.get("personality") or c.get("appearance") or "").strip()
                    background = _strip_secret_sections(_bg_src) if _bg_src else ""
                    _absorb_card_secrets(c)
                    # task 114: LLM 经常用 script_card_id 传了 user_card_id (混淆),
                    # 找不到时自动兜底到 user_card 表 — 因为 user_card 跨 script 共享,
                    # 给空白 player 强过让用户开局看到 "—"。
                    if not name:
                        from .. import user_cards as _ucards
                        uc = _ucards.get_user_card(user_id, cid_int) or {}
                        if uc:
                            name = str(uc.get("name") or "").strip()
                            role = str(uc.get("identity") or "").strip()
                            _bg_src = str(uc.get("personality") or uc.get("appearance") or "").strip()
                            background = _strip_secret_sections(_bg_src) if _bg_src else ""
                            _absorb_card_secrets(uc)
            except Exception:
                pass

    if name or role or background:
        try:
            state.setup_player(name or "Nameless", role or "Unspecified", background or "(no background)")
        except Exception:
            pass
        # #6 代入去重: script_card = 玩家代入原作已有角色。登记 player↔NPC 绑定
        # (player.aliases + player_meta.pov_replaces + bound_npc_card_id),让 GM 上下文
        # (_active_character_cards)把这张同名 NPC 卡视为玩家本人、不再当独立 NPC 注入,
        # 消除"代入原作角色后出现两个相同角色"。用函数参数 character 重判(局部 kind/cid 此处不在作用域)。
        if isinstance(character, dict) and str(character.get("kind") or "").strip() == "script_card" and name:
            try:
                _pdata = getattr(state, "data", state)
                _player = _pdata.setdefault("player", {})
                _al = _player.get("aliases") or []
                if isinstance(_al, str):
                    _al = [a.strip() for a in _al.split(",") if a.strip()]
                if name not in _al:
                    _al.append(name)
                _player["aliases"] = _al
                try:
                    _player["bound_npc_card_id"] = int(character.get("id")) if character.get("id") is not None else None
                except (TypeError, ValueError):
                    pass
                _meta = _pdata.setdefault("player_meta", {})
                _pov = _meta.get("pov_replaces") or []
                if name not in _pov:
                    _pov.append(name)
                _meta["pov_replaces"] = _pov
            except Exception:
                pass

    # task 137: 把详细角色卡字段写入 state.data["player"]（供 short_summary → GM 读取）
    # task 138: 已经在 _absorb_card_secrets 里 strip 过秘密段,_extra_card_fields 里
    # 只剩 NPC 可观察部分;secrets 字段不再被 _absorb 收集进 _extra_card_fields,
    # 不会污染 player namespace。
    if _extra_card_fields:
        try:
            player = state.data.setdefault("player", {})
            for _f, _v in _extra_card_fields.items():
                player[_f] = _v
        except Exception:
            pass

    # task 138: 把从角色卡 secrets 字段 + ## 秘密 段抽出来的内容写到 player_private.secrets。
    # player_private namespace 永远不进 GM system prompt(short_summary 显式排除)。
    if _extra_private_secrets:
        try:
            pp = state.data.setdefault("player_private", {})
            sec_list = pp.setdefault("secrets", [])
            for _s in _extra_private_secrets:
                if _s and _s not in sec_list:
                    sec_list.append(_s)
        except Exception:
            pass

    # task 34：DEFAULT_STATE 是 MuMuAINovel 柏林剧情的硬编码（time=图卢兹失守后翌日，柏林、
    # current_location=柏林哈布斯堡庄园附近、known_events=宴会/图卢兹/蛇信、
    # current_objective=观察柏林局势...）。从导入剧本创建 save 时必须用 script 的首章覆盖，
    # 否则用户看到的开场是别人剧本的状态。
    # 入场选了出生锚点 → 情境字段(地点/目标/known_events/开场原文预览)从【锚点章节】派生,
    # 否则 _apply_script_opening 恒锁第 1 章,与下面 birthpoint 改写的 world.time 自相矛盾,
    # GM 仍从第一章开场(用户实测 bug)。
    _prefer_chapter = None
    if isinstance(birthpoint, dict):
        try:
            _cmin = birthpoint.get("chapter_min")
            if _cmin is not None:
                _prefer_chapter = int(_cmin)
        except (TypeError, ValueError):
            _prefer_chapter = None
    try:
        _apply_script_opening(state, user_id, script_id, prefer_chapter=_prefer_chapter)
    except Exception:
        # 任何解析失败都不应该让 create_save 整个崩；退到 user/角色卡已写入的最小可玩 state。
        pass

    # 入场选出生点：覆盖 world.timeline / world.time（优先级高于 _apply_script_opening）
    if isinstance(birthpoint, dict):
        try:
            phase_label = str(birthpoint.get("phase_label") or "").strip()
            story_time_label = str(birthpoint.get("story_time_label") or "").strip()
            chapter_min = birthpoint.get("chapter_min")
            chapter_max = birthpoint.get("chapter_max")
            world = state.data.setdefault("world", {})
            timeline = world.setdefault("timeline", {})
            if phase_label:
                timeline["current_phase"] = phase_label
            if story_time_label:
                world["time"] = story_time_label
                timeline["current_label"] = story_time_label
            if chapter_min is not None and chapter_max is not None:
                timeline["anchor_chapter_range"] = [int(chapter_min), int(chapter_max)]
            # 根因(#62/#63/#66/#67 选出生点仍从序章 / 原著正文+对话消失):出生点过去只写进
            # world.timeline,没灌进【进度信号】worldline.progress_chapter → retrieve_context 的
            # _progress_chapter 默认 1(reveal 闸锁序章、ch2+ 角色被藏)、get_progress_window 退回
            # [1,30]、ongoing 回合贴原著注入序章原文。出生点是玩家显式选择的【确定性起始章】
            # (区别于 story_time_label 猜章,见 retrieval.py:469 注释),作为进度下限写入 worldline:
            # _PRESERVE_SETTINGS_SQL 已含 progress_chapter → 跨回合 sticky;advance_progress 仍可 max 前推。
            if chapter_min is not None:
                wl = state.data.setdefault("worldline", {})
                try:
                    wl["progress_chapter"] = max(int(wl.get("progress_chapter") or 0), int(chapter_min))
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass

    # v27: 入场初始身份。身份卡是「角色卡之上的定位 overlay」,*不再覆盖* player.name/role —
    # 那两个字段永远来自角色卡(身份脱离角色,无关具体人物)。
    # - identity.role/background → state_snapshot.player.identity 子对象 (overlay 运行时副本) +
    #   player.identity_role_desc (state/core short_summary 读的旧字段,保持兼容)
    # - identity.name 视为「代号/化名」,仅作为 identity.name_label 记录;玩家姓名仍是角色卡名字
    # - 没传 identity 时,player 完全等同于角色卡(用户明确接受此默认)
    # - 数据库侧:身份卡作为独立行存进 identity_cards 表 + save_character_identities 绑定,
    #   见 create_save() 在 insert game_saves 之后的处理
    if isinstance(identity, dict):
        try:
            id_name_label = str(identity.get("name") or "").strip()
            id_role = str(identity.get("role") or "").strip()
            id_background = str(identity.get("background") or "").strip()
            id_source = str(identity.get("source") or "custom").strip() or "custom"
            player = state.data.setdefault("player", {})
            overlay: dict[str, Any] = {
                "name_label": id_name_label,
                "role": id_role,
                "background": id_background,
                "source": id_source,
            }
            player["identity"] = overlay
            if id_background:
                player["identity_role_desc"] = id_background
            # 迭代(#5 POV 命名):从原著角色(source=npc_card)= 魂穿进该原著人物的身体 → 玩家在世界里
            # 就是这个人。名字/身份用原著人物(罗辑),原角色卡名作为「灵魂本名」记入 display_name(罗辑(阿米娅))
            # + aliases,供 UI 显示与提到原卡名时映射回玩家。普通 custom/ai 身份(只是套在卡上的社会定位)
            # 仍保留角色卡名,不改原设计。
            # 仅「灵魂穿越/双魂同体」时玩家占据/共体该原住民肉身 → 玩家名 = 该原住民(罗辑)。
            # 「整体穿越」无本地身份、「本世界人」你本就是所选角色卡(阿米娅)→ 都不改名(身份卡只叠加
            # role/background),否则会出现「阿米娅又叫罗辑」的双重身份(用户反馈)。
            _po_norm = "soul" if str(player_origin or "").lower() == "isekai" else str(player_origin or "").lower()
            if id_source == "npc_card" and id_name_label and _po_norm in ("soul", "dual"):
                _card_name = str(player.get("name") or "").strip()
                player["name"] = id_name_label  # 罗辑
                if id_role:
                    player["role"] = id_role
                if id_background:
                    player["background"] = id_background
                if _card_name and _card_name != id_name_label:
                    overlay["card_name"] = _card_name           # 阿米娅(灵魂本名)
                    player["display_name"] = f"{id_name_label} ({_card_name})"  # 罗辑(阿米娅)
                    _al = player.setdefault("aliases", [])
                    if _card_name not in _al:
                        _al.append(_card_name)
        except Exception:
            pass

    # 兜底:角色卡也没传时占位(保留旧行为,避免下游 NPE)
    try:
        player = state.data.setdefault("player", {})
        if not player.get("name"):
            player["name"] = "Nameless"
        if not player.get("role"):
            player["role"] = "Unspecified"
        if not player.get("background"):
            player["background"] = "(no background)"
    except Exception:
        pass

    if story_intent:
        try:
            from datetime import datetime as _dt
            # task 138: 主存到 player_private.story_intent(NPC / GM 看不到)。
            # user_variables.story_intent 仍写一份保留旧代码 dual-read 兼容,但 short_summary
            # 已经显式跳过该 key,不会注入到 GM prompt。后续把这条 dual-write 删掉前,
            # 任何读 worldline.user_variables.story_intent 的地方应该改读 player_private.story_intent。
            pp = state.data.setdefault("player_private", {})
            pp["story_intent"] = str(story_intent)
            variables = state.data.setdefault("worldline", {}).setdefault("user_variables", {})
            variables["story_intent"] = {
                "value": story_intent,
                "source": "user:new_game_wizard",
                "locked": False,
                "turn": 0,
                "updated_at": _dt.now().isoformat(timespec="seconds"),
            }
        except Exception:
            pass

    # player_origin: 玩家定位类型 (isekai = 穿越者 / native = 原作角色)。
    # 持久化到 state.player.player_origin,GM context provider 据此注入「穿越者特殊规则」,
    # 前端 status panel 显示穿越者徽章。saves wizard 显式提供,与身份卡 overlay 正交。
    # 出身 4 档:soul(魂穿)/body(肉穿)/dual(一体双魂)/native(彻底扮演)。旧值 isekai→soul 兼容。
    _po = str(player_origin or "").lower()
    if _po == "isekai":
        _po = "soul"
    if _po in ("soul", "body", "dual", "native"):
        _pnode = state.data.setdefault("player", {})
        _pnode["player_origin"] = _po
        # identity_known 只在实际挂了身份卡时有意义。
        if _po != "body" and isinstance(identity, dict) and isinstance(identity_known, bool):
            _pnode["identity_known"] = identity_known

    # Bug 5 fix: 新建存档时把用户偏好里的 perm.default_mode 注入 state.permissions.mode。
    # 偏好由 settings.jsx PermSection 通过 save("default_mode", val) 写入
    # user_preferences 表，key="perm.default_mode"。
    # 若无偏好或读取失败，保留 GameState.new() 的默认值（"review"）。
    try:
        with connect() as _pdb:
            _pref_row = _pdb.execute(
                "select preferences from user_preferences where user_id = %s",
                (user_id,),
            ).fetchone()
        _prefs = dict(_pref_row["preferences"]) if _pref_row else {}
        _default_mode = _prefs.get("perm.default_mode") or _prefs.get("default_perm_mode")
        _VALID_MODES = {"default", "review", "full_access"}
        if _default_mode and _default_mode in _VALID_MODES:
            state.data.setdefault("permissions", {})["mode"] = _default_mode
    except Exception:
        pass

    return state.data


# task 34 + task 40：从首章内容解析的几个 inline 元数据正则。
# 真实导入后 chapter_splitter.clean_text 会把换行折叠成空格，所以正则不能再要求 ^...$ 行起止。
# 形态示例（一行内连缀）："...灯塔。  当前地点：雾港码头。 当前目标：确认...灯塔星门。 时间锚点：申时三刻。"
# 用 [^。\n；;]+ 直到下一个句号/换行/分号作为 value 边界。
_OPENING_LOCATION_RE = re.compile(r"(?:当前地点|地点)\s*[:：]\s*([^。\n；;]+)")
_OPENING_OBJECTIVE_RE = re.compile(r"(?:当前目标|主线目标|目标)\s*[:：]\s*([^。\n；;]+)")
_OPENING_TIME_RE = re.compile(r"(?:时间锚点|时刻|时间)\s*[:：]\s*([^。\n；;]+)")


def _is_doc_title_only(content: str, title: str) -> bool:
    """判断这一章是不是『纯文档总标题 / 空内容 / 只复述标题』形态。"""
    c = (content or "").strip()
    if not c:
        return True
    if len(c) < 4:
        return True
    # 去掉 markdown # 标记，只比较剩余文字
    t = re.sub(r"^#+\s*", "", (title or "")).strip()
    bare = re.sub(r"^#+\s*", "", c).strip()
    if t and bare == t:
        return True
    return False


def _has_opening_meta(content: str) -> bool:
    """是否含至少一项 inline 元数据 (当前地点 / 当前目标 / 时间锚点) 之一。"""
    if not content:
        return False
    return bool(
        _OPENING_LOCATION_RE.search(content)
        or _OPENING_OBJECTIVE_RE.search(content)
        or _OPENING_TIME_RE.search(content)
    )


def _apply_script_opening(state: Any, user_id: int, script_id: int, prefer_chapter: int | None = None) -> None:
    """从 script_chapters 找『真实首章』（不是文档总标题/空前言），把 inline 元数据填到 state：
       当前地点 → player.current_location, world (location 同步)
       当前目标 → memory.current_objective
       时间锚点 → world.time + world.timeline (走 state.update_time，会刷 phase/anchor)
       known_events → 用首章 title + 首两行非元数据正文摘要替换默认柏林事件
       last_retrieval → 首章正文前 ~400 字作为初始检索预览
    一旦走到这里（用户从某 script 创建 save），就一定 scrub DEFAULT_STATE 里 MuMuAINovel
    柏林剧情的硬编码（柏林/图卢兹/哈布斯堡/蛇信/...），避免跨剧本污染——不论是否找到有效首章。

    task 40 修复：真实 markdown 导入后 chapter_index=1 常常是 `# 文档总标题` 单行
    （word_count=0、content=""），第 2 章才是 `## 第一章 雾港入夜` 含正文+inline meta。
    所以这里不能只 limit 1，要扫前 N 章选第一个『有 inline meta 或显著正文』的章节。

    prefer_chapter 修复（出生锚点）：玩家入场选了非首章的出生点(birthpoint) 时,情境字段
    (地点/目标/known_events/last_retrieval) 必须从【锚点章节】派生,而不是恒定第 1 章 —— 否则
    world.time 被改成锚点标签、player.current_location/known_events 仍停在第 1 章,GM 拿到自相矛盾
    的状态会照第 1 章渲染开场(用户实测:选了后段锚点仍从第一章开始)。传 prefer_chapter 时,从
    chapter_index>=prefer_chapter 起选第一个显著正文章节;该段没有章节(锚点越界)才回退到全书首章。
    """
    # 任何 save（不论 script 有无导入章节）都先 scrub DEFAULT_STATE 的柏林硬编码：
    # 用户选择了某个 script（不论是 5E 模组容器还是空白容器），就不该再继承默认小说
    # 的开场地点/事件/目标。原代码把 scrub 放在 `if not rows: return` 之后，导致 chapter_count=0
    # 的 script（例如 5E 模组容器）创建的新存档全部带柏林污染。
    _scrub_berlin_default(state)

    _first_chapters_sql = """
        select chapter_index, title, content
        from script_chapters
        where script_id = %s
        order by chapter_index asc
        limit 10
    """
    with connect() as db:
        rows = []
        if prefer_chapter and int(prefer_chapter) > 1:
            rows = db.execute(
                """
                select chapter_index, title, content
                from script_chapters
                where script_id = %s and chapter_index >= %s
                order by chapter_index asc
                limit 10
                """,
                (script_id, int(prefer_chapter)),
            ).fetchall()
        # 锚点越界 / 该段无章节 → 回退全书首章(prefer_chapter 为空时也走这里)
        if not rows:
            rows = db.execute(_first_chapters_sql, (script_id,)).fetchall()
    if not rows:
        return

    # task 40：选第一个『有 inline meta』的章节；没有 meta 时退到第一个『显著正文』章节
    chosen = None
    for row in rows:
        c = str(row.get("content") or "")
        if _is_doc_title_only(c, str(row.get("title") or "")):
            continue
        if _has_opening_meta(c):
            chosen = row
            break
    if chosen is None:
        for row in rows:
            c = str(row.get("content") or "").strip()
            if _is_doc_title_only(c, str(row.get("title") or "")):
                continue
            if len(c) >= 40:
                chosen = row
                break

    world = state.data.setdefault("world", {})
    memory = state.data.setdefault("memory", {})

    if chosen is None:
        # 全部章节都是空 / 总标题：至少用第一条 title 作为 opening 事件
        first = rows[0]
        first_title = str(first.get("title") or "").strip()
        if first_title:
            # 去掉 markdown # 前缀，让 event 文本干净
            ev_title = re.sub(r"^#+\s*", "", first_title).strip()
            world["known_events"] = [f"Opening: {ev_title}"] if ev_title else []
        return

    title = str(chosen.get("title") or "").strip()
    content = str(chosen.get("content") or "")
    # 去掉 markdown # 前缀（"## 第一章 雾港入夜" → "第一章 雾港入夜"）
    title_clean = re.sub(r"^#+\s*", "", title).strip()

    # 1) 解析三类 inline 元数据
    loc_m = _OPENING_LOCATION_RE.search(content)
    obj_m = _OPENING_OBJECTIVE_RE.search(content)
    time_m = _OPENING_TIME_RE.search(content)
    loc = (loc_m.group(1).strip() if loc_m else "")
    obj = (obj_m.group(1).strip() if obj_m else "")
    tm = (time_m.group(1).strip() if time_m else "")

    # 2) 写回 state
    if loc:
        try:
            state.update_location(loc)
        except Exception:
            state.data.setdefault("player", {})["current_location"] = loc
    if tm:
        try:
            state.update_time(tm, source="script_opening")
            tl = state.data.get("world", {}).get("timeline", {})
            if isinstance(tl, dict):
                tl["last_transition"] = None
        except Exception:
            state.data.setdefault("world", {})["time"] = tm

    if obj:
        memory["current_objective"] = obj

    # 3) known_events：『开场：<标题>』+ 首两段去元数据后的正文摘要
    # 真实 import 把换行折叠成空格 → 不能按行切，按句号切，过滤掉以"当前地点/当前目标/时间锚点"开头的句子
    sentences = [s.strip() for s in re.split(r"[。\n]+", content) if s.strip()]
    body_sents = [
        s for s in sentences
        if not re.match(r"^(?:当前地点|地点|当前目标|主线目标|目标|时间锚点|时刻|时间)\s*[:：]", s)
    ]
    events: list[str] = []
    if title_clean:
        events.append(f"Opening: {title_clean}")
    for s in body_sents[:2]:
        events.append(s if len(s) <= 80 else (s[:77] + "…"))
    if events:
        world["known_events"] = events  # 整段替换

    # 4) last_retrieval：首章前 ~400 字给检索面板/上下文做初始预览
    snippet = content.strip()
    if len(snippet) > 400:
        snippet = snippet[:400].rstrip() + "…"
    memory["last_retrieval"] = (
        f"=== Script opening · {title_clean or 'Chapter 1'} ===\n{snippet}"
        if snippet else memory.get("last_retrieval", "")
    )


# task 34：DEFAULT_STATE 是 MuMuAINovel 柏林剧情，从其他剧本创建新 save 时必须清掉
# 这些硬编码，避免新存档里出现 上个剧本 的 location/time/known_events/objective。
_DEFAULT_BERLIN_LOC = "柏林，哈布斯堡庄园附近"
_DEFAULT_BERLIN_TIME = "图卢兹失守后翌日，柏林"
_DEFAULT_BERLIN_PHASE = "柏林暗流篇"
_DEFAULT_BERLIN_OBJECTIVE_FRAG = "柏林局势"


def _scrub_berlin_default(state: Any) -> None:
    """清掉 DEFAULT_STATE 的柏林硬编码 location/time/timeline/known_events/objective。
    后续如果首章里有显式 inline meta，再覆盖回去；没有就保持安全空值。"""
    player = state.data.setdefault("player", {})
    if str(player.get("current_location") or "") == _DEFAULT_BERLIN_LOC:
        player["current_location"] = ""

    world = state.data.setdefault("world", {})
    if str(world.get("time") or "") == _DEFAULT_BERLIN_TIME:
        world["time"] = ""
    # known_events：DEFAULT_STATE 写死的 4 条柏林事件全部清掉
    default_events = {
        "宴会上调令伪造事件已曝光",
        "图卢兹战役：薇瑟帝国八位渊戮大胜，地联溃败",
        "娅赛兰决定暂留柏林",
        "蛇信在外围全程监视",
    }
    if isinstance(world.get("known_events"), list):
        world["known_events"] = [e for e in world["known_events"] if str(e) not in default_events]

    timeline = world.setdefault("timeline", {})
    if str(timeline.get("current_label") or "") == _DEFAULT_BERLIN_TIME:
        timeline["current_label"] = ""
    if str(timeline.get("current_phase") or "") == _DEFAULT_BERLIN_PHASE:
        timeline["current_phase"] = ""
    # last_transition 如果是 DEFAULT_STATE 的 None，留空
    if timeline.get("last_transition") is None:
        timeline["last_transition"] = None

    memory = state.data.setdefault("memory", {})
    if _DEFAULT_BERLIN_OBJECTIVE_FRAG in str(memory.get("current_objective") or ""):
        memory["current_objective"] = ""
