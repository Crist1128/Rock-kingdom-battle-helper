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
    data_version: str | None = Field(
        default=None,
        description="写入数据版本号；为空则按 UTC 日期生成",
    )
    write_artifacts: bool = Field(default=True, description="是否写 raw/cleaned JSON 文件便于审阅")
    refresh_static: bool = Field(
        default=False,
        description="是否按全量刷新处理 rocom 静态数据，重建 BWIKI 技能关系并软删除缺失静态项",
    )
    update_mode: str = Field(
        default="incremental",
        description="更新模式：incremental=增量更新；full=全量刷新；new_only=只抓取远程新增精灵",
    )


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
    refresh_static: bool = Field(
        default=False,
        description="是否按全量刷新处理 rocom 静态数据，重建 BWIKI 技能关系并软删除缺失静态项",
    )
    update_mode: str = Field(
        default="incremental",
        description="本地导入模式：incremental=增量导入；full=全量刷新",
    )


class ProjectBootstrapLocalRequest(BaseModel):
    """空库一键本地初始化请求。"""

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
    progress: dict[str, Any] = Field(default_factory=dict, description="后台任务进度")


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


class ProjectDataFileStatus(BaseModel):
    """本地数据文件状态。"""

    name: str = Field(description="文件名")
    path: str = Field(description="后端本机绝对路径")
    exists: bool = Field(description="文件是否存在")
    size_bytes: int = Field(default=0, description="文件大小，单位 byte")


class ProjectRequiredDataItem(BaseModel):
    """空库使用前需要准备的数据项说明。"""

    key: str = Field(description="数据项稳定键")
    name: str = Field(description="面向用户展示的数据项名称")
    source: str = Field(description="数据来源或仓库位置")
    import_path: str = Field(description="推荐导入路径")
    auto_on_startup: bool = Field(description="是否会在后端启动时自动补齐")


class ProjectDataBootstrapStatus(BaseModel):
    """空库初始化数据状态响应。"""

    ready: bool = Field(description="数据库是否已具备当前基础运行所需数据")
    checked_at: str = Field(description="检查时间 ISO 字符串")
    counts: dict[str, int] = Field(default_factory=dict, description="关键静态表当前行数")
    missing_required: list[str] = Field(default_factory=list, description="缺失的必要数据说明")
    local_cleaned_dir: str = Field(description="当前检查的本地 cleaned 目录")
    local_package_ready: bool = Field(description="本地 cleaned 必需文件是否齐备")
    cleaned_files: list[ProjectDataFileStatus] = Field(
        default_factory=list,
        description="本地 cleaned 必需文件状态",
    )
    seed_files: list[ProjectDataFileStatus] = Field(
        default_factory=list,
        description="仓库内项目 seed 文件状态",
    )
    recommended_action: str = Field(description="面向用户的下一步建议")
    required_data: list[ProjectRequiredDataItem] = Field(
        default_factory=list,
        description="空库使用前必要数据清单",
    )


class StaticSkillRuleSyncItem(BaseModel):
    """待同步的 structured 技能规则条目。"""

    skill_id: str
    skill_name: str
    review_status: str
    review_notes: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    has_damage_rule: bool = False
    has_hit_rule: bool = False
    has_effect_operations: bool = False


class StaticSkillRuleSyncRequest(BaseModel):
    """静态技能规则同步请求。"""

    commit: bool = Field(default=False, description="是否实际提交数据库事务；False 为 dry-run")
    skill_ids: list[str] | None = Field(
        default=None,
        description="只同步指定技能；为空表示同步所有待同步 structured 技能",
    )
    q: str | None = Field(
        default=None,
        description="可选技能名/ID 筛选；用于只同步当前筛选范围内的待同步规则",
    )


class StaticSkillRuleSyncResponse(BaseModel):
    """静态技能规则同步检查/执行响应。"""

    source: str
    query: str | None = None
    total_rows: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    structured_total: int
    up_to_date_count: int
    pending_count: int
    pending_items: list[StaticSkillRuleSyncItem] = Field(default_factory=list)
    pending_items_truncated: bool = False
    missing_skills: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    applied_skill_ids: list[str] = Field(default_factory=list)
    applied_count: int = 0
    transaction: str
