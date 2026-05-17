"""数据更新管理接口。

这些接口属于管理动作，默认需要由用户主动触发。后端普通启动不应依赖远程
爬虫或自动写库，避免 BWIKI 网络波动影响本地战斗记录功能。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status

from app.core.config import settings
from app.schemas.data_update import (
    RocomCheckRequest,
    RocomCheckResponse,
    RocomDataUpdateAccepted,
    RocomDataUpdateJobStatus,
    RocomDataUpdateRequest,
    RocomLocalImportRequest,
)
from app.services.rocom_data_update_service import (
    RocomCheckParams,
    RocomImportLocalParams,
    RocomUpdateParams,
    check_rocom_remote_updates,
    create_rocom_import_local_job,
    create_rocom_update_job,
    get_rocom_update_job,
    list_rocom_update_jobs,
    run_rocom_import_local_job,
    run_rocom_update_job,
)

router = APIRouter()


def verify_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """如果配置了 ADMIN_UPDATE_TOKEN，则要求请求头 X-Admin-Token 匹配。"""
    if settings.admin_update_token and x_admin_token != settings.admin_update_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid admin token")


@router.post(
    "/rocom/check",
    response_model=RocomCheckResponse,
    summary="检查洛克王国 BWIKI 图鉴列表是否可能有新增精灵",
)
def check_rocom_updates(
    request: RocomCheckRequest,
    _: None = Depends(verify_admin_token),
) -> RocomCheckResponse:
    """只检查远程列表与本地 rocom 精灵 ID 差异，不爬详情、不写库。"""
    try:
        result = check_rocom_remote_updates(RocomCheckParams(**request.model_dump()))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"remote check failed: {exc}") from exc
    return RocomCheckResponse(**result)


@router.post(
    "/rocom/sync",
    response_model=RocomDataUpdateAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="触发洛克王国 BWIKI 数据同步",
)
def start_rocom_sync(
    request: RocomDataUpdateRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_admin_token),
) -> RocomDataUpdateAccepted:
    """主动触发爬取、清洗和导入；默认 dry-run，不提交数据库。"""
    params = RocomUpdateParams(**request.model_dump())
    try:
        job = create_rocom_update_job(params)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    background_tasks.add_task(run_rocom_update_job, job["job_id"])
    return RocomDataUpdateAccepted(
        job_id=job["job_id"],
        status=job["status"],
        message="数据同步任务已创建；GET /api/v1/admin/data-updates/rocom/jobs/{job_id} 查询状态。",
    )


@router.post(
    "/rocom/import-local",
    response_model=RocomDataUpdateAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="从本地 cleaned JSON 导入洛克王国数据",
)
def start_rocom_import_local(
    request: RocomLocalImportRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(verify_admin_token),
) -> RocomDataUpdateAccepted:
    """不访问远程，只把已经存在的 cleaned JSON dry-run 或写入数据库。"""
    params = RocomImportLocalParams(**request.model_dump())
    try:
        job = create_rocom_import_local_job(params)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    background_tasks.add_task(run_rocom_import_local_job, job["job_id"])
    return RocomDataUpdateAccepted(
        job_id=job["job_id"],
        status=job["status"],
        message="本地导入任务已创建；GET /api/v1/admin/data-updates/rocom/jobs/{job_id} 查询状态。",
    )


@router.get(
    "/rocom/jobs/{job_id}",
    response_model=RocomDataUpdateJobStatus,
    summary="查询洛克王国数据更新任务状态",
)
def get_rocom_sync_job(
    job_id: str,
    _: None = Depends(verify_admin_token),
) -> RocomDataUpdateJobStatus:
    """查询单个更新任务状态。"""
    job = get_rocom_update_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    job.pop("traceback", None)
    return RocomDataUpdateJobStatus(**job)


@router.get(
    "/rocom/jobs",
    response_model=list[RocomDataUpdateJobStatus],
    summary="列出最近的洛克王国数据更新任务",
)
def list_rocom_sync_jobs(_: None = Depends(verify_admin_token)) -> list[RocomDataUpdateJobStatus]:
    """列出最近任务。"""
    jobs = list_rocom_update_jobs()
    for job in jobs:
        job.pop("traceback", None)
    return [RocomDataUpdateJobStatus(**job) for job in jobs]
