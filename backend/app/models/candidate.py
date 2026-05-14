"""
候选配置模型模块。

本模块定义敌方配置推算相关的数据模型，包括：
- BuildCandidate: 敌方候选配置，记录敌方精灵可能的配置组合
- CalculationCache: 计算缓存，用于缓存伤害计算等昂贵操作的结果

候选配置是敌方配置推算的核心，系统通过伤害事件不断过滤和收敛候选集合。
"""

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BuildCandidate(TimestampMixin, Base):
    """
    敌方候选配置模型。

    记录敌方精灵可能的配置组合，包括：
    - 性格选择
    - 个体资质分布
    - 最终面板属性（六维）
    - 可能的技能组
    - 匹配评分和置信度
    - 排除状态和原因

    候选配置在准备阶段生成，在战斗过程中通过伤害事件不断被过滤。
    只保存面板属性，不保存经过状态修正后的临时属性。

    Attributes:
        candidate_id: 候选配置唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        side: 所属阵营（默认为 enemy）
        elf_id: 精灵定义 ID（外键）
        nature_id: 性格定义 ID（外键）
        individual_talent_distribution_json: 个体资质分布（JSON 格式）
        final_hp: 最终生命属性
        final_physical_attack: 最终物攻属性
        final_physical_defense: 最终物防属性
        final_magic_attack: 最终魔攻属性
        final_magic_defense: 最终魔防属性
        final_speed: 最终速度属性
        possible_skill_ids_json: 可能携带的技能列表（JSON 格式）
        confirmed_skill_ids_json: 已确认的技能列表（JSON 格式）
        skill_weights_json: 技能权重（JSON 格式）
        match_score: 匹配评分（与观察数据的匹配程度）
        confidence: 置信度（该配置成立的可能性）
        is_excluded: 是否已被排除
        excluded_reason: 被排除的原因
        evidence_ids_json: 支持证据列表（JSON 格式）
        matched_event_ids_json: 匹配的事件列表（JSON 格式）
        mismatched_event_ids_json: 不匹配的事件列表（JSON 格式）
    """

    __tablename__ = "build_candidate"
    __table_args__ = (
        # 复合索引：便于查询特定精灵的未排除候选
        Index("idx_build_candidate_battle_elf_excluded", "battle_id", "elf_id", "is_excluded"),
        # 复合索引：便于按置信度排序查询候选
        Index("idx_build_candidate_confidence", "battle_id", "elf_id", "confidence"),
    )

    candidate_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False, default="enemy")
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    nature_id: Mapped[str] = mapped_column(ForeignKey("nature_definition.nature_id"), nullable=False)
    individual_talent_distribution_json: Mapped[str] = mapped_column(Text, nullable=False)

    # 最终面板属性六维
    final_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    final_physical_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    final_physical_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    final_magic_attack: Mapped[int] = mapped_column(Integer, nullable=False)
    final_magic_defense: Mapped[int] = mapped_column(Integer, nullable=False)
    final_speed: Mapped[int] = mapped_column(Integer, nullable=False)

    # 技能信息
    possible_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_weights_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 评分和置信度
    match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 证据记录
    evidence_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_event_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    mismatched_event_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class CalculationCache(TimestampMixin, Base):
    """
    计算缓存模型。

    用于缓存昂贵的计算结果，如伤害计算、速度判断等。
    通过缓存键（cache_key）快速查找已有计算结果，避免重复计算。

    Attributes:
        cache_id: 缓存记录唯一标识（主键）
        cache_key: 缓存键（唯一，用于快速查找）
        cache_type: 缓存类型（damage/speed/inference 等）
        battle_id: 所属战斗 ID（可选）
        snapshot_id: 关联的快照 ID（可选）
        payload_json: 缓存数据（JSON 格式）
        expire_at: 过期时间（可选，用于定期清理）
    """

    __tablename__ = "calculation_cache"
    __table_args__ = (Index("idx_calculation_cache_key", "cache_key", unique=True),)

    cache_id: Mapped[str] = mapped_column(String, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String, nullable=False)
    cache_type: Mapped[str] = mapped_column(String, nullable=False)
    battle_id: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    expire_at: Mapped[str | None] = mapped_column(String, nullable=True)
