"""阶段 B 状态实例挂载校验测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import BattlePhase
from app.data_pipeline.effects.importer import import_effect_definitions
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle
from app.schemas.effect import EffectApplyInput
from app.services.effect_service import BattleEffectService


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建状态服务测试用的独立内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    session.add(Battle(battle_id="battle_1", phase=BattlePhase.BATTLE.value, turn_number=2))
    import_effect_definitions(
        session,
        [
            _effect_row("effect_starfall_mark", "星陨印记", "mark", "side"),
            _effect_row("weather_rain", "雨天", "weather", "field"),
            _effect_row("effect_burn", "灼烧", "abnormal", "elf"),
        ],
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_apply_effect_normalizes_side_mark_target(db_session: Session) -> None:
    """星陨等 side 印记即使前端误传 elf，也应按定义挂到队伍侧。"""
    instance = BattleEffectService(db_session).apply_effect(
        EffectApplyInput(
            battle_id="battle_1",
            effect_id="effect_starfall_mark",
            owner_scope="elf",
            owner_side="enemy",
            owner_elf_id="enemy_active",
            layers=4,
        )
    )

    assert instance.owner_scope == "side"
    assert instance.owner_side == "enemy"
    assert instance.owner_elf_id is None
    assert instance.field_id is None
    assert instance.layers == 4


def test_apply_effect_normalizes_field_weather_target(db_session: Session) -> None:
    """天气应强制挂到 field，并默认 field_id=main。"""
    instance = BattleEffectService(db_session).apply_effect(
        EffectApplyInput(
            battle_id="battle_1",
            effect_id="weather_rain",
            owner_scope="side",
            owner_side="self",
            layers=1,
        )
    )

    assert instance.owner_scope == "field"
    assert instance.owner_side is None
    assert instance.owner_elf_id is None
    assert instance.field_id == "main"


def test_apply_effect_requires_elf_target_for_elf_effect(db_session: Session) -> None:
    """精灵状态缺少 owner_elf_id 时应拒绝，不能挂成半残状态。"""
    with pytest.raises(ValueError, match="owner_scope=elf"):
        BattleEffectService(db_session).apply_effect(
            EffectApplyInput(
                battle_id="battle_1",
                effect_id="effect_burn",
                owner_scope="side",
                owner_side="enemy",
                layers=1,
            )
        )


def _effect_row(effect_id: str, effect_name: str, category: str, owner_scope: str) -> dict:
    """构造最小状态定义。"""
    return {
        "effect_id": effect_id,
        "effect_name": effect_name,
        "icon": None,
        "category": category,
        "polarity": "negative" if category != "weather" else "neutral",
        "display_group": category,
        "display_priority": 1,
        "owner_scope": owner_scope,
        "target_scope": owner_scope,
        "attach_target_type": owner_scope,
        "is_visible_icon": True,
        "is_recognizable_by_icon": False,
        "recognition_alias_json": [effect_name],
        "default_layers": 1,
        "max_layers": 10,
        "stack_rule": "add_layers" if owner_scope != "field" else "replace",
        "refresh_rule": None,
        "duration_type": "until_removed",
        "default_duration_turns": None,
        "default_duration_uses": None,
        "clear_on_switch": owner_scope == "elf",
        "clear_by_abnormal_cleanse": category == "abnormal",
        "clear_by_stat_clear": False,
        "clear_by_mark_clear": category == "mark",
        "clear_by_weather_replace": category == "weather",
        "clear_by_skill_specific": True,
        "can_be_transferred": False,
        "can_be_converted": False,
        "can_be_inherited": False,
        "can_be_stolen": False,
        "can_be_doubled": category == "mark",
        "conflict_group": "weather" if category == "weather" else None,
        "conflict_policy": "replace" if category == "weather" else None,
        "formula_hooks_json": None,
        "stat_modifier_json": None,
        "damage_modifier_json": None,
        "skill_modifier_json": None,
        "action_modifier_json": None,
        "resource_modifier_json": None,
        "special_rule_id": None,
        "developer_notes": "test",
        "data_version": "test",
    }
