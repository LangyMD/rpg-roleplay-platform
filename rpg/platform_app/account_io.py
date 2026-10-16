"""
account_io.py — 账号级数据导出 / 导入(免部署服务 → 本地自部署 迁移)

把单个用户「全部个人数据」聚合成一个 zip 包,便于从在线托管服务迁移到本地部署实例:
  - profile.json     用户偏好(user_preferences.preferences)+ 模型 overlay(user_model_entries)
  - cards.jsonl      用户角色卡(character_cards.card_type='pc',含 persona)
  - scripts/<origin_id>.pack.zip   每个「自有」剧本 = 一个标准剧本包(复用 script_pack)
  - saves/<origin_id>.json         每份存档 = 标准存档导出(复用 save_io)

导入时:
  1. 先导入所有剧本包 → 建立 origin_script_id → new_script_id 映射
  2. 再导入存档,按映射改写 save.script_id 后落库(import_save 要求 owner 拥有目标剧本)
  3. 再导入角色卡 + 偏好 + 模型 overlay

安全 / 隐私:
  - **不含 API 密钥明文**。凭据用服务端密钥加密存储,跨实例不可解;迁移后请在本地重新填写。
  - 全程复用既有 owner 受限导入器(import_script_pack / import_save / upsert_user_card 都强制
    owner = 当前用户),不会跨用户误归属。
  - 复用各子包自身的大小 / zip 炸弹 / 列名白名单防护。
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import UTC
from typing import Any

from psycopg.types.json import Jsonb

from . import save_io, user_cards, user_models
from .api._card_dto import card_to_dto
from .db import connect, init_db
from .knowledge import script_pack

ACCOUNT_EXPORT_VERSION = 1

# 账号包整体上限(各子包另有自己的 50MB/500MB 防护)。
MAX_ACCOUNT_ZIP_BYTES = 300 * 1024 * 1024     # 压缩态 300MB
MAX_ACCOUNT_EXPANDED_BYTES = 1024 * 1024 * 1024  # 解压后 1GB(防 zip 炸弹)
MAX_MEMBERS = 5000                             # 成员数量上限


# ──────────────────────────────────────────────────────────────────────────
#  读取小块用户数据
# ──────────────────────────────────────────────────────────────────────────

def _read_preferences(db, user_id: int) -> dict[str, Any]:
    row = db.execute(
        "select preferences from user_preferences where user_id = %s",
        (user_id,),
    ).fetchone()
    if not row:
        return {}
    prefs = row["preferences"] if isinstance(row, dict) else row[0]
    return prefs if isinstance(prefs, dict) else {}


def _owned_script_ids(db, user_id: int) -> list[int]:
    rows = db.execute(
        "select id from scripts where owner_id = %s order by id",
        (user_id,),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def _owned_saves(db, user_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        "select id, script_id, title from game_saves where user_id = %s order by id",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────
#  导出
# ──────────────────────────────────────────────────────────────────────────

def estimate_account(user_id: int) -> dict[str, Any]:
    """轻量统计,供前端导出前展示规模。不真正打包。"""
    init_db()
    with connect() as db:
        scripts = _owned_script_ids(db, user_id)
        saves = _owned_saves(db, user_id)
        cards_row = db.execute(
            "select count(*) as n from character_cards where user_id = %s and card_type in ('pc', 'persona')",
            (user_id,),
        ).fetchone()
        prefs = _read_preferences(db, user_id)
        overlay = user_models.load_overlay(user_id)
    n_models = sum(len(v) for v in overlay.values())
    return {
        "ok": True,
        "scripts": len(scripts),
        "saves": len(saves),
        "cards": int(cards_row["n"] if isinstance(cards_row, dict) else cards_row[0]),
        "has_preferences": bool(prefs),
        "model_entries": n_models,
        "note": "The export does not include API keys; re-enter each model's API key after migrating to your local instance.",
    }


def export_account(user_id: int, include_chunks: bool = False) -> tuple[bytes, str]:
    """聚合该用户全部个人数据为单个 zip。返回 (zip_bytes, filename)。

    include_chunks=True 时,剧本包内含 document_chunks(体积大,默认不含)。
    """
    init_db()

    with connect() as db:
        script_ids = _owned_script_ids(db, user_id)
        saves = _owned_saves(db, user_id)
        cards_rows = db.execute(
            "select * from character_cards where user_id = %s and card_type in ('pc', 'persona') "
            "order by card_type, priority desc, id",
            (user_id,),
        ).fetchall()
        prefs = _read_preferences(db, user_id)
        user_row = db.execute(
            "select public_id, username from users where id = %s",
            (user_id,),
        ).fetchone()
        # 图片资产「清单」(仅元数据,不含文件本体):AI 生图/头像/封面/人设图等存本地或 OSS,体积大不入包;
        # 导出 URL 清单供用户跨实例时手动转存/重生(导入侧不处理,URL 跨实例失效)。表 v72 起,老库容缺。
        try:
            asset_rows = db.execute(
                "select kind, url, source, ref_kind, ref_id, mime, size, created_at "
                "from user_assets where user_id = %s order by kind, created_at",
                (user_id,),
            ).fetchall()
        except Exception:
            asset_rows = []

    overlay = user_models.load_overlay(user_id)
    # 保留 card_type(pc / persona),导入侧据此路由到 upsert_user_card / upsert_persona。
    cards = [{**card_to_dto(r), "card_type": r.get("card_type") or "pc"} for r in cards_rows]

    buf = io.BytesIO()
    manifest_scripts: list[dict[str, Any]] = []
    manifest_saves: list[dict[str, Any]] = []
    warnings: list[str] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. 剧本包(逐个)
        for sid in script_ids:
            try:
                pack_bytes, _fname = script_pack.export_script_pack(sid, user_id, include_chunks)
            except Exception as exc:  # 单个剧本导出失败不阻断整盘
                warnings.append(f"Script {sid} failed to export and was skipped: {exc}")
                continue
            member = f"scripts/{sid}.pack.zip"
            zf.writestr(member, pack_bytes)
            manifest_scripts.append({"origin_script_id": sid, "member": member})

        # 2. 存档(逐个,标准 save_io JSON)
        for sv in saves:
            sid_save = int(sv["id"])
            try:
                payload = save_io.export_save(user_id, sid_save)
            except Exception as exc:
                warnings.append(f"Save {sid_save} failed to export and was skipped: {exc}")
                continue
            member = f"saves/{sid_save}.json"
            # default=str:存档 payload 里可能有 datetime(expose 未全转)→ 转字符串,
            # 防 "datetime is not JSON serializable"。导入侧 timestamptz 接受 ISO 字符串。
            zf.writestr(member, json.dumps(payload, ensure_ascii=False, default=str))
            manifest_saves.append({
                "origin_save_id": sid_save,
                "origin_script_id": (int(sv["script_id"]) if sv.get("script_id") else None),
                "title": sv.get("title") or "",
                "member": member,
            })

        # 3. 角色卡
        if cards:
            zf.writestr(
                "cards.jsonl",
                "\n".join(json.dumps(c, ensure_ascii=False, default=str) for c in cards),
            )

        # 3b. 图片资产清单(仅元数据 / URL,不含文件本体)
        if asset_rows:
            zf.writestr(
                "images.jsonl",
                "\n".join(json.dumps(dict(r), ensure_ascii=False, default=str) for r in asset_rows),
            )

        # 4. profile(偏好 + 模型 overlay)
        zf.writestr("profile.json", json.dumps({
            "preferences": prefs,
            "model_overlay": overlay,
        }, ensure_ascii=False, default=str))

        # 5. manifest
        manifest = {
            "account_export_version": ACCOUNT_EXPORT_VERSION,
            "exported_at": time.time(),
            "source": {
                "public_id": (user_row.get("public_id") if user_row else None),
                "username": (user_row.get("username") if user_row else None),
            },
            "counts": {
                "scripts": len(manifest_scripts),
                "saves": len(manifest_saves),
                "cards": len(cards),
                "images": len(asset_rows),
                "model_entries": sum(len(v) for v in overlay.values()),
            },
            "scripts": manifest_scripts,
            "saves": manifest_saves,
            "has_cards": bool(cards),
            "has_profile": True,
            "warnings": warnings,
        }
        zf.writestr("account-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))

        # 6. 人类可读说明
        zf.writestr("README.txt", _README)

    data = buf.getvalue()
    if len(data) > MAX_ACCOUNT_ZIP_BYTES:
        raise ValueError(
            f"Account data package is too large (>{MAX_ACCOUNT_ZIP_BYTES // 1024 // 1024}MB); "
            "export per script / per save instead."
        )
    fname = f"account-{(user_row.get('public_id') if user_row else user_id)}-{int(time.time())}.zip"
    return data, fname


_README = (
    "RPG Roleplay Platform - Account data package\n"
    "============================================\n\n"
    "This package moves your personal data from the online service to a self-hosted local instance.\n"
    "Log in to your local instance, open Settings -> Data migration and choose this file to import it.\n\n"
    "Includes: your own scripts (all world settings / chapters / character cards / worldbooks), saves (story history / anchor state),\n"
    "          user character cards, personal preferences and model lists.\n\n"
    "Excludes: API keys. Keys are stored encrypted with the server's key and cannot be decrypted on another instance;\n"
    "          after migrating, re-enter each provider's API key under Settings -> Models on your local instance.\n"
)


# ──────────────────────────────────────────────────────────────────────────
#  导入
# ──────────────────────────────────────────────────────────────────────────

def import_account(user_id: int, zip_bytes: bytes, progress=None) -> dict[str, Any]:
    """从账号数据包重建该用户的数据。返回 {ok, scripts, saves, cards, warnings}。

    progress(stage:str, done:int, total:int):可选回调,用于异步作业上报真实进度。
    """
    def _p(stage, done, total):
        if progress:
            try:
                progress(stage, done, total)
            except Exception:
                pass
    init_db()
    if len(zip_bytes) > MAX_ACCOUNT_ZIP_BYTES:
        raise ValueError(f"Account package is too large (max {MAX_ACCOUNT_ZIP_BYTES // 1024 // 1024}MB)")

    try:
        zf_handle = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid zip file: {exc}") from exc

    warnings: list[str] = []
    n_scripts = n_saves = n_cards = 0
    script_id_map: dict[int, int] = {}  # origin_script_id → new_script_id

    with zf_handle as zf:
        names = zf.namelist()
        if len(names) > MAX_MEMBERS:
            raise ValueError(f"Too many members (max {MAX_MEMBERS})")
        # zip-slip + 解压炸弹预检
        declared_total = 0
        for info in zf.infolist():
            parts = info.filename.replace("\\", "/").split("/")
            if info.filename.startswith("/") or ".." in parts:
                raise ValueError(f"zip-slip detected: {info.filename!r}")
            declared_total += info.file_size
        if declared_total > MAX_ACCOUNT_EXPANDED_BYTES:
            raise ValueError(f"Too large after decompression (max {MAX_ACCOUNT_EXPANDED_BYTES // 1024 // 1024}MB)")

        try:
            # SEC(H-8): 有界解压,防单成员谎报/炸弹 OOM。
            manifest = json.loads(script_pack._safe_member_read(zf, "account-manifest.json").decode("utf-8"))
        except KeyError as exc:
            raise ValueError("Missing account-manifest.json - not an account data package") from exc
        av = int(manifest.get("account_export_version") or 0)
        if av != ACCOUNT_EXPORT_VERSION:
            raise ValueError(f"Unsupported account_export_version ({av}); {ACCOUNT_EXPORT_VERSION} is required")

        # 1. 剧本包 → 建立 id 映射
        scripts_list = manifest.get("scripts") or []
        total_scripts = len(scripts_list)
        _p("scripts", 0, total_scripts)
        for si, entry in enumerate(scripts_list):
            member = entry.get("member")
            origin = entry.get("origin_script_id")
            _p("scripts", si, total_scripts)
            if not member or member not in names:
                warnings.append(f"Missing script member: {member}")
                continue
            try:
                # #64:把单个剧本内部的章节/事实进度作为 scripts 阶段细粒度进度回报,
                # 让「导入剧本」进度条对大文件持续走动,而非卡在 0/1 像死了。
                res = script_pack.import_script_pack(
                    script_pack._safe_member_read(zf, member), user_id,  # SEC(H-8): 有界解压
                    progress_cb=lambda done, total: _p("scripts", done, total),
                )
                new_sid = int(res.get("script_id"))
                if origin is not None:
                    script_id_map[int(origin)] = new_sid
                n_scripts += 1
                for w in (res.get("warnings") or []):
                    warnings.append(f"Script {origin}: {w}")
            except Exception as exc:
                warnings.append(f"Script {origin} failed to import: {exc}")

        # 2. 存档 → 改写 script_id 后导入
        _p("scripts", total_scripts, total_scripts)
        saves_list = manifest.get("saves") or []
        total_saves = len(saves_list)
        _p("saves", 0, total_saves)
        for vi, entry in enumerate(saves_list):
            member = entry.get("member")
            origin_script = entry.get("origin_script_id")
            _p("saves", vi, total_saves)
            if not member or member not in names:
                warnings.append(f"Missing save member: {member}")
                continue
            try:
                payload = json.loads(script_pack._safe_member_read(zf, member).decode("utf-8"))  # SEC(H-8): 有界解压
                save_obj = payload.get("save") or {}
                # 把原 script_id 重映射到新导入的剧本;映射不到则置空,
                # import_save 会兜底挂到用户第一个剧本并 warning。
                mapped = script_id_map.get(int(origin_script)) if origin_script else None
                save_obj["script_id"] = mapped
                payload["save"] = save_obj
                res = save_io.import_save(user_id, payload)
                n_saves += 1
                for w in (res.get("warnings") or []):
                    warnings.append(f"Save {entry.get('origin_save_id')}: {w}")
            except Exception as exc:
                warnings.append(f"Save {entry.get('origin_save_id')} failed to import: {exc}")

        # 3. 角色卡
        _p("saves", total_saves, total_saves)
        _p("cards", 0, 1)
        if "cards.jsonl" in names:
            for line in zf.read("cards.jsonl").decode("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    dto = json.loads(line)
                    dto.pop("id", None)  # 让 DB 重新分配 / 按 slug upsert
                    if (dto.get("card_type") or "pc") == "persona":
                        user_cards.upsert_persona(user_id, dto)
                    else:
                        user_cards.upsert_user_card(user_id, dto)
                    n_cards += 1
                except Exception as exc:
                    warnings.append(f"Character card import failed: {exc}")

        # 4. profile(偏好 + 模型 overlay)
        if "profile.json" in names:
            try:
                profile = json.loads(zf.read("profile.json").decode("utf-8"))
                _import_preferences(user_id, profile.get("preferences") or {})
                overlay = profile.get("model_overlay") or {}
                for api_id, models in overlay.items():
                    if isinstance(models, list) and models:
                        user_models.replace_synced_models(user_id, api_id, models)
            except Exception as exc:
                warnings.append(f"Preferences/models import failed: {exc}")

    return {
        "ok": True,
        "scripts": n_scripts,
        "saves": n_saves,
        "cards": n_cards,
        "warnings": warnings,
    }


def _import_preferences(user_id: int, prefs: dict[str, Any]) -> None:
    """jsonb 浅合并:导入值覆盖同名键,保留本地已有的其它键。"""
    if not isinstance(prefs, dict) or not prefs:
        return
    with connect() as db:
        db.execute(
            """
            insert into user_preferences(user_id, preferences)
            values (%s, %s)
            on conflict (user_id) do update set
              preferences = coalesce(user_preferences.preferences, '{}'::jsonb) || excluded.preferences,
              updated_at = now()
            """,
            (user_id, Jsonb(prefs)),
        )


# ──────────────────────────────────────────────────────────────────────────
#  异步作业:账号导入(复用 import_jobs/SSE,前端 streamImport 看真实进度)
# ──────────────────────────────────────────────────────────────────────────
_STAGE_LABELS = {"scripts": "Imported script", "saves": "Imported save", "cards": "Imported character card"}


def import_account_job(user_id: int, zip_bytes: bytes) -> dict[str, Any]:
    """建 import_jobs 作业 + 后台线程跑 import_account,逐项上报进度。返回 {ok, job_id}。"""
    import secrets
    import threading

    init_db()
    if len(zip_bytes) > MAX_ACCOUNT_ZIP_BYTES:
        raise ValueError(f"Account package is too large (max {MAX_ACCOUNT_ZIP_BYTES // 1024 // 1024}MB)")
    job_id = f"acc_imp_{secrets.token_hex(6)}"
    with connect() as db:
        db.execute(
            "insert into import_jobs(job_id, user_id, script_id, kind, status, stage, "
            "overall_total, stages) values (%s, %s, null, 'account_import', 'pending', 'pending', 3, %s)",
            (job_id, user_id, Jsonb([
                {"id": "scripts", "label": "Imported script", "status": "pending"},
                {"id": "saves", "label": "Imported save", "status": "pending"},
                {"id": "cards", "label": "Imported character card", "status": "pending"},
            ])),
        )
    th = threading.Thread(target=_run_account_import_job, args=(job_id, user_id, zip_bytes), daemon=True)
    th.start()
    return {"ok": True, "job_id": job_id}


def _run_account_import_job(job_id: str, user_id: int, zip_bytes: bytes) -> None:
    from . import import_pipeline
    ctl = import_pipeline.JobController(job_id)
    sem = getattr(import_pipeline, "_IMPORT_GLOBAL_SEM", None)
    acquired = False
    try:
        if sem is not None:
            sem.acquire()
            acquired = True
        ctl.update(status="running", stage="scripts")
        order = ["scripts", "saves", "cards"]

        def _progress(stage, done, total):
            try:
                idx = order.index(stage)
            except ValueError:
                idx = 0
            ctl.update(stage=stage, stage_progress=int(done), stage_total=int(total),
                       overall_progress=idx)

        res = import_account(user_id, zip_bytes, progress=_progress)
        from datetime import datetime
        ctl.update(
            status="done_with_errors" if res.get("warnings") else "done",
            stage="done", overall_progress=3,
            warnings=res.get("warnings") or [],
            usage_actual={"summary": {"scripts": res.get("scripts", 0),
                                       "saves": res.get("saves", 0),
                                       "cards": res.get("cards", 0)}},
            finished_at=datetime.now(UTC),
        )
    except Exception as exc:
        from datetime import datetime
        ctl.update(status="failed", error=str(exc)[:500], finished_at=datetime.now(UTC))
    finally:
        if acquired and sem is not None:
            sem.release()
