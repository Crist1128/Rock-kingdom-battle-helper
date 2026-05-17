"""
战斗事件模型模块。

本模块定义战斗事件的存储结构，采用"主事件+子事件"的设计：
- BattleEvent: 通用事件主表，记录所有事件的基础信息
- DamageEvent: 伤害事件详情
- EffectChangeEvent: 状态变化事件详情
- ResourceChangeEvent: 资源变化事件详情

这种设计允许不同类型的事件有自己的特定字段，同时共享基础事件信息。
所有事件都引用 BattleEffectSnapshot，确保事件可解释和可回放。
"""

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BattleEvent(TimestampMixin, Base):
    """
    通用战斗事件模型。

    所有战斗事件的入口，记录事件的基础信息：
    - 事件类型和回合
    - 行动方和目标
    - 关联的技能和快照
    - 数据来源和可信度

    具体事件数据存储在子事件表中，通过 event_id 关联。

    Attributes:
        event_id: 事件唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        turn_number: 发生回合
        action_order: 同一回合内的人工排序号
        event_type: 事件类型（skill_use/damage/effect_apply 等）
        actor_side: 行动方阵营
        actor_elf_id: 行动方精灵 ID
        target_side: 目标方阵营
        target_elf_id: 目标方精灵 ID
        skill_id: 关联技能 ID
        skill_confirmed: 技能是否已确认
        snapshot_id: 关联状态快照 ID
        source: 事件来源（manual_input/auto_recognition/system_inferred 等）
        recognition_confidence: 识别可信度
        manual_override: 是否被手动覆盖
        corrected_event_id: 当前事件修正的历史事件 ID
        is_voided: 当前事件是否已作废
        payload_json: 附加数据（JSON 格式）
        notes: 备注
    """

    __tablename__ = "battle_event"
    __table_args__ = (
        # 复合索引：便于按回合顺序查询事件
        Index(
            "idx_battle_event_battle_turn",
            "battle_id",
            "turn_number",
            "action_order",
            "created_at",
        ),
        # 索引：便于按事件类型查询
        Index("idx_battle_event_type", "battle_id", "event_type"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # action_order 用于同一回合中人工排序。为空时按 created_at 作为兜底顺序。
    action_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)

    # 行动方和目标
    actor_side: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_side: Mapped[str | None] = mapped_column(String, nullable=True)
    target_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # 关联信息
    skill_id: Mapped[str | None] = mapped_column(String, nullable=True)
    skill_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # 来源和可信度
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual_input")
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 纠错字段：保留原事件但将其作废，新事件通过 corrected_event_id 指向被修正事件。
    corrected_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class DamageEvent(TimestampMixin, Base):
    """
    伤害事件详情模型。

    记录伤害事件的详细信息，支持多种伤害类型：
    - 单次伤害：直接记录 damage_value
    - 动画多段：记录 final_total_damage_value
    - 连击：记录 per_hit_damage_value 和 hit_count

    伤害事件是敌方配置推算的主要依据，通过对比理论伤害和实际伤害，
    可以排除不可能的候选配置。

    Attributes:
        event_id: 伤害事件唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        battle_event_id: 关联的通用事件 ID（外键）
        attacker_side: 攻击方阵营
        attacker_elf_id: 攻击方精灵 ID
        defender_side: 防御方阵营
        defender_elf_id: 防御方精灵 ID
        skill_id: 使用的技能 ID
        damage_display_type: 伤害显示类型（single/visual_total/combo）
        damage_value: 伤害值（单次或总伤害）
        final_total_damage_value: 动画多段最终总伤害
        per_hit_damage_value: 连击单段伤害
        hit_count: 连击次数
        computed_total_damage_value: 计算的总伤害（单段×次数）
        combo_count_source: 连击次数来源
        combo_confidence: 连击可信度
        hp_percent_before: 受伤前生命百分比
        hp_percent_after: 受伤后生命百分比
        hp_percent_delta: 生命百分比变化
        enemy_hp_percent_damage: 敌方生命百分比伤害
        type_effectiveness: 属性克制倍率
        formula_context_json: 伤害公式上下文（JSON 格式）
        special_formula_id: 特殊公式 ID
        calculation_confidence: 计算可信度
        recognition_confidence: 识别可信度
        manual_override: 是否被手动覆盖
    """

    __tablename__ = "damage_event"
    __table_args__ = (
        # 唯一索引：每个伤害事件对应一个通用事件
        Index("idx_damage_event_battle_event", "battle_event_id", unique=True),
        # 复合索引：便于查询特定精灵对的伤害记录
        Index("idx_damage_event_battle_pair", "battle_id", "attacker_elf_id", "defender_elf_id"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    battle_event_id: Mapped[str] = mapped_column(
        ForeignKey("battle_event.event_id"),
        nullable=False,
    )

    # 攻击方和防御方
    attacker_side: Mapped[str | None] = mapped_column(String, nullable=True)
    attacker_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    defender_side: Mapped[str | None] = mapped_column(String, nullable=True)
    defender_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    skill_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # 伤害数值
    damage_display_type: Mapped[str] = mapped_column(String, nullable=False)
    damage_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_total_damage_value: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 连击信息
    per_hit_damage_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_total_damage_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    combo_count_source: Mapped[str | None] = mapped_column(String, nullable=True)
    combo_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 生命百分比变化
    hp_percent_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    hp_percent_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    hp_percent_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    enemy_hp_percent_damage: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 计算相关信息
    type_effectiveness: Mapped[float | None] = mapped_column(Float, nullable=True)
    formula_context_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    special_formula_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # 可信度
    calculation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EffectChangeEvent(TimestampMixin, Base):
    """
    状态变化事件详情模型。

    记录状态的变化事件，包括：
    - 施加（apply）
    - 移除（remove）
    - 叠层（stack）
    - 驱散（dispel）
    - 转换（convert）
    - 转移（transfer）
    - 切换清除（switch_clear）

    状态变化事件是理解战斗过程的重要依据。

    Attributes:
        event_id: 状态变化事件唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        battle_event_id: 关联的通用事件 ID（外键）
        turn_number: 发生回合
        change_type: 变化类型（apply/remove/stack/dispel/convert/transfer/switch_clear/switch_keep）
        effect_instance_id: 状态实例 ID
        effect_id: 状态定义 ID
        effect_name: 状态名称（冗余存储）
        category: 状态分类（冗余存储）
        target_side: 目标阵营
        target_elf_id: 目标精灵 ID
        target_skill_slot_id: 目标技能槽 ID
        owner_scope: 归属范围
        layers_before: 变化前层数
        layers_after: 变化后层数
        duration_before: 变化前持续时间
        duration_after: 变化后持续时间
        source_skill_id: 来源技能 ID
        source_elf_id: 来源精灵 ID
        condition_branch: 条件分支
        reason: 变化原因
        source: 事件来源
        recognition_confidence: 识别可信度
        manual_override: 是否被手动覆盖
    """

    __tablename__ = "effect_change_event"
    __table_args__ = (
        # 索引：便于查询通用事件对应的详情
        Index("idx_effect_change_battle_event", "battle_event_id"),
        # 复合索引：便于查询特定目标的状态变化
        Index("idx_effect_change_target", "battle_id", "target_side", "target_elf_id"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    battle_event_id: Mapped[str] = mapped_column(
        ForeignKey("battle_event.event_id"),
        nullable=False,
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # 变化类型和状态信息
    change_type: Mapped[str] = mapped_column(String, nullable=False)
    effect_instance_id: Mapped[str | None] = mapped_column(String, nullable=True)
    effect_id: Mapped[str] = mapped_column(String, nullable=False)
    effect_name: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)

    # 目标信息
    target_side: Mapped[str | None] = mapped_column(String, nullable=True)
    target_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_skill_slot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_scope: Mapped[str] = mapped_column(String, nullable=False)

    # 变化前后数值
    layers_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    layers_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_after: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 来源信息
    source_skill_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    condition_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 来源和可信度
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual_input")
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ResourceChangeEvent(TimestampMixin, Base):
    """
    资源变化事件详情模型。

    记录生命和能量的变化事件，包括：
    - 生命变化（伤害、治疗、回复）
    - 能量变化（消耗、获取）

    资源变化事件用于追踪精灵的生命和能量状态。

    Attributes:
        event_id: 资源变化事件唯一标识（主键）
        battle_id: 所属战斗 ID（外键）
        battle_event_id: 关联的通用事件 ID（外键）
        resource_type: 资源类型（hp/energy）
        change_type: 变化类型（damage/heal/consume/gain）
        source_side: 来源阵营
        source_elf_id: 来源精灵 ID
        target_side: 目标阵营
        target_elf_id: 目标精灵 ID
        value_type: 数值类型（value/percent）
        value: 变化数值
        before_value: 变化前数值
        after_value: 变化后数值
        confidence: 可信度
        manual_override: 是否被手动覆盖
    """

    __tablename__ = "resource_change_event"
    __table_args__ = (Index("idx_resource_change_battle_event", "battle_event_id"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle.battle_id"), nullable=False)
    battle_event_id: Mapped[str] = mapped_column(
        ForeignKey("battle_event.event_id"),
        nullable=False,
    )

    # 资源类型和变化类型
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    change_type: Mapped[str] = mapped_column(String, nullable=False)

    # 来源和目标
    source_side: Mapped[str | None] = mapped_column(String, nullable=True)
    source_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_side: Mapped[str | None] = mapped_column(String, nullable=True)
    target_elf_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # 变化数值
    value_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    before_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 可信度
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
