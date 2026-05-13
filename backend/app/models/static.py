from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ElfDefinition(TimestampMixin, Base):
    """精灵静态定义。精灵不设置 alias_names，代码内部统一使用 elf_id。"""

    __tablename__ = "elf_definition"

    elf_id: Mapped[str] = mapped_column(String, primary_key=True)
    elf_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    avatar: Mapped[str] = mapped_column(String, nullable=False)
    element_types_json: Mapped[str] = mapped_column(Text, nullable=False)

    base_hp_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_physical_attack_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_physical_defense_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_magic_attack_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_magic_defense_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_speed_talent: Mapped[int] = mapped_column(Integer, nullable=False)

    common_skill_sets_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_natures_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_individual_talent_patterns_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    forms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recognition_templates_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    data_source: Mapped[str | None] = mapped_column(String, nullable=True)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)


class ElfLearnableSkill(Base):
    """精灵可学习技能关联表。用于敌方技能未知时枚举。"""

    __tablename__ = "elf_learnable_skill"
    __table_args__ = (
        UniqueConstraint("elf_id", "skill_id", name="uq_elf_learnable_skill_elf_id_skill_id"),
        Index("idx_elf_learnable_skill_elf", "elf_id"),
        Index("idx_elf_learnable_skill_skill", "skill_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definition.skill_id"), nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)


class NatureDefinition(TimestampMixin, Base):
    """性格定义。生命也可以受性格影响。"""

    __tablename__ = "nature_definition"

    nature_id: Mapped[str] = mapped_column(String, primary_key=True)
    nature_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    positive_stat: Mapped[str] = mapped_column(String, nullable=False)
    positive_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.2)
    negative_stat: Mapped[str] = mapped_column(String, nullable=False)
    negative_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=0.9)
    neutral_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)


class SkillDefinition(TimestampMixin, Base):
    """技能静态定义。技能允许 alias_names，用于搜索和 OCR 容错。"""

    __tablename__ = "skill_definition"

    skill_id: Mapped[str] = mapped_column(String, primary_key=True)
    skill_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    alias_names_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_icon: Mapped[str | None] = mapped_column(String, nullable=True)
    element_type: Mapped[str] = mapped_column(String, nullable=False)
    skill_category: Mapped[str] = mapped_column(String, nullable=False)
    base_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_energy_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority_modifier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    damage_rule_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hit_rule_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    effect_operations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recognition_template_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    data_source: Mapped[str | None] = mapped_column(String, nullable=True)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)


class EffectDefinition(TimestampMixin, Base):
    """统一状态定义。印记、天气、异常、普通属性变化全部使用此表。"""

    __tablename__ = "effect_definition"
    __table_args__ = (
        Index("idx_effect_definition_category", "category"),
        Index("idx_effect_definition_owner_scope", "owner_scope"),
    )

    effect_id: Mapped[str] = mapped_column(String, primary_key=True)
    effect_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    icon: Mapped[str | None] = mapped_column(String, nullable=True)

    category: Mapped[str] = mapped_column(String, nullable=False)
    polarity: Mapped[str] = mapped_column(String, nullable=False)
    display_group: Mapped[str] = mapped_column(String, nullable=False)
    display_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    owner_scope: Mapped[str] = mapped_column(String, nullable=False)
    target_scope: Mapped[str] = mapped_column(String, nullable=False)
    attach_target_type: Mapped[str] = mapped_column(String, nullable=False)

    is_visible_icon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_recognizable_by_icon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recognition_alias_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    default_layers: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_layers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stack_rule: Mapped[str] = mapped_column(String, nullable=False, default="replace")
    refresh_rule: Mapped[str | None] = mapped_column(String, nullable=True)

    duration_type: Mapped[str] = mapped_column(String, nullable=False, default="until_removed")
    default_duration_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_duration_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)

    clear_on_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_abnormal_cleanse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_stat_clear: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_mark_clear: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_weather_replace: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_skill_specific: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    can_be_transferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_be_converted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_be_inherited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_be_stolen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_be_doubled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    conflict_group: Mapped[str | None] = mapped_column(String, nullable=True)
    conflict_policy: Mapped[str | None] = mapped_column(String, nullable=True)

    formula_hooks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    stat_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    damage_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    special_rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    developer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)


class TypeEffectivenessRule(TimestampMixin, Base):
    """属性克制规则。"""

    __tablename__ = "type_effectiveness_rule"
    __table_args__ = (
        UniqueConstraint(
            "attack_element_type",
            "defense_element_type",
            name="uq_type_effectiveness_attack_defense",
        ),
        Index("idx_type_effectiveness_attack", "attack_element_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attack_element_type: Mapped[str] = mapped_column(String, nullable=False)
    defense_element_type: Mapped[str] = mapped_column(String, nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)


class PlayerElfBuild(TimestampMixin, Base):
    """玩家己方精灵完整配置。"""

    __tablename__ = "player_elf_build"
    __table_args__ = (Index("idx_player_elf_build_elf", "elf_id"),)

    build_id: Mapped[str] = mapped_column(String, primary_key=True)
    build_name: Mapped[str | None] = mapped_column(String, nullable=True)
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    nature_id: Mapped[str] = mapped_column(ForeignKey("nature_definition.nature_id"), nullable=False)
    individual_talent_distribution_json: Mapped[str] = mapped_column(Text, nullable=False)
    final_stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlayerElfBuildSkill(Base):
    """玩家配置中的技能槽。"""

    __tablename__ = "player_elf_build_skill"
    __table_args__ = (
        UniqueConstraint("build_id", "slot_index", name="uq_player_elf_build_skill_build_slot"),
        Index("idx_player_elf_build_skill_build", "build_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    build_id: Mapped[str] = mapped_column(ForeignKey("player_elf_build.build_id"), nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definition.skill_id"), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
