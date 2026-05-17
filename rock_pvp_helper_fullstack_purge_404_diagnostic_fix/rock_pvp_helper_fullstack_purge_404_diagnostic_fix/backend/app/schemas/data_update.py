"""数据更新接口的请求/响应模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RocomDataUpdateRequest(BaseModel):
    """洛克王国 BWIKI 远程同步请求。"""

    commit: bool = Field(default=False, description="是否实际提交数据库事务；False 为 dry-run")
    force: bool = Field(default=False, description="是否强制重新爬取已缓存精灵")
    limit: int = Field(default=0, ge=0, description="只更新前 N 条；0 表示全量")
    delay: float = Field(default=1.5, ge=0.5, description="请求间隔下限秒数")
    with_images: bool = Field(default=False, description="是否下载图片；MVP 默认仅记录图片 URL")
    data_version: str | None = Field(default=None, description="写入数据版本号；为空则按 UTC 日期生成")
    write_artifacts: bool = Field(default=True, description="是否写 raw/cleaned JSON 文件便于审阅")


class RocomCheckRequest(BaseModel):
    """洛克王国 BWIKI 远程列表检查请求。"""

    limit: int = Field(default=0, ge=0, description="只检查前 N 条；0 表示全量列表")
    include_new_elves_limit: int = Field(
        default=100,
        ge=0,
        le=500,
        description="响应中最多返回多少条新增精灵预览，避免响应过大",
    )


class RocomLocalImportRequest(BaseModel):
    """本地 cleaned JSON 导入请求。"""

    cleaned_dir: str | None = Field(
        default=None,
        description="cleaned JSON 目录；为空时使用 ROCOM_DATA_DIR/cleaned",
    )
    commit: bool = Field(default=False, description="是否实际提交数据库事务；False 为 dry-run")
    data_version: str | None = Field(
        default=None,
        description="可选：覆盖 cleaned 数据中的 data_version",
    )


class RocomDataUpdateAccepted(BaseModel):
    """数据更新任务已受理响应。"""

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    message: str


class RocomDataUpdateJobStatus(BaseModel):
    """数据更新任务状态响应。"""

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: str
    job_type: str = "sync"
    started_at: str | None = None
    finished_at: str | None = None
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


class RocomCheckResponse(BaseModel):
    """远程列表检查响应。"""

    source: str
    status: Literal["changed", "unchanged"]
    checked_at: str
    remote_count: int
    local_rocom_count: int
    new_elf_count: int
    missing_local_count: int
    new_elves: list[dict[str, Any]] = Field(default_factory=list)
    new_elves_truncated: bool = False
    remote_fingerprint: str
    note: str
