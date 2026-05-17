"""
最小规则数据种子模块。

用于本地开发快速跑通手动输入 MVP。这里放入少量示例精灵、技能、状态，
并自动生成 30 个性格定义。实际项目中应替换为真实规则库导入脚本。
"""

from app.core.enums import EffectCategory, OwnerScope, SkillCategory, StatKey
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models.static import (
    EffectDefinition,
    ElfDefinition,
    ElfLearnableSkill,
    NatureDefinition,
    SkillDefinition,
)
from app.utils.json import dumps_json

STAT_KEYS = [
    StatKey.HP,
    StatKey.PHYSICAL_ATTACK,
    StatKey.PHYSICAL_DEFENSE,
    StatKey.MAGIC_ATTACK,
    StatKey.MAGIC_DEFENSE,
    StatKey.SPEED,
]


NATURE_NAME_MAP = {
    StatKey.HP: "生命",
    StatKey.PHYSICAL_ATTACK: "物攻",
    StatKey.PHYSICAL_DEFENSE: "物防",
    StatKey.MAGIC_ATTACK: "魔攻",
    StatKey.MAGIC_DEFENSE: "魔防",
    StatKey.SPEED: "速度",
}


def seed_natures() -> list[NatureDefinition]:
    """生成 30 个性格定义。"""
    natures: list[NatureDefinition] = []
    for positive in STAT_KEYS:
        for negative in STAT_KEYS:
            if positive == negative:
                continue
            natures.append(
                NatureDefinition(
                    nature_id=f"{positive.value}_plus_{negative.value}_minus",
                    nature_name=f"{NATURE_NAME_MAP[positive]}+{NATURE_NAME_MAP[negative]}-",
                    positive_stat=positive.value,
                    positive_multiplier=1.2,
                    negative_stat=negative.value,
                    negative_multiplier=0.9,
                    neutral_multiplier=1.0,
                )
            )
    return natures


def main() -> None:
    """初始化数据库并插入最小可运行种子数据。"""
    init_db()
    db = SessionLocal()
    try:
        for nature in seed_natures():
            if db.get(NatureDefinition, nature.nature_id) is None:
                db.add(nature)

        demo_elves = [
            ElfDefinition(
                elf_id="elf_demo_fire",
                elf_name="示例火系精灵",
                avatar="assets/elves/demo_fire.png",
                element_types_json=dumps_json(["fire"]),
                base_hp_talent=80,
                base_physical_attack_talent=90,
                base_physical_defense_talent=70,
                base_magic_attack_talent=95,
                base_magic_defense_talent=70,
                base_speed_talent=85,
                data_source="minimal_seed",
                data_version="dev",
            ),
            ElfDefinition(
                elf_id="elf_demo_water",
                elf_name="示例水系精灵",
                avatar="assets/elves/demo_water.png",
                element_types_json=dumps_json(["water"]),
                base_hp_talent=90,
                base_physical_attack_talent=75,
                base_physical_defense_talent=85,
                base_magic_attack_talent=80,
                base_magic_defense_talent=90,
                base_speed_talent=70,
                data_source="minimal_seed",
                data_version="dev",
            ),
        ]
        for elf in demo_elves:
            if db.get(ElfDefinition, elf.elf_id) is None:
                db.add(elf)

        demo_skills = [
            SkillDefinition(
                skill_id="skill_demo_strike",
                skill_name="示例打击",
                element_type="normal",
                skill_category=SkillCategory.PHYSICAL.value,
                base_power=60,
                base_energy_cost=2,
                priority_modifier=0,
                damage_rule_json=dumps_json({"status": "formula_unavailable"}),
                hit_rule_json=dumps_json({"damage_display_type": "single_damage"}),
                data_source="minimal_seed",
                data_version="dev",
            ),
            SkillDefinition(
                skill_id="skill_demo_combo",
                skill_name="示例连击",
                element_type="normal",
                skill_category=SkillCategory.PHYSICAL.value,
                base_power=30,
                base_energy_cost=3,
                priority_modifier=0,
                damage_rule_json=dumps_json({"status": "formula_unavailable"}),
                hit_rule_json=dumps_json({"damage_display_type": "combo_repeated_damage"}),
                data_source="minimal_seed",
                data_version="dev",
            ),
        ]
        for skill in demo_skills:
            if db.get(SkillDefinition, skill.skill_id) is None:
                db.add(skill)

        # 先 flush 主表，确保后续关联表插入可以通过外键校验。
        db.flush()

        links = [
            ("elf_demo_fire", "skill_demo_strike"),
            ("elf_demo_fire", "skill_demo_combo"),
            ("elf_demo_water", "skill_demo_strike"),
            ("elf_demo_water", "skill_demo_combo"),
        ]
        for elf_id, skill_id in links:
            exists = db.query(ElfLearnableSkill).filter_by(elf_id=elf_id, skill_id=skill_id).first()
            if exists is None:
                db.add(ElfLearnableSkill(elf_id=elf_id, skill_id=skill_id, source="minimal_seed"))

        demo_effects = [
            EffectDefinition(
                effect_id="effect_poison",
                effect_name="中毒",
                category=EffectCategory.ABNORMAL.value,
                polarity="negative",
                display_group="elf_status",
                owner_scope=OwnerScope.ELF.value,
                target_scope="single_enemy",
                attach_target_type="elf",
                clear_on_switch=True,
                stack_rule="replace",
                duration_type="until_switch_or_clear",
                data_version="dev",
            ),
            EffectDefinition(
                effect_id="effect_freeze",
                effect_name="冰冻",
                category=EffectCategory.ABNORMAL.value,
                polarity="negative",
                display_group="elf_status",
                owner_scope=OwnerScope.ELF.value,
                target_scope="single_enemy",
                attach_target_type="elf",
                clear_on_switch=False,
                stack_rule="replace",
                duration_type="until_clear",
                data_version="dev",
            ),
            EffectDefinition(
                effect_id="effect_demo_weather",
                effect_name="示例天气",
                category=EffectCategory.WEATHER.value,
                polarity="neutral",
                display_group="field_status",
                owner_scope=OwnerScope.FIELD.value,
                target_scope="field",
                attach_target_type="field",
                clear_on_switch=False,
                clear_by_weather_replace=True,
                stack_rule="replace",
                duration_type="turns",
                default_duration_turns=5,
                conflict_group="weather",
                conflict_policy="replace_old",
                data_version="dev",
            ),
        ]
        for effect in demo_effects:
            if db.get(EffectDefinition, effect.effect_id) is None:
                db.add(effect)

        db.commit()
        print("Database initialized with minimal seed data.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
