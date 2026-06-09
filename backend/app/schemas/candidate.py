"""
旧候选配置相关 Schema。

已废弃：项目主流程已经切换到 `EnemyPanelEstimate` 实时属性约束和默认展示配置。
本模块仅为旧 `build_candidate` 表和遗留测试保留，后续删除旧表时同步移除。
新接口和前端类型不得继续引用这里的 Candidate* 输出。
"""

from pydantic import BaseModel, Field


class CandidateSummaryOut(BaseModel):
    """
    已废弃的敌方候选配置摘要。

    Attributes:
        battle_id: 战斗 ID。
        elf_id: 敌方精灵 ID。
        total_count: 候选总数。
        active_count: 尚未排除的候选数量。
        excluded_count: 已排除的候选数量。
        min_speed: 尚未排除候选中的最低速度。
        max_speed: 尚未排除候选中的最高速度。
        top_confidence: 当前最高置信度。
        formula_status: 旧公式与候选评分状态；主流程不再读取。
    """

    battle_id: str
    elf_id: str
    total_count: int = 0
    active_count: int = 0
    excluded_count: int = 0
    min_speed: int | None = None
    max_speed: int | None = None
    top_confidence: float | None = None
    formula_status: str = "legacy_candidate_space_disabled"


class CandidateOut(BaseModel):
    """
    已废弃的候选配置输出。

    保留给旧表迁移前的兼容代码。前端主流程应使用 `EnemyPanelEstimateOut`。
    """

    candidate_id: str
    battle_id: str
    side: str
    elf_id: str
    nature_id: str
    individual_talent_distribution_json: str
    final_hp: int
    final_physical_attack: int
    final_physical_defense: int
    final_magic_attack: int
    final_magic_defense: int
    final_speed: int
    possible_skill_ids_json: str | None = None
    confirmed_skill_ids_json: str | None = None
    match_score: float = 0.0
    confidence: float = 0.0
    is_excluded: bool = False
    excluded_reason: str | None = None

    model_config = {"from_attributes": True}


class CandidateListQuery(BaseModel):
    """
    候选配置列表查询参数。

    FastAPI 端点中主要使用 Query 参数，此模型用于文档说明和后续复用。
    """

    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    include_excluded: bool = False


class CandidateNatureDistributionItem(BaseModel):
    """候选配置中的性格分布项。"""

    nature_id: str
    count: int
    ratio: float


class CandidateTalentDistributionItem(BaseModel):
    """某一属性维度的个体资质取值分布。"""

    stat_key: str
    non_zero_count: int
    zero_count: int
    value_counts: dict[str, int] = Field(default_factory=dict)


class CandidatePatternDistributionItem(BaseModel):
    """个体资质存在维度组合的分布，例如 magic_attack+speed。"""

    pattern: str
    count: int
    ratio: float


class CandidateSpeedBucketItem(BaseModel):
    """速度分桶分布项。"""

    min_speed: int
    max_speed: int
    count: int
    ratio: float


class CandidateDetailOut(BaseModel):
    """
    候选配置详情页数据。

    该响应用于前端详情页展示速度范围、速度分布、性格分布和个体资质分布。
    这些分布只反映旧候选池，不代表实时反推结论。
    """

    summary: CandidateSummaryOut
    speed_buckets: list[CandidateSpeedBucketItem] = Field(default_factory=list)
    nature_distribution: list[CandidateNatureDistributionItem] = Field(default_factory=list)
    talent_distribution: list[CandidateTalentDistributionItem] = Field(default_factory=list)
    pattern_distribution: list[CandidatePatternDistributionItem] = Field(default_factory=list)


class CandidateNatureOptionOut(BaseModel):
    """有效候选中的可选性格。"""

    nature_id: str
    count: int
    ratio: float
    top_confidence: float


class CandidateTalentPatternOptionOut(BaseModel):
    """有效候选中的可选完整个体资质组合。"""

    pattern_key: str
    talent_values: dict[str, int] = Field(default_factory=dict)
    count: int
    ratio: float
    top_confidence: float


class CandidateSelectionOptionsOut(BaseModel):
    """
    候选选择面板数据。

    已废弃。实时方案使用 `/estimates/{battle_id}/{elf_id}` 读取估计档案，
    使用 `/default-config` 保存玩家选择的默认展示配置，不读取 `is_excluded`。
    """

    battle_id: str
    elf_id: str
    active_count: int
    nature_options: list[CandidateNatureOptionOut] = Field(default_factory=list)
    talent_pattern_options: list[CandidateTalentPatternOptionOut] = Field(default_factory=list)
    selected_nature_id: str | None = None
    selected_talent_pattern: str | None = None
    matched_count: int = 0
    panel_candidate: CandidateOut | None = None


class CandidateEvidenceOut(BaseModel):
    """已废弃的候选证据链占位输出。"""

    battle_id: str
    elf_id: str
    formula_status: str = "legacy_candidate_space_disabled"
    evidence_items: list[dict] = Field(default_factory=list)
    message: str = "旧候选空间已下线；请使用实时面板估计 evidence。"
