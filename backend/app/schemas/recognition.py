"""截图识别相关 API Schema。"""

from pydantic import BaseModel, Field


class RecognitionBoxOut(BaseModel):
    """截图中的头像裁剪框坐标。"""

    x1: int = Field(..., description="左上角 x 坐标")
    y1: int = Field(..., description="左上角 y 坐标")
    x2: int = Field(..., description="右下角 x 坐标")
    y2: int = Field(..., description="右下角 y 坐标")


class EnemyAvatarMatchedElfOut(BaseModel):
    """识别候选映射到数据库中的精灵定义。"""

    elf_id: str = Field(..., description="数据库精灵 ID")
    elf_name: str = Field(..., description="数据库精灵名称")
    avatar: str = Field(..., description="数据库头像 URL 或路径")
    element_types_json: str = Field(..., description="精灵系别 JSON 字符串")
    data_version: str | None = Field(default=None, description="静态数据版本")
    is_opening_eligible: bool = Field(default=True, description="是否适合作为准备阶段开局阵容精灵")
    recognition_role: str = Field(
        default="opening_candidate",
        description="识别映射角色：opening_candidate/runtime_form",
    )
    related_opening_elf_id: str | None = Field(
        default=None,
        description="局内形态对应的可开局基础精灵 ID",
    )
    relation_reason: str | None = Field(default=None, description="形态关系说明")


class EnemyAvatarCandidateOut(BaseModel):
    """单个头像模板匹配候选。"""

    dex_no: str = Field(..., description="头像素材文件名中的图鉴编号")
    elf_name: str = Field(..., description="头像素材文件名中的精灵名称")
    file_name: str = Field(..., description="命中的头像模板文件名")
    icon_url: str = Field(..., description="本地模板头像可访问 URL")
    score: float = Field(..., description="综合匹配分，越高越相似")
    spatial_score: float = Field(..., description="分块颜色直方图相似度")
    histogram_score: float = Field(..., description="全局颜色直方图相似度")
    pixel_score: float = Field(..., description="中心区域像素相似度")
    hash_score: float = Field(..., description="感知哈希相似度")
    edge_score: float = Field(..., description="边缘轮廓哈希相似度")
    confidence_level: str = Field(..., description="粗略置信等级 high/medium/low")
    matched_elves: list[EnemyAvatarMatchedElfOut] = Field(
        default_factory=list,
        description="按图鉴编号和名称映射到数据库的准备阶段可选精灵；可能为空或多个",
    )
    related_forms: list[EnemyAvatarMatchedElfOut] = Field(
        default_factory=list,
        description="同图鉴编号/同进化链的局内形态提示；不用于准备阶段自动采用",
    )


class EnemyAvatarSlotRecognitionOut(BaseModel):
    """敌方阵容单个槽位的截图识别结果。"""

    slot_index: int = Field(..., description="槽位序号，1-6")
    box: RecognitionBoxOut = Field(..., description="用于识别的头像裁剪框")
    location_method: str = Field(
        ...,
        description="头像定位方法：black_slot/green_hp_bar/fixed_reference",
    )
    location_confidence: float = Field(..., description="头像定位置信度，仅用于提示定位可靠性")
    candidates: list[EnemyAvatarCandidateOut] = Field(
        default_factory=list,
        description="该槽位的 TopK 头像识别候选",
    )


class EnemyAvatarSlotDebugOut(BaseModel):
    """单个槽位的头像识别调试图片。"""

    slot_index: int = Field(..., description="槽位序号，1-6")
    crop_url: str = Field(..., description="该槽位实际裁剪图 URL")
    detail_url: str = Field(..., description="原图、抄像、对齐和差异热力图综合对比 URL")
    top5_url: str = Field(..., description="该槽位 TopK 透明抄像候选对比 URL")


class EnemyLineupRecognitionDebugOut(BaseModel):
    """敌方阵容头像识别调试产物。"""

    run_id: str = Field(..., description="本次调试产物运行 ID")
    expires_after_seconds: int = Field(..., description="调试产物保留秒数，超过后会被后续请求清理")
    annotated_image_url: str = Field(..., description="整张截图框选识别结果 URL")
    contact_sheet_url: str = Field(..., description="全槽位候选总览图 URL")
    slots: list[EnemyAvatarSlotDebugOut] = Field(
        default_factory=list,
        description="每个槽位的裁剪图、详细对比图和 TopK 图 URL",
    )


class EnemyLineupRecognitionOut(BaseModel):
    """敌方阵容截图识别响应。"""

    source_image_size: tuple[int, int] = Field(..., description="上传截图尺寸，格式为 [宽, 高]")
    icon_template_count: int = Field(..., description="当前加载的头像模板数量")
    slots: list[EnemyAvatarSlotRecognitionOut] = Field(..., description="6 个敌方槽位识别结果")
    warnings: list[str] = Field(
        default_factory=list,
        description="识别过程中的提示；本接口只给候选，不自动写入阵容",
    )
    debug_artifacts: EnemyLineupRecognitionDebugOut | None = Field(
        default=None,
        description="可选调试图片产物；用于前端查看截图框选和抄像实际效果",
    )
