"""
玩家己方配置 Schema。

己方配置是准备阶段复制到 BattleElfState 的确定信息来源。创建配置时，
服务层会根据精灵种族资质、性格和个体资质计算面板属性并缓存。
"""

from pydantic import BaseModel, Field, field_validator


class IndividualTalentInput(BaseModel):
    """
    个体资质输入。

    当前需求规定：存在个体资质的维度取 7-10，不存在的维度按 0 计算。
    为了允许用户逐步录入，本 Schema 只限制范围为 0-10；“1-3 个维度”
    的完整规则在后续可按严格模式校验。
    """

    hp: int = Field(default=0, ge=0, le=10)
    physical_attack: int = Field(default=0, ge=0, le=10)
    physical_defense: int = Field(default=0, ge=0, le=10)
    magic_attack: int = Field(default=0, ge=0, le=10)
    magic_defense: int = Field(default=0, ge=0, le=10)
    speed: int = Field(default=0, ge=0, le=10)


class PlayerElfBuildCreate(BaseModel):
    """
    创建己方精灵配置请求。

    Attributes:
        elf_id: 精灵 ID。
        nature_id: 性格 ID。
        individual_talent_distribution: 六维个体资质。
        skill_ids: 携带技能列表，按槽位顺序保存。
        build_name: 用户自定义配置名。
        is_default: 是否作为该精灵默认配置。
        notes: 备注。
    """

    elf_id: str = Field(..., description="精灵 ID")
    nature_id: str = Field(..., description="性格 ID")
    individual_talent_distribution: IndividualTalentInput = Field(..., description="个体资质")
    skill_ids: list[str] = Field(default_factory=list, description="按槽位顺序排列的技能 ID")
    build_name: str | None = Field(default=None, description="配置名称")
    is_default: bool = Field(default=False, description="是否默认配置")
    notes: str | None = Field(default=None, description="备注")

    @field_validator("skill_ids")
    @classmethod
    def validate_skill_count(cls, value: list[str]) -> list[str]:
        """限制第一阶段手动配置最多 4 个技能槽。"""
        if len(value) > 4:
            raise ValueError("最多只能配置 4 个技能")
        if len(set(value)) != len(value):
            raise ValueError("技能列表不能包含重复 skill_id")
        return value


class PlayerElfBuildOut(BaseModel):
    """
    己方配置输出。

    skill_ids 来自 player_elf_build_skill 表，服务层负责合并。
    """

    build_id: str
    build_name: str | None = None
    elf_id: str
    nature_id: str
    individual_talent_distribution_json: str
    final_stats_json: str | None = None
    skill_ids: list[str] = Field(default_factory=list)
    is_default: bool = False
    notes: str | None = None
