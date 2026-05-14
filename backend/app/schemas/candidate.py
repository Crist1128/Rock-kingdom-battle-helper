"""
候选配置相关 Schema。

这些 Schema 用于查询敌方候选配置生成结果。第一阶段只提供候选数量、
速度范围和置信度摘要，不暴露大量候选明细，避免一次性返回数万行数据。
"""

from pydantic import BaseModel, Field


class CandidateSummaryOut(BaseModel):
    """
    敌方候选配置摘要。

    Attributes:
        battle_id: 战斗 ID。
        elf_id: 敌方精灵 ID。
        total_count: 候选总数。
        active_count: 尚未排除的候选数量。
        excluded_count: 已排除的候选数量。
        min_speed: 尚未排除候选中的最低速度。
        max_speed: 尚未排除候选中的最高速度。
        top_confidence: 当前最高置信度。
        formula_status: 公式状态。第一阶段为 formula_unavailable。
    """

    battle_id: str
    elf_id: str
    total_count: int = 0
    active_count: int = 0
    excluded_count: int = 0
    min_speed: int | None = None
    max_speed: int | None = None
    top_confidence: float | None = None
    formula_status: str = "formula_unavailable"


class CandidateOut(BaseModel):
    """
    候选配置输出。

    仅用于分页查看少量候选。完整候选集可能非常大，前端默认应优先使用
    CandidateSummaryOut。
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
