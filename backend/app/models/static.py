"""
静态规则模型模块。

本模块定义游戏中的静态规则数据模型，这些数据在游戏版本更新时才会变化，
不随单场战斗而改变。包括：精灵定义、性格定义、技能定义、状态定义、
属性克制规则、玩家配置等。
"""

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ElfDefinition(TimestampMixin, Base):
    """
    精灵静态定义模型。

    存储精灵的基础信息、种族资质、可学习技能等静态属性。
    精灵不设置 alias_names，代码内部统一使用 elf_id 进行引用。

    Attributes:
        elf_id: 精灵唯一标识符（主键）
        elf_name: 精灵显示名称
        avatar: 精灵头像图片路径或标识
        element_types_json: 系别类型（JSON 格式，支持双属性）
        base_*_talent: 六维种族资质
        common_skill_sets_json: 常见技能组（JSON 格式）
        common_natures_json: 常见性格（JSON 格式）
        common_individual_talent_patterns_json: 常见个体资质分布（JSON 格式）
        forms_json: 形态信息（JSON 格式）
        recognition_templates_json: 图像识别模板（JSON 格式）
    """

    __tablename__ = "elf_definition"

    # 主键和基础信息
    elf_id: Mapped[str] = mapped_column(String, primary_key=True)
    elf_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    avatar: Mapped[str] = mapped_column(String, nullable=False)
    element_types_json: Mapped[str] = mapped_column(Text, nullable=False)

    # 六维种族资质（基础值，参与面板属性计算）
    base_hp_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_physical_attack_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_physical_defense_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_magic_attack_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_magic_defense_talent: Mapped[int] = mapped_column(Integer, nullable=False)
    base_speed_talent: Mapped[int] = mapped_column(Integer, nullable=False)

    # 常见配置（用于生成候选配置时的权重参考）
    common_skill_sets_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_natures_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_individual_talent_patterns_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    forms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recognition_templates_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 数据来源和版本追踪
    data_source: Mapped[str | None] = mapped_column(String, nullable=True)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)


class ElfLearnableSkill(Base):
    """
    精灵可学习技能关联模型。

    建立精灵与技能的多对多关系，记录每只精灵可以学习的所有技能。
    用于敌方技能未知时的技能枚举。

    Attributes:
        id: 关联记录唯一标识（自增主键）
        elf_id: 精灵标识（外键关联 elf_definition）
        skill_id: 技能标识（外键关联 skill_definition）
        source: 技能来源（如升级、遗传、技能机等）
    """

    __tablename__ = "elf_learnable_skill"
    __table_args__ = (
        # 唯一约束：同一精灵不能重复关联同一技能
        UniqueConstraint("elf_id", "skill_id", name="uq_elf_learnable_skill_elf_id_skill_id"),
        # 索引：便于按精灵查询可学习技能
        Index("idx_elf_learnable_skill_elf", "elf_id"),
        # 索引：便于按技能查询哪些精灵可以学习
        Index("idx_elf_learnable_skill_skill", "skill_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definition.skill_id"), nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)


class NatureDefinition(TimestampMixin, Base):
    """
    性格定义模型。

    存储性格的名称和修正效果。性格会影响六维属性中的两维：
    - 正面修正属性 +20%
    - 负面修正属性 -10%
    - 其他属性不变

    注意：生命属性也可以受性格影响。

    Attributes:
        nature_id: 性格唯一标识（主键）
        nature_name: 性格显示名称
        positive_stat: 正面修正属性键
        positive_multiplier: 正面修正倍率（默认 1.2）
        negative_stat: 负面修正属性键
        negative_multiplier: 负面修正倍率（默认 0.9）
        neutral_multiplier: 中性修正倍率（默认 1.0）
    """

    __tablename__ = "nature_definition"

    nature_id: Mapped[str] = mapped_column(String, primary_key=True)
    nature_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    positive_stat: Mapped[str] = mapped_column(String, nullable=False)
    positive_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.2)
    negative_stat: Mapped[str] = mapped_column(String, nullable=False)
    negative_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=0.9)
    neutral_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)


class SkillDefinition(TimestampMixin, Base):
    """
    技能静态定义模型。

    存储技能的基础信息、伤害规则、效果操作等。
    技能允许设置 alias_names，用于搜索和 OCR 容错。

    Attributes:
        skill_id: 技能唯一标识（主键）
        skill_name: 技能显示名称
        alias_names_json: 别名列表（JSON 格式）
        skill_icon: 技能图标路径
        element_type: 技能系别类型
        skill_category: 技能类别（物理/魔法/状态/特殊）
        base_power: 基础威力
        base_energy_cost: 基础能量消耗
        priority_modifier: 先手优先级修正
        tags_json: 标签列表（JSON 格式）
        damage_rule_json: 伤害规则（JSON 格式）
        hit_rule_json: 连击规则（JSON 格式）
        effect_operations_json: 效果操作（JSON 格式）
        recognition_template_json: 识别模板（JSON 格式）
    """

    __tablename__ = "skill_definition"

    # 主键和基础信息
    skill_id: Mapped[str] = mapped_column(String, primary_key=True)
    skill_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    alias_names_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_icon: Mapped[str | None] = mapped_column(String, nullable=True)

    # 技能属性
    element_type: Mapped[str] = mapped_column(String, nullable=False)
    skill_category: Mapped[str] = mapped_column(String, nullable=False)
    base_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_energy_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority_modifier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 规则和模板（JSON 格式存储复杂结构）
    damage_rule_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hit_rule_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    effect_operations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recognition_template_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 数据来源和版本
    data_source: Mapped[str | None] = mapped_column(String, nullable=True)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)


class EffectDefinition(TimestampMixin, Base):
    """
    统一状态定义模型。

    存储所有状态效果的定义，包括：
    - 普通属性修正（攻击+1、防御-1等）
    - 异常状态（中毒、灼烧、冰冻）
    - 特殊状态（萌化）
    - 印记效果
    - 天气/战场效果
    - 技能槽修正
    - 行动规则修正

    这是统一状态系统的核心，所有状态共享此表的结构。

    Attributes:
        effect_id: 状态唯一标识（主键）
        effect_name: 状态显示名称
        icon: 状态图标路径
        category: 状态分类
        polarity: 极性（正面/负面/中性）
        display_group: 显示分组
        display_priority: 显示优先级
        owner_scope: 归属范围
        target_scope: 目标范围
        attach_target_type: 附加目标类型
        is_visible_icon: 是否在状态栏显示图标
        is_recognizable_by_icon: 是否可通过图标识别
        default_layers: 默认层数
        max_layers: 最大层数
        stack_rule: 叠层规则
        clear_on_switch: 切换精灵时是否清除
        formula_hooks_json: 参与的公式钩子（JSON 格式）
    """

    __tablename__ = "effect_definition"
    __table_args__ = (
        # 索引：便于按分类查询
        Index("idx_effect_definition_category", "category"),
        # 索引：便于按归属范围查询
        Index("idx_effect_definition_owner_scope", "owner_scope"),
    )

    # 主键和基础信息
    effect_id: Mapped[str] = mapped_column(String, primary_key=True)
    effect_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    icon: Mapped[str | None] = mapped_column(String, nullable=True)

    # 分类和显示
    category: Mapped[str] = mapped_column(String, nullable=False)
    polarity: Mapped[str] = mapped_column(String, nullable=False)
    display_group: Mapped[str] = mapped_column(String, nullable=False)
    display_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 归属和目标
    owner_scope: Mapped[str] = mapped_column(String, nullable=False)
    target_scope: Mapped[str] = mapped_column(String, nullable=False)
    attach_target_type: Mapped[str] = mapped_column(String, nullable=False)

    # 识别相关
    is_visible_icon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_recognizable_by_icon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recognition_alias_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 层数规则
    default_layers: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_layers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stack_rule: Mapped[str] = mapped_column(String, nullable=False, default="replace")
    refresh_rule: Mapped[str | None] = mapped_column(String, nullable=True)

    # 持续时间
    duration_type: Mapped[str] = mapped_column(String, nullable=False, default="until_removed")
    default_duration_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_duration_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 清除规则
    clear_on_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_abnormal_cleanse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_stat_clear: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_mark_clear: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_weather_replace: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clear_by_skill_specific: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 特殊行为
    can_be_transferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_be_converted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_be_inherited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_be_stolen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_be_doubled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # 互斥规则
    conflict_group: Mapped[str | None] = mapped_column(String, nullable=True)
    conflict_policy: Mapped[str | None] = mapped_column(String, nullable=True)

    # 公式相关（JSON 格式存储）
    formula_hooks_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    stat_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    damage_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_modifier_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 特殊规则和开发注释
    special_rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    developer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)


class TypeEffectivenessRule(TimestampMixin, Base):
    """
    属性克制规则模型。

    定义攻击属性对防御属性的效果倍率。
    例如：火属性攻击草属性，倍率可能为 2.0（克制）

    Attributes:
        id: 规则唯一标识（自增主键）
        attack_element_type: 攻击方属性类型
        defense_element_type: 防御方属性类型
        multiplier: 伤害倍率
        data_version: 数据版本
    """

    __tablename__ = "type_effectiveness_rule"
    __table_args__ = (
        # 唯一约束：同一攻击属性对同一防御属性的规则唯一
        UniqueConstraint(
            "attack_element_type",
            "defense_element_type",
            name="uq_type_effectiveness_attack_defense",
        ),
        # 索引：便于按攻击属性查询
        Index("idx_type_effectiveness_attack", "attack_element_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attack_element_type: Mapped[str] = mapped_column(String, nullable=False)
    defense_element_type: Mapped[str] = mapped_column(String, nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)


class PlayerElfBuild(TimestampMixin, Base):
    """
    玩家己方精灵完整配置模型。

    存储玩家为自己精灵配置的完整信息，包括：
    - 性格选择
    - 个体资质分布
    - 技能组
    - 面板属性缓存

    战斗开始时，此配置会被复制到 BattleElfState 作为本场初始状态。

    Attributes:
        build_id: 配置唯一标识（主键）
        build_name: 配置名称（可选，用于区分同一精灵的不同配置）
        elf_id: 精灵标识（外键）
        nature_id: 性格标识（外键）
        individual_talent_distribution_json: 个体资质分布（JSON 格式）
        final_stats_json: 最终面板属性缓存（JSON 格式）
        is_default: 是否为默认配置
        notes: 备注
    """

    __tablename__ = "player_elf_build"
    __table_args__ = (Index("idx_player_elf_build_elf", "elf_id"),)

    build_id: Mapped[str] = mapped_column(String, primary_key=True)
    build_name: Mapped[str | None] = mapped_column(String, nullable=True)
    elf_id: Mapped[str] = mapped_column(ForeignKey("elf_definition.elf_id"), nullable=False)
    nature_id: Mapped[str] = mapped_column(
        ForeignKey("nature_definition.nature_id"),
        nullable=False,
    )
    individual_talent_distribution_json: Mapped[str] = mapped_column(Text, nullable=False)
    final_stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlayerElfBuildSkill(Base):
    """
    玩家配置中的技能槽模型。

    记录玩家为特定配置选择的技能及其位置。

    Attributes:
        id: 记录唯一标识（自增主键）
        build_id: 所属配置标识（外键）
        skill_id: 技能标识（外键）
        slot_index: 技能槽位置（0-3）
    """

    __tablename__ = "player_elf_build_skill"
    __table_args__ = (
        # 唯一约束：同一配置的同一位置不能有两个技能
        UniqueConstraint("build_id", "slot_index", name="uq_player_elf_build_skill_build_slot"),
        # 索引：便于查询配置的所有技能
        Index("idx_player_elf_build_skill_build", "build_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    build_id: Mapped[str] = mapped_column(ForeignKey("player_elf_build.build_id"), nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definition.skill_id"), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
