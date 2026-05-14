"""
战斗运行时模型模块。

本模块定义战斗中实时变化的数据模型，包括：
- 战斗主表（Battle）：记录战斗的基本信息和当前状态
- 战斗精灵状态（BattleElfState）：记录本场战斗中每只精灵的实时状态
- 战斗技能槽（BattleSkillSlot）：记录技能槽的实时状态

这些数据随战斗进行而更新，战斗结束后可选择归档保存。
"""

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Battle(TimestampMixin, Base):
    """
    战斗主表模型。

n    记录一场战斗的基本信息、当前阶段、回合数和上场精灵。
    每场战斗有唯一的 battle_id，贯穿战斗的整个生命周期。

    Attributes:
        battle_id: 战斗唯一标识（主键）
        battle_name: 战斗名称（可选，用于标识）
        phase: 当前阶段（preparation/battle/finished/archived）
        turn_number: 当前回合数
        self_active_elf_id: 己方当前上场精灵 ID
        enemy_active_elf_id: 敌方当前上场精灵 ID
        current_snapshot_id: 当前状态快照 ID
        notes: 备注信息
    """

    __tablename__ = "battle"
    __table_args__ = (Index("idx_battle_phase", "phase"),)

    battle_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_name: Mapped[str | None] = mapped_column(String, nullable=True)
    phase: Mapped[str] = mapped_column(String, nullable=False, default="preparation")
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    self_active_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    enemy_active_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    current_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BattleElfState(TimestampMixin, Base):
    """
    战斗中精灵运行时状态模型。

    记录本场战斗中每只精灵的实时状态，包括：
    - 基础信息（精灵 ID、名称、头像）
    - 面板属性（六维最终值）
    - 当前状态（生命、能量）
    - 技能信息
    - 状态效果关联
    - 战斗状态（是否在场、是否战败）

    注意：所有状态效果通过 BattleEffectInstance 关联，不直接存储在此表。

    Attributes:
        state_id: 状态记录唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        side: 所属阵营（self/enemy）
        elf_id: 精灵定义 ID（外键）
        elf_name: 精灵显示名称（冗余存储，便于查询）
        avatar: 精灵头像（冗余存储）
        panel_stats_json: 面板属性六维（JSON 格式）
        current_hp_value: 当前生命值（数值）
        current_hp_percent: 当前生命百分比
        energy: 当前能量值
        skill_ids_json: 携带技能列表（JSON 格式）
        confirmed_skill_ids_json: 已确认技能列表（JSON 格式）
        active_effect_instance_ids_json: 生效状态实例列表（JSON 格式）
        is_active_elf: 是否为当前上场精灵
        is_defeated: 是否已战败
        last_switch_turn: 上次切换回合
        manual_override: 是否被手动覆盖
    """

    __tablename__ = "battle_elf_state"
    __table_args__ = (
        # 复合索引：便于查询特定战斗的特定阵营的特定精灵
        Index("idx_battle_elf_state_battle_side_elf", "battle_id", "side", "elf_id"),
        # 复合索引：便于查询当前上场精灵
        Index("idx_battle_elf_state_active", "battle_id", "side", "is_active_elf"),
    )

    state_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    elf_name: Mapped[str] = mapped_column(String, nullable=False)
    avatar: Mapped[str] = mapped_column(String, nullable=False)

    # 面板属性（JSON 格式存储六维）
    panel_stats_json: Mapped[str] = mapped_column(Text, nullable=False)
    # 当前状态
    current_hp_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_hp_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 技能信息
    skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_skill_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_effect_instance_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 战斗状态
    is_active_elf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_defeated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_switch_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BattleSkillSlot(TimestampMixin, Base):
    """
    战斗中的技能槽状态模型。

    记录战斗中技能槽的实时状态，用于能耗、威力、冷却等技能槽修正。
    技能槽修正是 BattleEffectSystem 的一部分，可以通过状态实例关联。

    Attributes:
        slot_id: 技能槽记录唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        side: 所属阵营（self/enemy）
        elf_id: 所属精灵 ID（外键）
        slot_index: 技能槽位置（0-3）
        skill_id: 技能定义 ID（外键）
        current_energy_cost: 当前能量消耗（可能受状态影响）
        current_power: 当前威力（可能受状态影响）
        cooldown_remaining: 剩余冷却回合
        active_effect_instance_ids_json: 生效的状态实例列表（JSON 格式）
        manual_override: 是否被手动覆盖
    """

    __tablename__ = "battle_skill_slot"
    __table_args__ = (
        # 复合索引：便于查询特定战斗特定精灵的所有技能槽
        Index("idx_battle_skill_slot_battle_elf", "battle_id", "side", "elf_id"),
        # 索引：便于查询特定技能的使用情况
        Index("idx_battle_skill_slot_skill", "skill_id"),
    )

    slot_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definition.skill_id"), nullable=False)
    current_energy_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooldown_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_effect_instance_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
