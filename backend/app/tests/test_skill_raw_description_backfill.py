"""技能原文描述回填测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.data_pipeline.skill_raw_description_backfill import backfill_skill_raw_descriptions
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import SkillDefinition


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建隔离的内存数据库。"""
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


def test_backfill_skill_raw_descriptions_updates_only_raw_description(
    db_session: Session,
) -> None:
    """回填只应更新 raw_description，不污染人工规则 JSON。"""
    db_session.add(
        SkillDefinition(
            skill_id="skill_power_up",
            skill_name="力量增效",
            element_type="normal",
            skill_category="status",
            base_power=None,
            base_energy_cost=0,
            priority_modifier=0,
            damage_rule_json='{"manual_review":{"notes":"开发备注"}}',
        )
    )
    db_session.commit()

    summary = backfill_skill_raw_descriptions(
        db_session,
        [
            {
                "skill_id": "skill_power_up",
                "skill_name": "力量增效",
                "raw_description": "自己获得物攻+100%。",
            }
        ],
    )

    skill = db_session.get(SkillDefinition, "skill_power_up")
    assert summary["skills_updated"] == 1
    assert skill is not None
    assert skill.raw_description == "自己获得物攻+100%。"
    assert skill.damage_rule_json == '{"manual_review":{"notes":"开发备注"}}'


def test_backfill_skill_raw_descriptions_supports_only_missing(
    db_session: Session,
) -> None:
    """only_missing 模式下不覆盖已有原文。"""
    db_session.add(
        SkillDefinition(
            skill_id="skill_existing",
            skill_name="已有原文",
            raw_description="旧原文。",
            element_type="normal",
            skill_category="status",
            base_power=None,
            base_energy_cost=0,
            priority_modifier=0,
        )
    )
    db_session.commit()

    summary = backfill_skill_raw_descriptions(
        db_session,
        [
            {
                "skill_id": "skill_existing",
                "skill_name": "已有原文",
                "raw_description": "新原文。",
            }
        ],
        only_missing=True,
    )

    skill = db_session.get(SkillDefinition, "skill_existing")
    assert summary["skills_updated"] == 0
    assert skill is not None
    assert skill.raw_description == "旧原文。"
