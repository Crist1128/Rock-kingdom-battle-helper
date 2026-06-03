"""rocom 导入器技能规则合并测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.data_pipeline.rocom.cleaner import CleanedDataset
from app.data_pipeline.rocom.importer import import_dataset
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import SkillDefinition
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
