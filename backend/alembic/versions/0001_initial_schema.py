"""
初始数据库模式迁移脚本。

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-05-12

本迁移脚本创建系统的初始数据库表结构，包括：
- 静态规则表：精灵、性格、技能、状态定义、属性克制规则
- 玩家配置表：己方精灵配置
- 战斗运行时表：战斗主表、精灵状态、技能槽
- 候选配置表：敌方候选配置、计算缓存
- 状态效果表：状态实例、状态快照
- 事件日志表：通用事件、伤害事件、状态变化事件、资源变化事件
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# 迁移标识
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def timestamp_columns() -> list[sa.Column]:
    """
    返回标准的时间戳列定义。

    Returns:
        list[sa.Column]: 包含 created_at、updated_at、deleted_at 的列定义列表
    """
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    """
    执行数据库升级。

    创建所有初始表结构和索引。
    """
    # ==================== 静态规则表 ====================

    # 精灵定义表
    op.create_table(
        "elf_definition",
        sa.Column("elf_id", sa.String(), primary_key=True),
        sa.Column("elf_name", sa.String(), nullable=False),
        sa.Column("avatar", sa.String(), nullable=False),
        sa.Column("element_types_json", sa.Text(), nullable=False),
        sa.Column("base_hp_talent", sa.Integer(), nullable=False),
        sa.Column("base_physical_attack_talent", sa.Integer(), nullable=False),
        sa.Column("base_physical_defense_talent", sa.Integer(), nullable=False),
        sa.Column("base_magic_attack_talent", sa.Integer(), nullable=False),
        sa.Column("base_magic_defense_talent", sa.Integer(), nullable=False),
        sa.Column("base_speed_talent", sa.Integer(), nullable=False),
        sa.Column("common_skill_sets_json", sa.Text(), nullable=True),
        sa.Column("common_natures_json", sa.Text(), nullable=True),
        sa.Column("common_individual_talent_patterns_json", sa.Text(), nullable=True),
        sa.Column("forms_json", sa.Text(), nullable=True),
        sa.Column("recognition_templates_json", sa.Text(), nullable=True),
        sa.Column("data_source", sa.String(), nullable=True),
        sa.Column("data_version", sa.String(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_elf_definition_name", "elf_definition", ["elf_name"])

    # 性格定义表
    op.create_table(
        "nature_definition",
        sa.Column("nature_id", sa.String(), primary_key=True),
        sa.Column("nature_name", sa.String(), nullable=False),
        sa.Column("positive_stat", sa.String(), nullable=False),
        sa.Column("positive_multiplier", sa.Float(), nullable=False),
        sa.Column("negative_stat", sa.String(), nullable=False),
        sa.Column("negative_multiplier", sa.Float(), nullable=False),
        sa.Column("neutral_multiplier", sa.Float(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("idx_nature_definition_name", "nature_definition", ["nature_name"])

    # 技能定义表
    op.create_table(
        "skill_definition",
        sa.Column("skill_id", sa.String(), primary_key=True),
        sa.Column("skill_name", sa.String(), nullable=False),
        sa.Column("alias_names_json", sa.Text(), nullable=True),
        sa.Column("skill_icon", sa.String(), nullable=True),
        sa.Column("element_type", sa.String(), nullable=False),
        sa.Column("skill_category", sa.String(), nullable=False),
        sa.Column("base_power", sa.Integer(), nullable=True),
        sa.Column("base_energy_cost", sa.Integer(), nullable=False),
        sa.Column("priority_modifier", sa.Integer(), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("damage_rule_json", sa.Text(), nullable=True),
        sa.Column("hit_rule_json", sa.Text(), nullable=True),
        sa.Column("effect_operations_json", sa.Text(), nullable=True),
        sa.Column("recognition_template_json", sa.Text(), nullable=True),
        sa.Column("data_source", sa.String(), nullable=True),
        sa.Column("data_version", sa.String(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_skill_definition_name", "skill_definition", ["skill_name"])

    # 状态效果定义表
    op.create_table(
        "effect_definition",
        sa.Column("effect_id", sa.String(), primary_key=True),
        sa.Column("effect_name", sa.String(), nullable=False),
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("polarity", sa.String(), nullable=False),
        sa.Column("display_group", sa.String(), nullable=False),
        sa.Column("display_priority", sa.Integer(), nullable=False),
        sa.Column("owner_scope", sa.String(), nullable=False),
        sa.Column("target_scope", sa.String(), nullable=False),
        sa.Column("attach_target_type", sa.String(), nullable=False),
        sa.Column("is_visible_icon", sa.Boolean(), nullable=False),
        sa.Column("is_recognizable_by_icon", sa.Boolean(), nullable=False),
        sa.Column("recognition_alias_json", sa.Text(), nullable=True),
        sa.Column("default_layers", sa.Integer(), nullable=False),
        sa.Column("max_layers", sa.Integer(), nullable=True),
        sa.Column("stack_rule", sa.String(), nullable=False),
        sa.Column("refresh_rule", sa.String(), nullable=True),
        sa.Column("duration_type", sa.String(), nullable=False),
        sa.Column("default_duration_turns", sa.Integer(), nullable=True),
        sa.Column("default_duration_uses", sa.Integer(), nullable=True),
        sa.Column("clear_on_switch", sa.Boolean(), nullable=False),
        sa.Column("clear_by_abnormal_cleanse", sa.Boolean(), nullable=False),
        sa.Column("clear_by_stat_clear", sa.Boolean(), nullable=False),
        sa.Column("clear_by_mark_clear", sa.Boolean(), nullable=False),
        sa.Column("clear_by_weather_replace", sa.Boolean(), nullable=False),
        sa.Column("clear_by_skill_specific", sa.Boolean(), nullable=False),
        sa.Column("can_be_transferred", sa.Boolean(), nullable=False),
        sa.Column("can_be_converted", sa.Boolean(), nullable=False),
        sa.Column("can_be_inherited", sa.Boolean(), nullable=False),
        sa.Column("can_be_stolen", sa.Boolean(), nullable=False),
        sa.Column("can_be_doubled", sa.Boolean(), nullable=False),
        sa.Column("conflict_group", sa.String(), nullable=True),
        sa.Column("conflict_policy", sa.String(), nullable=True),
        sa.Column("formula_hooks_json", sa.Text(), nullable=True),
        sa.Column("stat_modifier_json", sa.Text(), nullable=True),
        sa.Column("damage_modifier_json", sa.Text(), nullable=True),
        sa.Column("skill_modifier_json", sa.Text(), nullable=True),
        sa.Column("action_modifier_json", sa.Text(), nullable=True),
        sa.Column("resource_modifier_json", sa.Text(), nullable=True),
        sa.Column("special_rule_id", sa.String(), nullable=True),
        sa.Column("developer_notes", sa.Text(), nullable=True),
        sa.Column("data_version", sa.String(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_effect_definition_name", "effect_definition", ["effect_name"])
    op.create_index("idx_effect_definition_category", "effect_definition", ["category"])
    op.create_index("idx_effect_definition_owner_scope", "effect_definition", ["owner_scope"])

    # ==================== 关联表 ====================

    # 精灵可学习技能关联表
    op.create_table(
        "elf_learnable_skill",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("elf_id", sa.String(), sa.ForeignKey("elf_definition.elf_id"), nullable=False),
        sa.Column("skill_id", sa.String(), sa.ForeignKey("skill_definition.skill_id"), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.UniqueConstraint("elf_id", "skill_id", name="uq_elf_learnable_skill_elf_id_skill_id"),
    )
    op.create_index("idx_elf_learnable_skill_elf", "elf_learnable_skill", ["elf_id"])
    op.create_index("idx_elf_learnable_skill_skill", "elf_learnable_skill", ["skill_id"])

    # 属性克制规则表
    op.create_table(
        "type_effectiveness_rule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("attack_element_type", sa.String(), nullable=False),
        sa.Column("defense_element_type", sa.String(), nullable=False),
        sa.Column("multiplier", sa.Float(), nullable=False),
        sa.Column("data_version", sa.String(), nullable=True),
        *timestamp_columns(),
        sa.UniqueConstraint("attack_element_type", "defense_element_type", name="uq_type_effectiveness_attack_defense"),
    )
    op.create_index("idx_type_effectiveness_attack", "type_effectiveness_rule", ["attack_element_type"])

    # ==================== 玩家配置表 ====================

    # 玩家精灵配置表
    op.create_table(
        "player_elf_build",
        sa.Column("build_id", sa.String(), primary_key=True),
        sa.Column("build_name", sa.String(), nullable=True),
        sa.Column("elf_id", sa.String(), sa.ForeignKey("elf_definition.elf_id"), nullable=False),
        sa.Column("nature_id", sa.String(), sa.ForeignKey("nature_definition.nature_id"), nullable=False),
        sa.Column("individual_talent_distribution_json", sa.Text(), nullable=False),
        sa.Column("final_stats_json", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_player_elf_build_elf", "player_elf_build", ["elf_id"])

    # 玩家配置技能槽表
    op.create_table(
        "player_elf_build_skill",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("build_id", sa.String(), sa.ForeignKey("player_elf_build.build_id"), nullable=False),
        sa.Column("skill_id", sa.String(), sa.ForeignKey("skill_definition.skill_id"), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.UniqueConstraint("build_id", "slot_index", name="uq_player_elf_build_skill_build_slot"),
    )
    op.create_index("idx_player_elf_build_skill_build", "player_elf_build_skill", ["build_id"])

    # ==================== 战斗运行时表 ====================

    # 战斗主表
    op.create_table(
        "battle",
        sa.Column("battle_id", sa.String(), primary_key=True),
        sa.Column("battle_name", sa.String(), nullable=True),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("self_active_elf_id", sa.String(), nullable=True),
        sa.Column("enemy_active_elf_id", sa.String(), nullable=True),
        sa.Column("current_snapshot_id", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_battle_phase", "battle", ["phase"])

    # 战斗精灵状态表
    op.create_table(
        "battle_elf_state",
        sa.Column("state_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("elf_id", sa.String(), sa.ForeignKey("elf_definition.elf_id"), nullable=False),
        sa.Column("elf_name", sa.String(), nullable=False),
        sa.Column("avatar", sa.String(), nullable=False),
        sa.Column("panel_stats_json", sa.Text(), nullable=False),
        sa.Column("current_hp_value", sa.Integer(), nullable=True),
        sa.Column("current_hp_percent", sa.Float(), nullable=True),
        sa.Column("energy", sa.Integer(), nullable=True),
        sa.Column("skill_ids_json", sa.Text(), nullable=True),
        sa.Column("confirmed_skill_ids_json", sa.Text(), nullable=True),
        sa.Column("active_effect_instance_ids_json", sa.Text(), nullable=True),
        sa.Column("is_active_elf", sa.Boolean(), nullable=False),
        sa.Column("is_defeated", sa.Boolean(), nullable=False),
        sa.Column("last_switch_turn", sa.Integer(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("idx_battle_elf_state_battle_side_elf", "battle_elf_state", ["battle_id", "side", "elf_id"])
    op.create_index("idx_battle_elf_state_active", "battle_elf_state", ["battle_id", "side", "is_active_elf"])

    # 战斗技能槽表
    op.create_table(
        "battle_skill_slot",
        sa.Column("slot_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("elf_id", sa.String(), sa.ForeignKey("elf_definition.elf_id"), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.String(), sa.ForeignKey("skill_definition.skill_id"), nullable=False),
        sa.Column("current_energy_cost", sa.Integer(), nullable=True),
        sa.Column("current_power", sa.Integer(), nullable=True),
        sa.Column("cooldown_remaining", sa.Integer(), nullable=True),
        sa.Column("active_effect_instance_ids_json", sa.Text(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("idx_battle_skill_slot_battle_elf", "battle_skill_slot", ["battle_id", "side", "elf_id"])
    op.create_index("idx_battle_skill_slot_skill", "battle_skill_slot", ["skill_id"])

    # ==================== 候选配置表 ====================

    # 敌方候选配置表
    op.create_table(
        "build_candidate",
        sa.Column("candidate_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("elf_id", sa.String(), sa.ForeignKey("elf_definition.elf_id"), nullable=False),
        sa.Column("nature_id", sa.String(), sa.ForeignKey("nature_definition.nature_id"), nullable=False),
        sa.Column("individual_talent_distribution_json", sa.Text(), nullable=False),
        sa.Column("final_hp", sa.Integer(), nullable=False),
        sa.Column("final_physical_attack", sa.Integer(), nullable=False),
        sa.Column("final_physical_defense", sa.Integer(), nullable=False),
        sa.Column("final_magic_attack", sa.Integer(), nullable=False),
        sa.Column("final_magic_defense", sa.Integer(), nullable=False),
        sa.Column("final_speed", sa.Integer(), nullable=False),
        sa.Column("possible_skill_ids_json", sa.Text(), nullable=True),
        sa.Column("confirmed_skill_ids_json", sa.Text(), nullable=True),
        sa.Column("skill_weights_json", sa.Text(), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_excluded", sa.Boolean(), nullable=False),
        sa.Column("excluded_reason", sa.Text(), nullable=True),
        sa.Column("evidence_ids_json", sa.Text(), nullable=True),
        sa.Column("matched_event_ids_json", sa.Text(), nullable=True),
        sa.Column("mismatched_event_ids_json", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_build_candidate_battle_elf_excluded", "build_candidate", ["battle_id", "elf_id", "is_excluded"])
    op.create_index("idx_build_candidate_confidence", "build_candidate", ["battle_id", "elf_id", "confidence"])

    # ==================== 状态效果表 ====================

    # 战斗状态实例表
    op.create_table(
        "battle_effect_instance",
        sa.Column("instance_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("effect_id", sa.String(), sa.ForeignKey("effect_definition.effect_id"), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("owner_scope", sa.String(), nullable=False),
        sa.Column("owner_side", sa.String(), nullable=True),
        sa.Column("owner_elf_id", sa.String(), nullable=True),
        sa.Column("owner_skill_slot_id", sa.String(), nullable=True),
        sa.Column("field_id", sa.String(), nullable=True),
        sa.Column("source_side", sa.String(), nullable=True),
        sa.Column("source_elf_id", sa.String(), nullable=True),
        sa.Column("source_skill_id", sa.String(), nullable=True),
        sa.Column("source_event_id", sa.String(), nullable=True),
        sa.Column("layers", sa.Integer(), nullable=False),
        sa.Column("remaining_turns", sa.Integer(), nullable=True),
        sa.Column("remaining_uses", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("applied_turn", sa.Integer(), nullable=True),
        sa.Column("expire_turn", sa.Integer(), nullable=True),
        sa.Column("last_updated_turn", sa.Integer(), nullable=True),
        sa.Column("recognition_source", sa.String(), nullable=True),
        sa.Column("recognition_confidence", sa.Float(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_effect_instance_battle_owner", "battle_effect_instance", ["battle_id", "owner_side", "owner_elf_id"])
    op.create_index("idx_effect_instance_battle_category", "battle_effect_instance", ["battle_id", "category"])
    op.create_index("idx_effect_instance_active", "battle_effect_instance", ["battle_id", "is_active"])

    # 状态快照表
    op.create_table(
        "battle_effect_snapshot",
        sa.Column("snapshot_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("active_effect_instance_ids_json", sa.Text(), nullable=False),
        sa.Column("self_active_elf_id", sa.String(), nullable=True),
        sa.Column("enemy_active_elf_id", sa.String(), nullable=True),
        sa.Column("self_elf_effect_ids_json", sa.Text(), nullable=True),
        sa.Column("enemy_elf_effect_ids_json", sa.Text(), nullable=True),
        sa.Column("self_side_effect_ids_json", sa.Text(), nullable=True),
        sa.Column("enemy_side_effect_ids_json", sa.Text(), nullable=True),
        sa.Column("field_effect_ids_json", sa.Text(), nullable=True),
        sa.Column("skill_slot_effect_ids_json", sa.Text(), nullable=True),
        sa.Column("turn_effect_ids_json", sa.Text(), nullable=True),
        sa.Column("full_snapshot_json", sa.Text(), nullable=True),
        sa.Column("source_event_id", sa.String(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_effect_snapshot_battle_turn", "battle_effect_snapshot", ["battle_id", "turn_number", "created_at"])
    op.create_index("idx_effect_snapshot_source_event", "battle_effect_snapshot", ["source_event_id"])

    # ==================== 事件日志表 ====================

    # 通用战斗事件表
    op.create_table(
        "battle_event",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_side", sa.String(), nullable=True),
        sa.Column("actor_elf_id", sa.String(), nullable=True),
        sa.Column("target_side", sa.String(), nullable=True),
        sa.Column("target_elf_id", sa.String(), nullable=True),
        sa.Column("skill_id", sa.String(), nullable=True),
        sa.Column("skill_confirmed", sa.Boolean(), nullable=False),
        sa.Column("snapshot_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("recognition_confidence", sa.Float(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_battle_event_battle_turn", "battle_event", ["battle_id", "turn_number", "created_at"])
    op.create_index("idx_battle_event_type", "battle_event", ["battle_id", "event_type"])

    # 伤害事件详情表
    op.create_table(
        "damage_event",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("battle_event_id", sa.String(), sa.ForeignKey("battle_event.event_id"), nullable=False),
        sa.Column("attacker_side", sa.String(), nullable=True),
        sa.Column("attacker_elf_id", sa.String(), nullable=True),
        sa.Column("defender_side", sa.String(), nullable=True),
        sa.Column("defender_elf_id", sa.String(), nullable=True),
        sa.Column("skill_id", sa.String(), nullable=True),
        sa.Column("damage_display_type", sa.String(), nullable=False),
        sa.Column("damage_value", sa.Integer(), nullable=True),
        sa.Column("final_total_damage_value", sa.Integer(), nullable=True),
        sa.Column("per_hit_damage_value", sa.Integer(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=True),
        sa.Column("computed_total_damage_value", sa.Integer(), nullable=True),
        sa.Column("combo_count_source", sa.String(), nullable=True),
        sa.Column("combo_confidence", sa.Float(), nullable=True),
        sa.Column("hp_percent_before", sa.Float(), nullable=True),
        sa.Column("hp_percent_after", sa.Float(), nullable=True),
        sa.Column("hp_percent_delta", sa.Float(), nullable=True),
        sa.Column("enemy_hp_percent_damage", sa.Float(), nullable=True),
        sa.Column("type_effectiveness", sa.Float(), nullable=True),
        sa.Column("formula_context_json", sa.Text(), nullable=True),
        sa.Column("special_formula_id", sa.String(), nullable=True),
        sa.Column("calculation_confidence", sa.Float(), nullable=True),
        sa.Column("recognition_confidence", sa.Float(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("idx_damage_event_battle_event", "damage_event", ["battle_event_id"], unique=True)
    op.create_index("idx_damage_event_battle_pair", "damage_event", ["battle_id", "attacker_elf_id", "defender_elf_id"])

    # 状态变化事件详情表
    op.create_table(
        "effect_change_event",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("battle_event_id", sa.String(), sa.ForeignKey("battle_event.event_id"), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(), nullable=False),
        sa.Column("effect_instance_id", sa.String(), nullable=True),
        sa.Column("effect_id", sa.String(), nullable=False),
        sa.Column("effect_name", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("target_side", sa.String(), nullable=True),
        sa.Column("target_elf_id", sa.String(), nullable=True),
        sa.Column("target_skill_slot_id", sa.String(), nullable=True),
        sa.Column("owner_scope", sa.String(), nullable=False),
        sa.Column("layers_before", sa.Integer(), nullable=True),
        sa.Column("layers_after", sa.Integer(), nullable=True),
        sa.Column("duration_before", sa.Integer(), nullable=True),
        sa.Column("duration_after", sa.Integer(), nullable=True),
        sa.Column("source_skill_id", sa.String(), nullable=True),
        sa.Column("source_elf_id", sa.String(), nullable=True),
        sa.Column("condition_branch", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("recognition_confidence", sa.Float(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("idx_effect_change_battle_event", "effect_change_event", ["battle_event_id"])
    op.create_index("idx_effect_change_target", "effect_change_event", ["battle_id", "target_side", "target_elf_id"])

    # 资源变化事件详情表
    op.create_table(
        "resource_change_event",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("battle_id", sa.String(), sa.ForeignKey("battle.battle_id"), nullable=False),
        sa.Column("battle_event_id", sa.String(), sa.ForeignKey("battle_event.event_id"), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("change_type", sa.String(), nullable=False),
        sa.Column("source_side", sa.String(), nullable=True),
        sa.Column("source_elf_id", sa.String(), nullable=True),
        sa.Column("target_side", sa.String(), nullable=True),
        sa.Column("target_elf_id", sa.String(), nullable=True),
        sa.Column("value_type", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("before_value", sa.Float(), nullable=True),
        sa.Column("after_value", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("manual_override", sa.Boolean(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("idx_resource_change_battle_event", "resource_change_event", ["battle_event_id"])

    # ==================== 计算缓存表 ====================

    # 计算缓存表
    op.create_table(
        "calculation_cache",
        sa.Column("cache_id", sa.String(), primary_key=True),
        sa.Column("cache_key", sa.String(), nullable=False),
        sa.Column("cache_type", sa.String(), nullable=False),
        sa.Column("battle_id", sa.String(), nullable=True),
        sa.Column("snapshot_id", sa.String(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("expire_at", sa.String(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index("idx_calculation_cache_key", "calculation_cache", ["cache_key"], unique=True)


def downgrade() -> None:
    """
    执行数据库降级。

    删除所有创建的表，按依赖关系的逆序删除。
    """
    # 按依赖关系的逆序删除表
    for table in [
        "calculation_cache",
        "resource_change_event",
        "effect_change_event",
        "damage_event",
        "battle_event",
        "battle_effect_snapshot",
        "battle_effect_instance",
        "build_candidate",
        "battle_skill_slot",
        "battle_elf_state",
        "battle",
        "player_elf_build_skill",
        "player_elf_build",
        "type_effectiveness_rule",
        "elf_learnable_skill",
        "effect_definition",
        "skill_definition",
        "nature_definition",
        "elf_definition",
    ]:
        op.drop_table(table)
