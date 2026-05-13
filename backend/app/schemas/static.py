from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class ElfDefinitionOut(ORMBase):
    elf_id: str
    elf_name: str
    avatar: str
    element_types_json: str
    base_hp_talent: int
    base_physical_attack_talent: int
    base_physical_defense_talent: int
    base_magic_attack_talent: int
    base_magic_defense_talent: int
    base_speed_talent: int
    data_version: str | None = None


class NatureDefinitionOut(ORMBase):
    nature_id: str
    nature_name: str
    positive_stat: str
    positive_multiplier: float
    negative_stat: str
    negative_multiplier: float
    neutral_multiplier: float


class SkillDefinitionOut(ORMBase):
    skill_id: str
    skill_name: str
    element_type: str
    skill_category: str
    base_power: int | None = None
    base_energy_cost: int
    priority_modifier: int
    damage_rule_json: str | None = None
    hit_rule_json: str | None = None
    effect_operations_json: str | None = None


class EffectDefinitionOut(ORMBase):
    effect_id: str
    effect_name: str
    category: str
    polarity: str
    display_group: str
    owner_scope: str
    clear_on_switch: bool
    formula_hooks_json: str | None = None


class StatBlock(BaseModel):
    hp: int = Field(..., description="生命")
    physical_attack: int
    physical_defense: int
    magic_attack: int
    magic_defense: int
    speed: int
