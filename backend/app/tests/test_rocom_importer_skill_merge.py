"""rocom 导入器技能规则合并测试。"""

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.data_pipeline.rocom.avatar_repair import repair_missing_elf_avatars
from app.data_pipeline.rocom.cleaner import CleanedDataset
from app.data_pipeline.rocom.importer import import_dataset
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import ElfDefinition, ElfLearnableSkill, SkillDefinition
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建导入器测试用的独立内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_rocom_import_preserves_structured_operations_when_cleaned_is_unparsed(
    db_session: Session,
) -> None:
    """cleaned 基线重新导入时，不应覆盖 DB 里已有的结构化技能操作。"""
    db_session.add(
        SkillDefinition(
            skill_id="skill_starfall",
            skill_name="星陨测试",
            element_type="normal",
            skill_category="status",
            base_power=None,
            base_energy_cost=1,
            priority_modifier=0,
            effect_operations_json=dumps_json(
                [
                    {
                        "op_type": "apply_effect",
                        "effect_id": "effect_starfall_mark",
                        "target": "enemy_side",
                        "layers": 4,
                    }
                ]
            ),
        )
    )
    db_session.commit()

    dataset = CleanedDataset(
        skills=[
            {
                "skill_id": "skill_starfall",
                "skill_name": "星陨测试",
                "alias_names_json": None,
                "skill_icon": None,
                "element_type": "normal",
                "skill_category": "status",
                "base_power": None,
                "base_energy_cost": 1,
                "priority_modifier": 0,
                "tags_json": dumps_json(["status"]),
                "damage_rule_json": None,
                "hit_rule_json": dumps_json({"damage_display_type": "single_damage"}),
                "effect_operations_json": dumps_json(
                    [{"status": "unparsed", "raw_description": "敌方获得4层星陨印记。"}]
                ),
                "recognition_template_json": None,
                "data_source": "biligame_rocom_bwiki",
                "data_version": "test",
            }
        ]
    )

    summary = import_dataset(db_session, dataset)

    skill = db_session.get(SkillDefinition, "skill_starfall")
    assert summary["skills_updated"] == 1
    assert skill is not None
    assert loads_json(skill.effect_operations_json, [])[0]["op_type"] == "apply_effect"
    assert skill.data_version == "test"


def test_rocom_import_accepts_structured_operations_from_cleaned(db_session: Session) -> None:
    """当 cleaned 本身提供结构化操作时，应正常更新 DB。"""
    db_session.add(
        SkillDefinition(
            skill_id="skill_status",
            skill_name="状态测试",
            element_type="normal",
            skill_category="status",
            base_power=None,
            base_energy_cost=1,
            priority_modifier=0,
            effect_operations_json=dumps_json(
                [{"status": "unparsed", "raw_description": "旧描述"}]
            ),
        )
    )
    db_session.commit()

    dataset = CleanedDataset(
        skills=[
            {
                "skill_id": "skill_status",
                "skill_name": "状态测试",
                "alias_names_json": None,
                "skill_icon": None,
                "element_type": "normal",
                "skill_category": "status",
                "base_power": None,
                "base_energy_cost": 1,
                "priority_modifier": 0,
                "tags_json": dumps_json(["status"]),
                "damage_rule_json": None,
                "hit_rule_json": dumps_json({"damage_display_type": "single_damage"}),
                "effect_operations_json": dumps_json(
                    [{"op_type": "apply_effect", "effect_id": "effect_test"}]
                ),
                "recognition_template_json": None,
                "data_source": "biligame_rocom_bwiki",
                "data_version": "test",
            }
        ]
    )

    import_dataset(db_session, dataset)

    skill = db_session.get(SkillDefinition, "skill_status")
    assert skill is not None
    assert loads_json(skill.effect_operations_json, [])[0]["op_type"] == "apply_effect"


def test_rocom_import_preserves_structured_operations_when_cleaned_has_no_operations(
    db_session: Session,
) -> None:
    """攻击技能的 cleaned 基线没有操作字段时，也不能清掉 DB 里的人工规则。"""
    db_session.add(
        SkillDefinition(
            skill_id="skill_attack_starfall",
            skill_name="攻击星陨测试",
            element_type="normal",
            skill_category="physical",
            base_power=80,
            base_energy_cost=3,
            priority_modifier=0,
            effect_operations_json=dumps_json(
                [{"op_type": "dynamic_apply_effect", "effect_id": "effect_starfall_mark"}]
            ),
        )
    )
    db_session.commit()

    dataset = CleanedDataset(
        skills=[
            {
                "skill_id": "skill_attack_starfall",
                "skill_name": "攻击星陨测试",
                "alias_names_json": None,
                "skill_icon": None,
                "element_type": "normal",
                "skill_category": "physical",
                "base_power": 80,
                "base_energy_cost": 3,
                "priority_modifier": 0,
                "tags_json": dumps_json(["physical"]),
                "damage_rule_json": dumps_json({"damage_type": "normal_formula"}),
                "hit_rule_json": dumps_json({"damage_display_type": "single_damage"}),
                "effect_operations_json": None,
                "recognition_template_json": None,
                "data_source": "biligame_rocom_bwiki",
                "data_version": "test",
            }
        ]
    )

    import_dataset(db_session, dataset)

    skill = db_session.get(SkillDefinition, "skill_attack_starfall")
    assert skill is not None
    assert loads_json(skill.effect_operations_json, [])[0]["op_type"] == "dynamic_apply_effect"


def test_rocom_import_refresh_static_rebuilds_links_and_soft_deletes_stale_skill(
    db_session: Session,
) -> None:
    """全量刷新应重建 BWIKI 技能关系，并软删除新数据集中消失的 rocom 技能。"""
    db_session.add_all(
        [
            SkillDefinition(
                skill_id="skill_stale",
                skill_name="旧技能",
                element_type="normal",
                skill_category="physical",
                base_power=50,
                base_energy_cost=1,
                priority_modifier=0,
                data_source="biligame_rocom_bwiki",
                data_version="old",
            ),
            ElfDefinition(
                elf_id="elf_keep",
                elf_name="保留精灵",
                avatar="",
                element_types_json=dumps_json(["normal"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
                data_source="biligame_rocom_bwiki",
                data_version="old",
            ),
        ]
    )
    db_session.commit()
    db_session.add(
        ElfLearnableSkill(
            elf_id="elf_keep",
            skill_id="skill_stale",
            source="biligame_rocom_bwiki:LV1",
        )
    )
    db_session.commit()

    dataset = CleanedDataset(
        elves=[
            {
                "elf_id": "elf_keep",
                "elf_name": "保留精灵",
                "avatar": "",
                "element_types_json": dumps_json(["normal"]),
                "base_hp_talent": 100,
                "base_physical_attack_talent": 100,
                "base_physical_defense_talent": 100,
                "base_magic_attack_talent": 100,
                "base_magic_defense_talent": 100,
                "base_speed_talent": 100,
                "common_skill_sets_json": None,
                "common_natures_json": None,
                "common_individual_talent_patterns_json": None,
                "forms_json": None,
                "recognition_templates_json": None,
                "data_source": "biligame_rocom_bwiki",
                "data_version": "new",
            }
        ],
        skills=[
            {
                "skill_id": "skill_new",
                "skill_name": "新技能",
                "alias_names_json": None,
                "skill_icon": None,
                "element_type": "normal",
                "skill_category": "physical",
                "base_power": 80,
                "base_energy_cost": 2,
                "priority_modifier": 0,
                "tags_json": dumps_json(["physical"]),
                "damage_rule_json": dumps_json({"damage_type": "normal_formula"}),
                "hit_rule_json": dumps_json({"damage_display_type": "single_damage"}),
                "effect_operations_json": None,
                "recognition_template_json": None,
                "data_source": "biligame_rocom_bwiki",
                "data_version": "new",
            }
        ],
        elf_skills=[
            {
                "elf_id": "elf_keep",
                "skill_id": "skill_new",
                "source": "biligame_rocom_bwiki",
                "learn_level": 1,
            }
        ],
    )

    summary = import_dataset(db_session, dataset, refresh_static=True)

    stale_skill = db_session.get(SkillDefinition, "skill_stale")
    links = db_session.query(ElfLearnableSkill).all()
    assert summary["elf_skill_links_deleted_before_refresh"] == 1
    assert summary["stale_skills_soft_deleted"] == 1
    assert stale_skill is not None
    assert stale_skill.deleted_at is not None
    assert len(links) == 1
    assert links[0].skill_id == "skill_new"


def test_rocom_import_preserves_existing_incomplete_elf_and_links(
    db_session: Session,
) -> None:
    """全量刷新遇到缺六维精灵时，应保留旧主表和旧 BWIKI 技能关系。"""
    db_session.add_all(
        [
            SkillDefinition(
                skill_id="skill_old",
                skill_name="旧技能",
                element_type="normal",
                skill_category="physical",
                base_power=50,
                base_energy_cost=1,
                priority_modifier=0,
                data_source="biligame_rocom_bwiki",
                data_version="old",
            ),
            SkillDefinition(
                skill_id="skill_new",
                skill_name="新技能",
                element_type="normal",
                skill_category="physical",
                base_power=80,
                base_energy_cost=2,
                priority_modifier=0,
                data_source="biligame_rocom_bwiki",
                data_version="new",
            ),
            ElfDefinition(
                elf_id="elf_incomplete",
                elf_name="旧精灵",
                avatar="old_avatar",
                element_types_json=dumps_json(["normal"]),
                base_hp_talent=100,
                base_physical_attack_talent=90,
                base_physical_defense_talent=80,
                base_magic_attack_talent=70,
                base_magic_defense_talent=60,
                base_speed_talent=50,
                data_source="biligame_rocom_bwiki",
                data_version="old",
            ),
        ]
    )
    db_session.commit()
    db_session.add(
        ElfLearnableSkill(
            elf_id="elf_incomplete",
            skill_id="skill_old",
            source="biligame_rocom_bwiki:LV1",
        )
    )
    db_session.commit()

    dataset = CleanedDataset(
        elves=[
            {
                "elf_id": "elf_incomplete",
                "elf_name": "空详情精灵",
                "avatar": "",
                "element_types_json": dumps_json([]),
                "base_hp_talent": 0,
                "base_physical_attack_talent": 0,
                "base_physical_defense_talent": 0,
                "base_magic_attack_talent": 0,
                "base_magic_defense_talent": 0,
                "base_speed_talent": 0,
                "common_skill_sets_json": None,
                "common_natures_json": None,
                "common_individual_talent_patterns_json": None,
                "forms_json": None,
                "recognition_templates_json": None,
                "data_source": "biligame_rocom_bwiki",
                "data_version": "new",
            }
        ],
        skills=[],
        elf_skills=[
            {
                "elf_id": "elf_incomplete",
                "skill_id": "skill_new",
                "source": "biligame_rocom_bwiki",
                "learn_level": 1,
            }
        ],
    )

    summary = import_dataset(db_session, dataset, refresh_static=True)

    elf = db_session.get(ElfDefinition, "elf_incomplete")
    links = db_session.query(ElfLearnableSkill).all()
    assert summary["elves_skipped_incomplete"] == 1
    assert summary["incomplete_elf_links_preserved"] == 1
    assert summary["elf_skill_links_skipped_incomplete_elf"] == 1
    assert elf is not None
    assert elf.elf_name == "旧精灵"
    assert elf.base_hp_talent == 100
    assert links[0].skill_id == "skill_old"


def test_rocom_import_preserves_existing_avatar_when_cleaned_avatar_is_empty(
    db_session: Session,
) -> None:
    """cleaned 未带头像 URL 时，不应覆盖 DB 里已有的非空头像。"""
    db_session.add(
        ElfDefinition(
            elf_id="elf_avatar",
            elf_name="头像测试",
            avatar="https://example.test/avatar.png",
            element_types_json=dumps_json(["normal"]),
            base_hp_talent=100,
            base_physical_attack_talent=100,
            base_physical_defense_talent=100,
            base_magic_attack_talent=100,
            base_magic_defense_talent=100,
            base_speed_talent=100,
            data_source="biligame_rocom_bwiki",
            data_version="old",
        )
    )
    db_session.commit()

    dataset = CleanedDataset(
        elves=[
            {
                "elf_id": "elf_avatar",
                "elf_name": "头像测试",
                "avatar": "",
                "element_types_json": dumps_json(["normal"]),
                "base_hp_talent": 110,
                "base_physical_attack_talent": 100,
                "base_physical_defense_talent": 100,
                "base_magic_attack_talent": 100,
                "base_magic_defense_talent": 100,
                "base_speed_talent": 100,
                "common_skill_sets_json": None,
                "common_natures_json": None,
                "common_individual_talent_patterns_json": None,
                "forms_json": None,
                "recognition_templates_json": None,
                "data_source": "biligame_rocom_bwiki",
                "data_version": "new",
            }
        ]
    )

    summary = import_dataset(db_session, dataset)

    elf = db_session.get(ElfDefinition, "elf_avatar")
    assert summary["elves_updated"] == 1
    assert elf is not None
    assert elf.avatar == "https://example.test/avatar.png"
    assert elf.base_hp_talent == 110
    assert elf.data_version == "new"


def test_repair_missing_elf_avatars_updates_only_empty_avatar(
    db_session: Session,
    tmp_path,
) -> None:
    """头像修复工具只补空头像，不覆盖已有头像。"""
    fallback_dir = tmp_path / "cleaned"
    fallback_dir.mkdir()
    (fallback_dir / "elves.json").write_text(
        json.dumps(
            [
                {
                    "elf_id": "elf_empty_avatar",
                    "elf_name": "空头像",
                    "avatar": "https://example.test/empty.png",
                },
                {
                    "elf_id": "elf_keep_avatar",
                    "elf_name": "保留头像",
                    "avatar": "https://example.test/new.png",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    db_session.add_all(
        [
            ElfDefinition(
                elf_id="elf_empty_avatar",
                elf_name="空头像",
                avatar="",
                element_types_json=dumps_json(["normal"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            ElfDefinition(
                elf_id="elf_keep_avatar",
                elf_name="保留头像",
                avatar="https://example.test/old.png",
                element_types_json=dumps_json(["normal"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
        ]
    )
    db_session.commit()

    summary = repair_missing_elf_avatars(db_session, fallback_cleaned_dir=fallback_dir)

    empty = db_session.get(ElfDefinition, "elf_empty_avatar")
    keep = db_session.get(ElfDefinition, "elf_keep_avatar")
    assert summary["updated_avatars"] == 1
    assert empty is not None
    assert empty.avatar == "https://example.test/empty.png"
    assert keep is not None
    assert keep.avatar == "https://example.test/old.png"
