"""
状态效果模型模块。

本模块定义统一状态系统的核心模型，包括：
- 状态实例（BattleEffectInstance）：战斗中实际存在的状态效果
- 状态快照（BattleEffectSnapshot）：某一时刻所有状态的完整记录

统一状态系统是设计的核心概念，所有状态（印记、天气、异常、属性修正）
都使用相同的模型结构，通过字段区分不同类型和行为。
"""

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BattleEffectInstance(TimestampMixin, Base):
    """
    战斗内状态实例模型。

    统一状态系统的核心模型，所有状态效果（印记、天气、异常、普通增减益）
    都存储在此表中，通过字段区分具体类型和行为。

    状态实例记录状态的当前状态，包括：
    - 所属范围和目标
    - 层数和剩余时间
    - 来源信息
    - 识别可信度

    Attributes:
        instance_id: 实例唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        effect_id: 状态定义 ID（外键关联 effect_definition）
        category: 状态分类（冗余存储，便于查询）
        owner_scope: 归属范围（elf/side/field/skill_slot/turn）
        owner_side: 归属阵营（self/enemy，owner_scope=elf 时有效）
        owner_elf_id: 归属精灵 ID（owner_scope=elf 时有效）
        owner_skill_slot_id: 归属技能槽 ID（owner_scope=skill_slot 时有效）
        field_id: 战场标识（owner_scope=field 时有效）
        source_side: 来源阵营
        source_elf_id: 来源精灵 ID
        source_skill_id: 来源技能 ID
        source_event_id: 来源事件 ID
        layers: 当前层数
        remaining_turns: 剩余回合数
        remaining_uses: 剩余使用次数
        is_active: 是否处于生效状态
        applied_turn: 施加回合
        expire_turn: 过期回合
        last_updated_turn: 最后更新回合
        recognition_source: 识别来源
        recognition_confidence: 识别可信度
        manual_override: 是否被手动覆盖
        notes: 备注
    """

    __tablename__ = "battle_effect_instance"
    __table_args__ = (
        # 复合索引：便于查询特定战斗的特定目标的所有状态
        Index("idx_effect_instance_battle_owner", "battle_id", "owner_side", "owner_elf_id"),
        # 索引：便于按分类查询（如查询所有印记）
        Index("idx_effect_instance_battle_category", "battle_id", "category"),
        # 索引：便于查询所有生效状态
        Index("idx_effect_instance_active", "battle_id", "is_active"),
    )

    instance_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    effect_id: Mapped[str] = mapped_column(ForeignKey("effect_definition.effect_id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)

    # 归属信息（状态跟随的目标）
    owner_scope: Mapped[str] = mapped_column(String, nullable=False)
    owner_side: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_skill_slot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    field_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # 来源信息（状态从何而来）
    source_side: Mapped[str | None] = mapped_column(String, nullable=True)
    source_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_skill_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # 状态数值
    layers: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    remaining_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 时间信息
    applied_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expire_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_updated_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 识别和覆盖信息
    recognition_source: Mapped[str | None] = mapped_column(String, nullable=True)
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BattleEffectSnapshot(TimestampMixin, Base):
    """
    状态快照模型。

    记录事件发生瞬间的所有状态信息，用于：
    - 伤害计算（基于事件发生时的状态）
    - 候选过滤（基于事件发生时的面板属性）
    - 事件回放（重现事件发生时的场景）
    - 纠错重算（从特定时间点重新计算）

    快照保存的是状态实例的完整副本，而不只是实例 ID，
    确保状态后续变化不会影响历史事件的解释。

    Attributes:
        snapshot_id: 快照唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        turn_number: 回合数
        active_effect_instance_ids_json: 生效状态实例 ID 列表（JSON 格式）
        self_active_elf_id: 己方当前上场精灵 ID
        enemy_active_elf_id: 敌方当前上场精灵 ID
        self_elf_effect_ids_json: 己方精灵状态 ID 列表（JSON 格式）
        enemy_elf_effect_ids_json: 敌方精灵状态 ID 列表（JSON 格式）
        self_side_effect_ids_json: 己方队伍状态 ID 列表（JSON 格式）
        enemy_side_effect_ids_json: 敌方队伍状态 ID 列表（JSON 格式）
        field_effect_ids_json: 战场状态 ID 列表（JSON 格式）
        skill_slot_effect_ids_json: 技能槽状态 ID 列表（JSON 格式）
        turn_effect_ids_json: 回合状态 ID 列表（JSON 格式）
        full_snapshot_json: 完整快照数据（JSON 格式，包含所有状态详情）
        source_event_id: 触发此快照的事件 ID
    """

    __tablename__ = "battle_effect_snapshot"
    __table_args__ = (
        # 复合索引：便于查询特定回合的所有快照
        Index("idx_effect_snapshot_battle_turn", "battle_id", "turn_number", "created_at"),
        # 索引：便于通过事件查询对应的快照
        Index("idx_effect_snapshot_source_event", "source_event_id"),
    )

    snapshot_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # 生效状态列表（ID 列表，便于快速查询）
    active_effect_instance_ids_json: Mapped[str] = mapped_column(Text, nullable=False)

    # 当前上场精灵
    self_active_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    enemy_active_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # 按归属范围分组的状态 ID 列表
    self_elf_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enemy_elf_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    self_side_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enemy_side_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_slot_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_effect_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 完整快照数据（包含所有状态实例的完整信息）
    full_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
