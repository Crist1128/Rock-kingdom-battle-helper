"""洛克王国 BWIKI 数据更新服务。

本模块只负责“主动触发”的数据更新管理，不在后端普通启动流程中主动检查
远程站点。这样可以保证本地战斗记录、候选生成等核心功能不受外部网络、BWIKI
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

from sqlalchemy import select

from app.core.config import BACKEND_DIR, settings
from app.data_pipeline.rocom.cleaner import clean_from_raw_sprites, write_cleaned_dataset
from app.data_pipeline.rocom.importer import import_dataset, load_cleaned_dataset
from app.data_pipeline.rocom.scraper import parse_list_page, scrape_rocom_sprites
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.static import ElfDefinition


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
        )
        _jobs[job_id] = job
        return asdict(job)


def create_rocom_update_job(params: RocomUpdateParams) -> dict[str, Any]:
    """创建远程同步任务记录。"""
    return _create_job(asdict(params), job_type="sync")


def create_rocom_import_local_job(params: RocomImportLocalParams) -> dict[str, Any]:
    """创建本地 cleaned JSON 导入任务记录。"""
    return _create_job(asdict(params), job_type="import_local")


def _finish_job_success(job_id: str, result: dict[str, Any]) -> None:
    """把任务标记为成功。"""
    with _jobs_lock:
        job = _jobs[job_id]
        job.status = "succeeded"
        job.finished_at = utc_now_iso()
        job.result = result


def _finish_job_error(job_id: str, exc: Exception) -> None:
    """把任务标记为失败，并保存 traceback 供开发排查。"""
    with _jobs_lock:
        job = _jobs[job_id]
        job.status = "failed"
        job.finished_at = utc_now_iso()
        job.error = str(exc)
        job.traceback = traceback.format_exc()


def _mark_job_running(job_id: str) -> tuple[str, dict[str, Any]]:
    """把任务标记为 running，并返回 job_type 与参数副本。"""
    with _jobs_lock:
        job = _jobs[job_id]
        job.status = "running"
        job.started_at = utc_now_iso()
        return job.job_type, dict(job.params)


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
    cleaned_dir = data_root / "cleaned"
    raw_output = raw_dir / "sprites_raw.json"

    try:
        scrape_result = scrape_rocom_sprites(
            output=raw_output,
            limit=params.limit,
            delay=params.delay,
            with_images=params.with_images,
            force=params.force,
            debug_images=False,
            repair_images=False,
        )
        dataset = clean_from_raw_sprites(
            scrape_result["sprites"],
            image_url_rows=scrape_result["image_urls"],
            data_version=params.data_version,
            image_mode="local" if params.with_images else "remote",
        )
        if params.write_artifacts:
            write_cleaned_dataset(dataset, cleaned_dir)

        import_summary, transaction = _import_dataset_with_transaction(
            dataset=dataset,
            commit=params.commit,
        )

        result = {
            "transaction": transaction,
            "commit": params.commit,
            "raw_output": str(raw_output.resolve()),
            "cleaned_dir": str(cleaned_dir.resolve()) if params.write_artifacts else None,
            "scrape_stats": scrape_result["stats"],
            "clean_stats": dataset.stats,
            "import_summary": import_summary,
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


def run_rocom_import_local_job(job_id: str) -> None:
    """执行本地 cleaned JSON 导入。

    该任务不访问远程网络，适合“爬虫已经在别处跑完，只需要把 cleaned JSON
    重新导入数据库”的场景。
    """
    _, raw_params = _mark_job_running(job_id)
    params = RocomImportLocalParams(**raw_params)
    cleaned_dir = _resolve_cleaned_dir(params.cleaned_dir)

    try:
        dataset = load_cleaned_dataset(cleaned_dir)
        if params.data_version:
            _override_dataset_version(dataset, params.data_version)

        import_summary, transaction = _import_dataset_with_transaction(
            dataset=dataset,
            commit=params.commit,
        )

        result = {
            "transaction": transaction,
            "commit": params.commit,
            "cleaned_dir": str(cleaned_dir.resolve()),
            "clean_stats": dataset.stats,
            "import_summary": import_summary,
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


def _import_dataset_with_transaction(*, dataset: Any, commit: bool) -> tuple[dict[str, Any], str]:
    """导入数据集，并按 commit 决定提交或回滚。"""
    init_db()
    db = SessionLocal()
    try:
        import_summary = import_dataset(db, dataset)
        if commit:
            db.commit()
            transaction = "committed"
        else:
            db.rollback()
            transaction = "rolled_back_dry_run"
        return import_summary, transaction
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def start_rocom_update_thread(params: RocomUpdateParams) -> dict[str, Any]:
    """创建并用守护线程启动更新任务，供启动时被动更新使用。"""
    job = create_rocom_update_job(params)
    thread = Thread(target=run_rocom_update_job, args=(job["job_id"],), daemon=True)
    thread.start()
    return job
