"""context_engine.projection — 进度感知角色卡 · 方案 C 运行时投影(Phase 2)。

治本「序章看最终态 / 敌写成友 / 剧透」:不落多版本卡、不改写库 schema,而是 GM 取卡时
从 **chapter_facts**(逐章逐态的现成证据,被 resolve 压扁丢弃前的原料)按玩家当前进度
**投影**出「该进度下的角色态」,替换/补充单态 persona 里易剧透的字段
(identity / current_status / relationships)。

确定性 + 防剧透铁律:
  · none       : 严格 ≤progress(只合成已揭示章的态)
  · partial    : ≤progress + 近未来缓冲(穿越者模糊预知,温和)
  · omniscient : 取全书最终态(= 现状,不 gate)
  · progress=None 且非 omniscient → 兜到第 1 章(最严格,绝不剧透),与 _save_ctx / retrieval 一致
  · 投影不出 / 无数据 / 出错 → 返回 None,调用方回退原单态卡(绝不给空卡、不破回合)

数据形状兼容两条提取路径:
  · LLM(per_chapter): characters[]={surface/canonical_guess/full_name/identity/background/status/type},
                       relationships[]={from,to,kind,evidence}
  · 启发式(chapter_fact_indexer): characters[]={name,count}, relationships[]={source,target,note}
"""
from __future__ import annotations

from typing import Any

# partial 近未来缓冲章数(与 loaders._PARTIAL_LOOKAHEAD_CHAPTERS 同语义,温和放宽)。
_PARTIAL_LOOKAHEAD_CHAPTERS = 20

# 轻量进程内缓存:键 (script_id, name_key, progress, mode) → 投影 dict|None。
# 避免每回合每卡重算 chapter_facts。容量软上限,超过即清(无需精细 LRU)。
_PROJECTION_CACHE: dict[tuple, Any] = {}
_PROJECTION_CACHE_MAX = 4096


def clear_projection_cache() -> None:
    """测试 / 重建后清缓存。"""
    _PROJECTION_CACHE.clear()


def _ceiling_for(progress_chapter: int | None, mode: str) -> int | None:
    """该 mode 下投影可见的章节天花板。omniscient → None(不 gate / 全书)。"""
    mode = (mode or "none").lower()
    if mode == "omniscient":
        return None
    prog = int(progress_chapter) if progress_chapter is not None else 1
    if mode == "partial":
        prog += _PARTIAL_LOOKAHEAD_CHAPTERS
    return prog


def _char_name_fields(entity: dict) -> list[str]:
    """一个 chapter_facts 角色项可能用来匹配的所有名字(两条路径并集)。"""
    names: list[str] = []
    for k in ("canonical_guess", "name", "surface", "full_name"):
        v = (entity.get(k) or "").strip() if isinstance(entity.get(k), str) else ""
        if v:
            names.append(v)
    aliases = entity.get("aliases_in_chapter") or entity.get("aliases") or []
    if isinstance(aliases, list):
        names.extend(str(a).strip() for a in aliases if str(a).strip())
    return names


def _name_matches(entity: dict, name_or_key: str, aliases: list[str]) -> bool:
    target = {name_or_key.strip(), *[str(a).strip() for a in (aliases or []) if str(a).strip()]}
    target.discard("")
    if not target:
        return False
    cand = set(_char_name_fields(entity))
    return bool(cand & target)


def _rel_endpoints(rel: dict) -> tuple[str, str]:
    """关系两端(兼容 from/to 与 source/target)。"""
    a = (rel.get("from") or rel.get("source") or "").strip() if isinstance(rel, dict) else ""
    b = (rel.get("to") or rel.get("target") or "").strip() if isinstance(rel, dict) else ""
    return a, b


def project_character_state(
    db,
    script_id: int,
    name_or_key: str,
    progress_chapter: int | None,
    foreknowledge_mode: str = "none",
    *,
    aliases: list[str] | None = None,
    use_cache: bool = True,
) -> dict[str, Any] | None:
    """从 chapter_facts 投影出该角色在当前进度下的态。

    返回 {identity, background, current_status, relationships, _source_chapter} 或 None。
    relationships = [{"other": str, "kind": str, "chapter": int}],「最后一次」kind 胜出
    (敌对→盟友逐章演进,取 ≤ceiling 的最近一次)。identity / background 取「最近非空」
    (≤ceiling 各章逐渐丰富,后章覆盖前章空值)。None = 无任何可投影数据 → 调用方回退原卡。
    """
    name_or_key = (name_or_key or "").strip()
    if not name_or_key or not script_id:
        return None
    aliases = aliases or []
    mode = (foreknowledge_mode or "none").lower()
    if mode not in ("none", "partial", "omniscient"):
        mode = "none"
    ceiling = _ceiling_for(progress_chapter, mode)

    cache_key = (int(script_id), name_or_key, ceiling, mode)
    if use_cache and cache_key in _PROJECTION_CACHE:
        return _PROJECTION_CACHE[cache_key]

    try:
        if ceiling is None:  # omniscient = 全书最终态
            rows = db.execute(
                "select chapter, characters, relationships from chapter_facts "
                "where script_id=%s order by chapter asc",
                (int(script_id),),
            ).fetchall()
        else:
            rows = db.execute(
                "select chapter, characters, relationships from chapter_facts "
                "where script_id=%s and chapter <= %s order by chapter asc",
                (int(script_id), int(ceiling)),
            ).fetchall()
    except Exception:
        return None  # 投影读失败 → 回退原卡,绝不破回合

    identity = ""
    background = ""
    current_status = ""
    # 关系:key=对端名,value=(kind, chapter)。后章覆盖前章 → 敌→友逐章演进取最近态。
    rel_latest: dict[str, tuple[str, int]] = {}
    source_chapter = 0

    for row in (rows or []):
        if isinstance(row, dict):
            cnum = row.get("chapter")
            characters = row.get("characters")
            relationships = row.get("relationships")
        else:
            cnum, characters, relationships = row[0], row[1], row[2]
        try:
            cnum = int(cnum)
        except (TypeError, ValueError):
            cnum = 0

        # 1) 角色态:本章命中该角色 → 「最近非空」合成 identity/background/status。
        if isinstance(characters, list):
            for ent in characters:
                if not isinstance(ent, dict):
                    continue
                if not _name_matches(ent, name_or_key, aliases):
                    continue
                idv = (ent.get("identity") or "").strip() if isinstance(ent.get("identity"), str) else ""
                bgv = (ent.get("background") or "").strip() if isinstance(ent.get("background"), str) else ""
                stv = (ent.get("status") or ent.get("current_status") or "")
                stv = stv.strip() if isinstance(stv, str) else ""
                # status 字段在 LLM 路径是 linked|proposed(消歧标记,非角色现状),不当现状用。
                if stv in ("linked", "proposed"):
                    stv = ""
                if idv:
                    identity = idv
                    source_chapter = max(source_chapter, cnum)
                if bgv:
                    background = bgv
                    source_chapter = max(source_chapter, cnum)
                if stv:
                    current_status = stv
                    source_chapter = max(source_chapter, cnum)

        # 2) 关系:本章涉及该角色的关系 → 记最近一次 kind(后章覆盖)。
        if isinstance(relationships, list):
            for rel in relationships:
                if not isinstance(rel, dict):
                    continue
                a, b = _rel_endpoints(rel)
                kind = (rel.get("kind") or rel.get("note") or "").strip()
                if not kind:
                    continue
                me = {name_or_key, *[str(x).strip() for x in aliases]}
                me.discard("")
                other = ""
                if a in me and b:
                    other = b
                elif b in me and a:
                    other = a
                if not other:
                    continue
                rel_latest[other] = (kind, cnum)
                source_chapter = max(source_chapter, cnum)

    relationships_out = [
        {"other": other, "kind": kind, "chapter": ch}
        for other, (kind, ch) in sorted(rel_latest.items(), key=lambda kv: -kv[1][1])
    ]

    if not identity and not background and not current_status and not relationships_out:
        result = None  # 无任何可投影数据 → 回退原单态卡
    else:
        result = {
            "identity": identity,
            "background": background,
            "current_status": current_status,
            "relationships": relationships_out,
            "_source_chapter": source_chapter,
        }

    if use_cache:
        if len(_PROJECTION_CACHE) >= _PROJECTION_CACHE_MAX:
            _PROJECTION_CACHE.clear()
        _PROJECTION_CACHE[cache_key] = result
    return result


def apply_projection_to_card(card: dict[str, Any], projected: dict[str, Any] | None) -> dict[str, Any]:
    """把投影态叠加到单态卡上(只覆盖易剧透字段,非空才覆盖;关系拼成一行 current_status 后缀)。

    投影=None → 原卡原样返回(不破)。返回新 dict(不原地改输入卡)。
    """
    if not projected:
        return card
    out = dict(card)
    if projected.get("identity"):
        out["identity"] = projected["identity"]
    if projected.get("background"):
        out["background"] = projected["background"]
    rel_text = "; ".join(
        f"toward {r['other']}: {r['kind']}" for r in (projected.get("relationships") or [])[:6]
        if r.get("other") and r.get("kind")
    )
    # 防剧透关键:一旦有投影,**不保留原卡的 current_status**(那是全书最终态,
    # 可能直接剧透「敌→友」结局)。只用投影出的进度内现状 + 进度内关系。
    # 没投影现状也没关系 → 留空(由 _format_card 渲染成「未记录」,不剧透)。
    status_parts = []
    if projected.get("current_status"):
        status_parts.append(projected["current_status"])
    if rel_text:
        status_parts.append(f"Relationships: {rel_text}")
    out["current_status"] = " · ".join(status_parts)
    out["_projected_chapter"] = projected.get("_source_chapter", 0)
    return out
