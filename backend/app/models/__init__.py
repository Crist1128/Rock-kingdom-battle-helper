"""
模型包初始化模块。

本模块聚合所有 SQLAlchemy ORM 模型，统一导出供其他模块使用。
通过集中导入，确保 Base.metadata 能收集到所有表的定义。

导入顺序不重要，但建议按功能分组，便于阅读和维护。
"""

# 战斗运行时模型
from app.models.battle import Battle, BattleElfState, BattleSkillSlot

# 候选配置模型
from app.models.candidate import BuildCandidate, CalculationCache

# 状态效果模型
from app.models.effect import BattleEffectInstance, BattleEffectSnapshot

# 战斗事件模型
from app.models.event import BattleEvent, DamageEvent, EffectChangeEvent, ResourceChangeEvent

# 静态规则模型
from app.models.static import (
    EffectDefinition,
    ElfDefinition,
    ElfLearnableSkill,
    NatureDefinition,
    PlayerElfBuild,
    PlayerElfBuildSkill,
    SkillDefinition,
    TypeEffectivenessRule,
)

# __all__ 定义公开接口，明确列出所有导出的模型类
__all__ = [
    # 战斗相关模型
    "Battle",
    "BattleElfState",
    "BattleSkillSlot",

    # 候选配置相关模型
    "BuildCandidate",
    "CalculationCache",

    # 状态效果相关模型
    "BattleEffectInstance",
    "BattleEffectSnapshot",

    # 事件相关模型
    "BattleEvent",
    "DamageEvent",
    "EffectChangeEvent",
    "ResourceChangeEvent",

    # 静态规则相关模型
    "EffectDefinition",
    "ElfDefinition",
    "ElfLearnableSkill",
    "NatureDefinition",
    "PlayerElfBuild",
    "PlayerElfBuildSkill",
    "SkillDefinition",
    "TypeEffectivenessRule",
]
