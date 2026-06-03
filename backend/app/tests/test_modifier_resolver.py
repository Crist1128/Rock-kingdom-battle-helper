"""ModifierResolver 与 ResponseResolver 的 E 阶段聚焦测试。"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.calculation.formula_context import DamageFormulaContext
from app.calculation.modifier_resolver import ModifierResolver
from app.calculation.response_resolver import ResponseResolver
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import EffectDefinition, SkillDefinition
from app.utils.json import dumps_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建解析器测试用的独立内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    session.add_all(
        [
            SkillDefinition(
                skill_id="defense_skill",
                skill_name="防御测试",
                element_type="normal",
                skill_category="status",
                base_power=None,
                base_energy_cost=1,
                priority_modifier=0,
                damage_rule_json=dumps_json(
                    {
                        "damage_type": "defense_modifier",
                        "damage_reduction": 0.7,
                        "active": True,
                    }
                ),
            ),
            EffectDefinition(
                effect_id="effect_guard",
                effect_name="守护测试",
                category="mark",
                polarity="positive",
                display_group="mark",
                display_priority=100,
                owner_scope="elf",
                target_scope="single_elf",
                attach_target_type="elf",
                damage_modifier_json=dumps_json(
                    {
                        "damage_type": "defense_modifier",
                        "damage_reduction": 0.5,
                        "active": True,
                    }
                ),
            ),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_modifier_resolver_uses_defense_skill_rule_from_payload() -> None:
    """防御技能减伤规则应进入 damage_reductions。"""
    context = DamageFormulaContext(battle_id="battle_1")

    details = ModifierResolver().resolve_formula_modifiers(
        context,
        {
            "defense_skill_rule": {
                "source_id": "defense_skill",
                "damage_type": "defense_modifier",
                "damage_reduction": 0.7,
            }
        },
    )

    assert context.damage_reductions == [Decimal("0.7")]
    assert details["damage_reductions"]["items"][0]["reduction"] == "0.7"


def test_modifier_resolver_loads_defense_skill_rule_from_db(db_session: Session) -> None:
    """传入 defense_skill_id 时，可从 SkillDefinition.damage_rule_json 读取减伤。"""
    context = DamageFormulaContext(battle_id="battle_1")

    ModifierResolver(db_session).resolve_formula_modifiers(
        context,
        {"defense_skill_id": "defense_skill"},
    )

    assert context.damage_reductions == [Decimal("0.7")]


def test_modifier_resolver_uses_snapshot_effect_instances(db_session: Session) -> None:
    """历史快照里的防御方状态可被解析为当前事件的减伤来源。"""
    context = DamageFormulaContext(
        battle_id="battle_1",
        defender_side="enemy",
        defender_elf_id="elf_a",
        snapshot_payload=[
            {
                "instance_id": "instance_guard",
                "effect_id": "effect_guard",
                "owner_scope": "elf",
                "owner_side": "enemy",
                "owner_elf_id": "elf_a",
                "layers": 1,
            }
        ],
    )

    ModifierResolver(db_session).resolve_formula_modifiers(context, {})

    assert context.damage_reductions == [Decimal("0.5")]


def test_response_resolver_marks_unknown_when_success_flag_missing() -> None:
    """应对分支存在但成功与否未知时，只写 unknown，不改变倍率。"""
    context = DamageFormulaContext(battle_id="battle_1")

    details = ResponseResolver().resolve_response_modifiers(
        context,
        {"response_rule": {"target": "attack", "success_multiplier": 3}},
    )

    assert context.response_multiplier == Decimal("1")
    assert "response_success_unknown" in context.unknown_factors
    assert details["response_multiplier"]["source"] == "rule_branch_unknown"
