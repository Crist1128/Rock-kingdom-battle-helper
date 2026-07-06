"""洛克王国 BWIKI 数据更新服务。

本模块只负责“主动触发”的数据更新管理，不在后端普通启动流程中主动检查
远程站点。这样可以保证本地战斗记录、实时面板估计等核心功能不受外部网络、BWIKI
可用性和爬虫耗时影响。

当前提供三类能力：
- check-only：只读取远程图鉴列表，与本地 rocom 精灵 ID 做差异对比，不写库；
- sync：爬取远程详情页、清洗数据，并按 commit 参数决定 dry-run 或写库；
- import-local：不访问远程，只把已存在的 cleaned JSON 重新导入数据库。
"""

from __future__ import annotations

import hashlib
import traceback
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.data_pipeline.effects.importer import import_effect_definitions, read_effect_rows
from app.data_pipeline.rocom.cleaner import clean_from_raw_sprites, write_cleaned_dataset
from app.data_pipeline.rocom.importer import import_dataset, load_cleaned_dataset
from app.data_pipeline.rocom.scraper import parse_list_page, scrape_rocom_sprites
from app.data_pipeline.skill_rule_reviews.importer import (
    import_skill_rule_reviews,
    read_review_rows,
)
from app.data_pipeline.static_rule_sync import check_effect_definition_seed_sync
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.static import (
    EffectDefinition,
    ElfDefinition,
    ElfLearnableSkill,
    NatureDefinition,
    SkillDefinition,
    TypeEffectivenessRule,
)
from app.seed.core_natures import ensure_core_natures
from app.seed.core_skills import ensure_core_skills

PROJECT_EFFECT_SEED_FILES = (
    BACKEND_DIR / "app" / "seed" / "manual_skill_effect_definitions_all_20260612.json",
    BACKEND_DIR / "app" / "seed" / "effect_definitions_p0.json",
)
PROJECT_SKILL_REVIEW_SEED_FILES = (
    BACKEND_DIR / "app" / "seed" / "manual_skill_rule_reviews_all_20260612.json",
)


@dataclass(slots=True)
class RocomUpdateParams:
    """远程同步参数。

    commit=False 时只执行 dry-run 并回滚数据库事务，适合作为同步前预检查。
    force=True 会强制重爬已缓存精灵，通常只在确认数据源发生变动时使用。
    """

    commit: bool = False
    force: bool = False
    limit: int = 0
    delay: float = 1.5
    with_images: bool = False
    data_version: str | None = None
    write_artifacts: bool = True
    refresh_static: bool = False
    update_mode: str = "incremental"


@dataclass(slots=True)
class RocomCheckParams:
    """远程列表检查参数。

    check-only 只解析图鉴列表页，不抓取详情页、不清洗、不写库。它适合做
    “是否可能有新增精灵”的低成本人工判断。
    """

    limit: int = 0
    include_new_elves_limit: int = 100


@dataclass(slots=True)
class RocomImportLocalParams:
    """本地 cleaned JSON 导入参数。"""

    cleaned_dir: str | None = None
    commit: bool = False
    data_version: str | None = None
    refresh_static: bool = False
    update_mode: str = "incremental"


@dataclass(slots=True)
class ProjectBootstrapLocalParams:
    """空库一键初始化参数。"""

    cleaned_dir: str | None = None
    commit: bool = False
    data_version: str | None = None


@dataclass(slots=True)
class RocomUpdateJob:
    """内存中的更新任务记录。

    注意：任务状态保存在进程内，后端重启后历史任务会丢失。第一阶段 MVP 用于
    本地单用户管理已经足够；如后续需要长期审计，可再落表。
    """

    job_id: str
    status: str
    created_at: str
    params: dict[str, Any]
    job_type: str = "sync"
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    traceback: str | None = field(default=None, repr=False)


_jobs: dict[str, RocomUpdateJob] = {}
_jobs_lock = Lock()


def utc_now_iso() -> str:
    """返回 UTC ISO 时间字符串。"""
    return datetime.now(UTC).isoformat()


def get_rocom_update_job(job_id: str) -> dict[str, Any] | None:
    """查询任务状态。"""
    with _jobs_lock:
        job = _jobs.get(job_id)
        return asdict(job) if job else None


def list_rocom_update_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """列出最近的更新任务。"""
    with _jobs_lock:
        jobs = sorted(_jobs.values(), key=lambda item: item.created_at, reverse=True)[:limit]
        return [asdict(job) for job in jobs]


def _create_job(params: dict[str, Any], *, job_type: str) -> dict[str, Any]:
    """创建任务记录；同一时间只允许一个数据写入/同步任务运行。

    check-only 不走任务队列，因为它只读远程列表且不写库；sync/import-local
    可能耗时或写库，使用后台任务并串行化，避免并发导入导致 SQLite 锁冲突。
    """
    with _jobs_lock:
        running = [job for job in _jobs.values() if job.status in {"queued", "running"}]
        if running:
            raise RuntimeError(f"已有数据更新任务正在运行: {running[0].job_id}")
        job_id = uuid4().hex
        job = RocomUpdateJob(
            job_id=job_id,
            job_type=job_type,
            status="queued",
            created_at=utc_now_iso(),
            params=params,
            progress={
                "stage": "queued",
                "message": "任务已排队",
                "current": 0,
                "total": 0,
                "percent": 0,
            },
        )
        _jobs[job_id] = job
        return asdict(job)


def create_rocom_update_job(params: RocomUpdateParams) -> dict[str, Any]:
    """Create a remote sync job."""
    _validate_update_params(params)
    return _create_job(asdict(params), job_type="sync")


def create_rocom_import_local_job(params: RocomImportLocalParams) -> dict[str, Any]:
    """创建本地 cleaned JSON 导入任务记录。"""
    return _create_job(asdict(params), job_type="import_local")


def create_project_bootstrap_local_job(params: ProjectBootstrapLocalParams) -> dict[str, Any]:
    """创建空库一键初始化任务。"""
    return _create_job(asdict(params), job_type="bootstrap_local")


def _finish_job_success(job_id: str, result: dict[str, Any]) -> None:
    """Mark a job as successful."""
    with _jobs_lock:
        job = _jobs[job_id]
        job.status = "succeeded"
        job.finished_at = utc_now_iso()
        job.result = result
        job.progress = {
            "stage": "complete",
            "message": "Job complete",
            "current": 100,
            "total": 100,
            "percent": 100,
            "updated_at": utc_now_iso(),
        }


def _finish_job_error(job_id: str, exc: Exception) -> None:
    """Mark a job as failed and keep traceback for debugging."""
    with _jobs_lock:
        job = _jobs[job_id]
        job.status = "failed"
        job.finished_at = utc_now_iso()
        job.error = str(exc)
        job.progress = {
            "stage": "failed",
            "message": str(exc),
            "current": 0,
            "total": 0,
            "percent": 0,
            "updated_at": utc_now_iso(),
        }
        job.traceback = traceback.format_exc()


def _mark_job_running(job_id: str) -> tuple[str, dict[str, Any]]:
    """Mark a job as running and return job_type plus params copy."""
    with _jobs_lock:
        job = _jobs[job_id]
        job.status = "running"
        job.started_at = utc_now_iso()
        job.progress = {
            "stage": "running",
            "message": "Job started",
            "current": 0,
            "total": 0,
            "percent": 0,
            "updated_at": utc_now_iso(),
        }
        return job.job_type, dict(job.params)


def _update_job_progress(job_id: str, progress: dict[str, Any]) -> None:
    """Update background job progress for frontend polling."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.progress = {**progress, "updated_at": utc_now_iso()}


def _validate_update_params(params: RocomUpdateParams) -> None:
    """Reject partial committed full-refresh jobs to protect static data."""
    if params.update_mode not in {"incremental", "full", "new_only"}:
        raise ValueError("update_mode must be incremental, full, or new_only")
    effective_refresh_static = params.refresh_static or params.update_mode == "full"
    if params.update_mode == "new_only" and params.refresh_static:
        raise ValueError("new_only mode cannot be used with refresh_static=true")
    if params.commit and effective_refresh_static and params.limit > 0:
        raise ValueError(
            "commit=true with refresh_static=true requires limit=0; "
            "run dry-run first or set limit to 0 before committing a full refresh."
        )


def _local_rocom_elf_ids() -> set[str]:
    """Return active local rocom elf IDs."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(ElfDefinition.elf_id).where(
                ElfDefinition.elf_id.like("rocom_elf_%"),
                ElfDefinition.deleted_at.is_(None),
            )
        ).all()
        return {row.elf_id for row in rows}
    finally:
        db.close()


def _new_remote_sprite_entries(limit: int = 0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch the remote sprite list and keep entries that do not exist locally."""
    from app.data_pipeline.rocom.cleaner import make_elf_id

    entries = parse_list_page()
    local_ids = _local_rocom_elf_ids()
    new_entries = [entry for entry in entries if make_elf_id(entry) not in local_ids]
    if limit > 0:
        new_entries = new_entries[:limit]
    return new_entries, {
        "remote_count": len(entries),
        "local_rocom_count": len(local_ids),
        "new_elf_count": len(new_entries),
        "new_elf_preview": [
            {
                "no": entry.get("no"),
                "name": entry.get("name"),
                "form": entry.get("form"),
                "url": entry.get("url"),
            }
            for entry in new_entries[:50]
        ],
        "new_elf_preview_truncated": len(new_entries) > 50,
    }


def check_rocom_remote_updates(params: RocomCheckParams) -> dict[str, Any]:
    """检查远程图鉴列表与本地数据库的差异。

    该函数只读取 BWIKI 图鉴列表页，并基于 cleaner.make_elf_id 规则生成稳定
    elf_id，然后与本地 `elf_definition` 中 rocom_elf_* 记录对比。

    返回值是“是否可能有变化”的管理提示，不会修改数据库。若 BWIKI 页面结构变化，
    该检查可能失败或低估变化，因此真正入库前仍应执行 dry-run sync/import-local。
    """
    # 延迟导入 make_elf_id，避免 service 顶部暴露过多清洗细节。
    from app.data_pipeline.rocom.cleaner import make_elf_id

    entries = parse_list_page()
    if params.limit > 0:
        entries = entries[: params.limit]

    remote_ids: dict[str, dict[str, Any]] = {}
    for entry in entries:
        elf_id = make_elf_id(entry)
        remote_ids[elf_id] = entry

    db = SessionLocal()
    try:
        rows = db.execute(
            select(ElfDefinition.elf_id, ElfDefinition.elf_name, ElfDefinition.data_version).where(
                ElfDefinition.elf_id.like("rocom_elf_%"),
                ElfDefinition.deleted_at.is_(None),
            )
        ).all()
    finally:
        db.close()

    local_ids = {row.elf_id for row in rows}
    new_ids = sorted(set(remote_ids) - local_ids)
    missing_ids = sorted(local_ids - set(remote_ids))

    new_elves = [
        {
            "elf_id": elf_id,
            "no": remote_ids[elf_id].get("no"),
            "name": remote_ids[elf_id].get("name"),
            "form": remote_ids[elf_id].get("form"),
            "url": remote_ids[elf_id].get("url"),
        }
        for elf_id in new_ids[: params.include_new_elves_limit]
    ]

    # 给远程列表生成一个轻量指纹，便于前端展示“本次检查与上次是否一致”。
    fingerprint_source = "\n".join(
        f"{item.get('no')}|{item.get('name')}|{item.get('form')}|{item.get('url')}"
        for item in entries
    )
    remote_fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8")).hexdigest()

    status = "changed" if new_ids else "unchanged"
    return {
        "source": "rocom_bwiki",
        "status": status,
        "checked_at": utc_now_iso(),
        "remote_count": len(remote_ids),
        "local_rocom_count": len(local_ids),
        "new_elf_count": len(new_ids),
        "missing_local_count": len(missing_ids),
        "new_elves": new_elves,
        "new_elves_truncated": len(new_ids) > len(new_elves),
        "remote_fingerprint": remote_fingerprint,
        "note": (
            "check-only 只比较图鉴列表稳定 ID；详情页字段变化需通过 dry-run sync "
            "或 import-local 的 import_summary 判断。"
        ),
    }


def run_rocom_update_job(job_id: str) -> None:
    """执行远程爬取、清洗和数据库导入。"""
    _, raw_params = _mark_job_running(job_id)
    params = RocomUpdateParams(**raw_params)

    data_root = Path(settings.rocom_data_dir)
    raw_dir = data_root / "raw"
    cleaned_name = "cleaned_new_only" if params.update_mode == "new_only" else "cleaned"
    cleaned_dir = data_root / cleaned_name
    raw_output = raw_dir / (
        "sprites_raw_new_only.json" if params.update_mode == "new_only" else "sprites_raw.json"
    )

    try:
        _validate_update_params(params)
        entries_override: list[dict[str, Any]] | None = None
        remote_check: dict[str, Any] | None = None
        skip_skill_catalog = False
        if params.update_mode == "new_only":
            _update_job_progress(
                job_id,
                {
                    "stage": "check_remote",
                    "message": "Checking remote new sprites",
                    "current": 0,
                    "total": 1,
                    "percent": 0,
                },
            )
            entries_override, remote_check = _new_remote_sprite_entries(params.limit)
            _update_job_progress(
                job_id,
                {
                    "stage": "check_remote",
                    "message": "Remote check complete",
                    "current": 1,
                    "total": 1,
                    "percent": 100,
                    "details": remote_check,
                },
            )
            skip_skill_catalog = True
            if not entries_override:
                _update_job_progress(
                    job_id,
                    {
                        "stage": "import_project_rules",
                        "message": "No new sprites; importing project seed rules only",
                        "current": 0,
                        "total": 1,
                        "percent": 0,
                    },
                )
                project_rule_summary, transaction = _import_project_seed_rules_with_transaction(
                    commit=params.commit
                )
                _finish_job_success(
                    job_id,
                    {
                        "transaction": transaction,
                        "commit": params.commit,
                        "remote_check": remote_check,
                        "import_summary": {},
                        "project_rule_summary": project_rule_summary,
                        "warnings": [],
                    },
                )
                return

        scrape_result = scrape_rocom_sprites(
            output=raw_output,
            limit=params.limit,
            delay=params.delay,
            with_images=params.with_images,
            force=params.force,
            debug_images=False,
            repair_images=False,
            skip_skill_catalog=skip_skill_catalog,
            progress_callback=lambda progress: _update_job_progress(job_id, progress),
            entries=entries_override,
        )
        _update_job_progress(
            job_id,
            {
                "stage": "clean",
                "message": "Cleaning scraped data",
                "current": 0,
                "total": 1,
                "percent": 0,
            },
        )
        dataset = clean_from_raw_sprites(
            scrape_result["sprites"],
            raw_skill_rows=scrape_result.get("skills"),
            image_url_rows=scrape_result["image_urls"],
            data_version=params.data_version,
            image_mode="local" if params.with_images else "remote",
        )
        if params.write_artifacts:
            write_cleaned_dataset(dataset, cleaned_dir)
        _update_job_progress(
            job_id,
            {
                "stage": "clean",
                "message": "Clean complete",
                "current": 1,
                "total": 1,
                "percent": 100,
            },
        )

        _update_job_progress(
            job_id,
            {
                "stage": "import",
                "message": "Importing dataset; commit=false will roll back as dry-run",
                "current": 0,
                "total": 1,
                "percent": 0,
            },
        )
        import_summary, project_rule_summary, transaction = _import_dataset_with_transaction(
            dataset=dataset,
            commit=params.commit,
            refresh_static=params.refresh_static or params.update_mode == "full",
        )
        _update_job_progress(
            job_id,
            {
                "stage": "import",
                "message": "Import complete",
                "current": 1,
                "total": 1,
                "percent": 100,
            },
        )

        result = {
            "transaction": transaction,
            "commit": params.commit,
            "update_mode": params.update_mode,
            "raw_output": str(raw_output.resolve()),
            "cleaned_dir": str(cleaned_dir.resolve()) if params.write_artifacts else None,
            "remote_check": remote_check,
            "scrape_stats": scrape_result["stats"],
            "clean_stats": dataset.stats,
            "import_summary": import_summary,
            "project_rule_summary": project_rule_summary,
            "warnings": dataset.warnings[:50],
        }
        _finish_job_success(job_id, result)
    except Exception as exc:
        _finish_job_error(job_id, exc)


def _resolve_cleaned_dir(cleaned_dir: str | None) -> Path:
    """解析 cleaned JSON 目录。

    - 未传入时使用 ROCOM_DATA_DIR/cleaned；
    - 传入绝对路径时原样使用；
    - 传入相对路径时按 backend 目录解析，避免从项目根目录或 backend
      目录启动服务时行为不一致。
    """
    if cleaned_dir is None:
        return Path(settings.rocom_data_dir) / "cleaned"
    path = Path(cleaned_dir)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def get_project_bootstrap_status(cleaned_dir: str | None = None) -> dict[str, Any]:
    """汇总空库启动前必须导入的数据状态。"""
    cleaned_path = _resolve_cleaned_dir(cleaned_dir)
    required_cleaned_files = [
        "elves.json",
        "skills.json",
        "elf_learnable_skills.json",
        "type_effectiveness_rules.json",
    ]
    cleaned_files = [
        {
            "name": name,
            "path": str((cleaned_path / name).resolve()),
            "exists": (cleaned_path / name).exists(),
            "size_bytes": (cleaned_path / name).stat().st_size
            if (cleaned_path / name).exists()
            else 0,
        }
        for name in required_cleaned_files
    ]
    seed_files = [
        {
            "name": path.name,
            "path": str(path.resolve()),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        }
        for path in [*PROJECT_EFFECT_SEED_FILES, *PROJECT_SKILL_REVIEW_SEED_FILES]
    ]

    init_db()
    db = SessionLocal()
    try:
        counts = {
            "natures": _table_count(db, NatureDefinition),
            "core_skill": 1 if db.get(SkillDefinition, "core_skill_focus_energy") else 0,
            "elves": _table_count(db, ElfDefinition),
            "skills": _table_count(db, SkillDefinition),
            "learnable_skills": _table_count(db, ElfLearnableSkill),
            "type_effectiveness_rules": _table_count(db, TypeEffectivenessRule),
            "effects": _table_count(db, EffectDefinition),
        }
        seed_rule_status = check_effect_definition_seed_sync(db, limit=20)
    finally:
        db.close()

    has_static_data = (
        counts["elves"] > 0
        and counts["skills"] > 1
        and counts["learnable_skills"] > 0
        and counts["type_effectiveness_rules"] > 0
    )
    has_project_rules = (
        counts["effects"] > 0
        and int(seed_rule_status.get("pending_count") or 0) == 0
    )
    local_package_ready = all(item["exists"] for item in cleaned_files)
    seed_files_ready = all(item["exists"] for item in seed_files)
    ready = has_static_data and has_project_rules
    missing_required = []
    if counts["natures"] == 0:
        missing_required.append("核心性格")
    if counts["core_skill"] == 0:
        missing_required.append("核心默认技能：聚能")
    if not has_static_data:
        missing_required.append("BWIKI 静态数据：精灵、技能、可学习技能、属性克制")
    if not has_project_rules:
        missing_required.append("项目规则 seed：状态定义与人工技能分支")
    if not seed_files_ready:
        missing_required.append("仓库内项目 seed 文件")

    return {
        "ready": ready,
        "checked_at": utc_now_iso(),
        "counts": counts,
        "seed_rule_status": {
            "effect_pending_count": seed_rule_status.get("pending_count", 0),
            "effect_up_to_date_count": seed_rule_status.get("up_to_date_count", 0),
            "effect_pending_items": seed_rule_status.get("pending_items", []),
            "effect_pending_items_truncated": seed_rule_status.get(
                "pending_items_truncated",
                False,
            ),
            "errors": seed_rule_status.get("errors", []),
        },
        "missing_required": missing_required,
        "local_cleaned_dir": str(cleaned_path.resolve()),
        "local_package_ready": local_package_ready,
        "cleaned_files": cleaned_files,
        "seed_files": seed_files,
        "recommended_action": (
            "数据库已具备运行所需基础数据"
            if ready
            else (
                "优先使用一键本地初始化；如果本地 cleaned 数据缺失，再使用远程 BWIKI 同步"
                if local_package_ready
                else "本地 cleaned 数据缺失，请先放入数据包或执行远程 BWIKI 同步"
            )
        ),
        "required_data": [
            {
                "key": "schema",
                "name": "数据库结构",
                "source": "Alembic",
                "import_path": "后端启动或 init_db 自动迁移",
                "auto_on_startup": True,
            },
            {
                "key": "core_rules",
                "name": "核心性格与默认聚能技能",
                "source": "backend/app/seed/core_natures.py, core_skills.py",
                "import_path": "后端启动自动幂等写入；一键初始化也会补齐",
                "auto_on_startup": True,
            },
            {
                "key": "rocom_cleaned",
                "name": "BWIKI 静态数据",
                "source": "data/rocom/cleaned 或远程 BWIKI 爬取",
                "import_path": "设置页一键本地初始化 / 本地 cleaned 导入 / 远程同步",
                "auto_on_startup": False,
            },
            {
                "key": "project_seed_rules",
                "name": "项目规则 seed",
                "source": "backend/app/seed/*.json",
                "import_path": "一键初始化、本地 cleaned 导入和远程同步都会并入导入事务",
                "auto_on_startup": False,
            },
        ],
    }


def _table_count(db: Session, model: type[Any]) -> int:
    """返回模型表行数。"""
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def run_project_bootstrap_local_job(job_id: str) -> None:
    """执行空库一键本地初始化。"""
    _, raw_params = _mark_job_running(job_id)
    params = ProjectBootstrapLocalParams(**raw_params)
    cleaned_dir = _resolve_cleaned_dir(params.cleaned_dir)

    try:
        _update_job_progress(
            job_id,
            {
                "stage": "bootstrap_check",
                "message": "检查本地 cleaned 数据包与 seed 文件",
                "current": 0,
                "total": 4,
                "percent": 0,
            },
        )
        before_status = get_project_bootstrap_status(params.cleaned_dir)
        if not before_status["local_package_ready"]:
            raise FileNotFoundError(
                f"本地 cleaned 数据不完整，请检查目录：{before_status['local_cleaned_dir']}"
            )
        missing_seed_files = [
            item["path"] for item in before_status["seed_files"] if not item["exists"]
        ]
        if missing_seed_files:
            raise FileNotFoundError(
                "项目 seed 文件缺失，无法完成初始化："
                + "、".join(missing_seed_files)
            )

        _update_job_progress(
            job_id,
            {
                "stage": "ensure_core_rules",
                "message": "准备在同一事务内补齐核心规则",
                "current": 1,
                "total": 4,
                "percent": 25,
            },
        )

        _update_job_progress(
            job_id,
            {
                "stage": "load_cleaned",
                "message": "读取本地 cleaned JSON 数据包",
                "current": 2,
                "total": 4,
                "percent": 50,
            },
        )
        dataset = load_cleaned_dataset(cleaned_dir)
        if params.data_version:
            _override_dataset_version(dataset, params.data_version)

        _update_job_progress(
            job_id,
            {
                "stage": "import",
                "message": "导入 BWIKI 静态数据与项目规则 seed",
                "current": 3,
                "total": 4,
                "percent": 75,
            },
        )
        import_summary, project_rule_summary, transaction = _import_dataset_with_transaction(
            dataset=dataset,
            commit=params.commit,
            refresh_static=True,
            ensure_core=True,
        )
        after_status = get_project_bootstrap_status(params.cleaned_dir) if params.commit else None
        _finish_job_success(
            job_id,
            {
                "transaction": transaction,
                "commit": params.commit,
                "update_mode": "bootstrap_full",
                "cleaned_dir": str(cleaned_dir.resolve()),
                "core_rule_summary": project_rule_summary.get("core_rules"),
                "bootstrap_status_before": before_status,
                "bootstrap_status_after": after_status,
                "clean_stats": dataset.stats,
                "import_summary": import_summary,
                "project_rule_summary": project_rule_summary,
                "warnings": dataset.warnings[:50],
            },
        )
    except Exception as exc:
        _finish_job_error(job_id, exc)


def run_rocom_import_local_job(job_id: str) -> None:
    """执行本地 cleaned JSON 导入。

    该任务不访问远程网络，适合“爬虫已经在别处跑完，只需要把 cleaned JSON
    重新导入数据库”的场景。
    """
    _, raw_params = _mark_job_running(job_id)
    params = RocomImportLocalParams(**raw_params)
    cleaned_dir = _resolve_cleaned_dir(params.cleaned_dir)

    try:
        _update_job_progress(
            job_id,
            {
                "stage": "load_cleaned",
                "message": "Loading local cleaned JSON",
                "current": 0,
                "total": 1,
                "percent": 0,
            },
        )
        dataset = load_cleaned_dataset(cleaned_dir)
        if params.data_version:
            _override_dataset_version(dataset, params.data_version)
        _update_job_progress(
            job_id,
            {
                "stage": "load_cleaned",
                "message": "Loaded local cleaned JSON",
                "current": 1,
                "total": 1,
                "percent": 100,
            },
        )

        _update_job_progress(
            job_id,
            {
                "stage": "import",
                "message": "Importing dataset; commit=false will roll back as dry-run",
                "current": 0,
                "total": 1,
                "percent": 0,
            },
        )
        import_summary, project_rule_summary, transaction = _import_dataset_with_transaction(
            dataset=dataset,
            commit=params.commit,
            refresh_static=params.refresh_static or params.update_mode == "full",
        )
        _update_job_progress(
            job_id,
            {
                "stage": "import",
                "message": "Import complete",
                "current": 1,
                "total": 1,
                "percent": 100,
            },
        )

        result = {
            "transaction": transaction,
            "commit": params.commit,
            "update_mode": params.update_mode,
            "cleaned_dir": str(cleaned_dir.resolve()),
            "clean_stats": dataset.stats,
            "import_summary": import_summary,
            "project_rule_summary": project_rule_summary,
            "warnings": dataset.warnings[:50],
        }
        _finish_job_success(job_id, result)
    except Exception as exc:
        _finish_job_error(job_id, exc)


def _override_dataset_version(dataset: Any, data_version: str) -> None:
    """覆盖 cleaned 数据集中的 data_version 字段。

    本地导入时可能需要给同一批 cleaned JSON 打上新的规则版本号。这里只改
    静态规则主表相关行，不修改警告和统计信息。
    """
    for row in dataset.elves:
        row["data_version"] = data_version
    for row in dataset.skills:
        row["data_version"] = data_version
    for row in dataset.type_effectiveness_rules:
        row["data_version"] = data_version


def _import_dataset_with_transaction(
    *,
    dataset: Any,
    commit: bool,
    refresh_static: bool = False,
    ensure_core: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """导入数据集和项目规则种子，并按 commit 决定提交或回滚。"""
    init_db()
    db = SessionLocal()
    try:
        core_rule_summary: dict[str, Any] | None = None
        if ensure_core:
            core_rule_summary = {
                "natures": asdict(ensure_core_natures(db)),
                "core_skills": asdict(ensure_core_skills(db)),
            }
        import_summary = import_dataset(
            db,
            dataset,
            refresh_static=refresh_static,
        )
        project_rule_summary = import_project_seed_rules(db)
        if core_rule_summary is not None:
            project_rule_summary = {
                **project_rule_summary,
                "core_rules": core_rule_summary,
            }
        if commit:
            db.commit()
            transaction = "committed"
        else:
            db.rollback()
            transaction = "rolled_back_dry_run"
        return import_summary, project_rule_summary, transaction
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _import_project_seed_rules_with_transaction(*, commit: bool) -> tuple[dict[str, Any], str]:
    """只导入项目规则种子，用于远程 new_only 无新增时补齐空库规则。"""
    init_db()
    db = SessionLocal()
    try:
        project_rule_summary = import_project_seed_rules(db)
        if commit:
            db.commit()
            transaction = "committed"
        else:
            db.rollback()
            transaction = "rolled_back_dry_run"
        return project_rule_summary, transaction
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def import_project_seed_rules(db: Session) -> dict[str, Any]:
    """导入本项目运行必需的状态定义与人工技能规则。

    rocom cleaned 只负责精灵/技能/可学习关系等 BWIKI 基础数据；状态系统还依赖
    仓库内稳定 effect_id 的人工规则种子。把这一步并入本地/远程数据导入事务后，
    新电脑或空库不会出现“技能有结构化操作但 effect_definition 为空”的半成品状态。
    """
    effect_summaries: list[dict[str, Any]] = []
    for path in PROJECT_EFFECT_SEED_FILES:
        rows = read_effect_rows(path)
        summary = import_effect_definitions(db, rows)
        effect_summaries.append({"path": str(path), **summary})

    review_summaries: list[dict[str, Any]] = []
    for path in PROJECT_SKILL_REVIEW_SEED_FILES:
        rows = read_review_rows(path)
        summary = import_skill_rule_reviews(db, rows)
        review_summaries.append({"path": str(path), **summary})

    return {
        "effect_seed_files": effect_summaries,
        "skill_review_seed_files": review_summaries,
    }


def start_rocom_update_thread(params: RocomUpdateParams) -> dict[str, Any]:
    """创建并用守护线程启动更新任务，供启动时被动更新使用。"""
    job = create_rocom_update_job(params)
    thread = Thread(target=run_rocom_update_job, args=(job["job_id"],), daemon=True)
    thread.start()
    return job
