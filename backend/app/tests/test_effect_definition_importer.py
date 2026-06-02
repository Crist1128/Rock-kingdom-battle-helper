"""状态定义导入器测试。"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.data_pipeline.effects.importer import (
    get_effect_definition_status,
    import_effect_definitions,
    read_effect_rows,
    validate_effect_rows,
)
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import EffectDefinition
from app.utils.json import loads_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建状态导入测试用的独立内存数据库。"""
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


def _row(effect_id: str = "effect_test_burn") -> dict:
    return {
        "effect_id": effect_id,
        "effect_name": "测试灼烧",
        "category": "abnormal",
        "polarity": "negative",
        "display_group": "abnormal",
        "display_priority": 1,
        "owner_scope": "elf",
        "target_scope": "single_elf",
        "attach_target_type": "elf",
        "is_visible_icon": True,
        "is_recognizable_by_icon": False,
        "recognition_alias_json": ["灼烧"],
        "default_layers": 1,
        "max_layers": None,
        "stack_rule": "add_layers",
        "refresh_rule": None,
        "duration_type": "until_removed",
        "default_duration_turns": None,
        "default_duration_uses": None,
        "clear_on_switch": True,
        "clear_by_abnormal_cleanse": True,
        "clear_by_stat_clear": False,
        "clear_by_mark_clear": False,
        "clear_by_weather_replace": False,
        "clear_by_skill_specific": True,
        "can_be_transferred": False,
        "can_be_converted": False,
        "can_be_inherited": False,
        "can_be_stolen": False,
        "can_be_doubled": True,
        "conflict_group": None,
        "conflict_policy": None,
        "formula_hooks_json": ["end_turn_status_damage"],
        "stat_modifier_json": None,
        "damage_modifier_json": None,
        "skill_modifier_json": None,
        "action_modifier_json": None,
        "resource_modifier_json": {"percent_per_layer": 0.02},
        "special_rule_id": None,
        "developer_notes": "测试",
        "data_version": "test",
    }


def test_read_effect_rows_requires_json_array(tmp_path: Path) -> None:
    """状态定义 JSON 顶层必须是数组。"""
    path = tmp_path / "effects.json"
    path.write_text(json.dumps({"effect_id": "bad"}), encoding="utf-8")

    with pytest.raises(ValueError, match="顶层必须是数组"):
        read_effect_rows(path)


def test_validate_effect_rows_detects_duplicate_effect_id() -> None:
    """导入前应检查 effect_id 重复。"""
    errors = validate_effect_rows([_row("same"), _row("same")])

    assert any("effect_id 重复" in item for item in errors)


def test_import_effect_definitions_creates_and_serializes_json_fields(
    db_session: Session,
) -> None:
    """导入器应新增状态定义并把对象/数组字段转为 JSON 字符串。"""
    summary = import_effect_definitions(db_session, [_row()])

    assert summary["errors"] == []
    assert summary["effects_created"] == 1
    definition = db_session.get(EffectDefinition, "effect_test_burn")
    assert definition is not None
    assert definition.stack_rule == "add_layers"
    assert loads_json(definition.formula_hooks_json, []) == ["end_turn_status_damage"]
    assert loads_json(definition.resource_modifier_json, {}) == {"percent_per_layer": 0.02}


def test_import_effect_definitions_updates_existing_definition(db_session: Session) -> None:
    """重复导入同一 effect_id 时应更新而不是新增。"""
    row = _row()
    import_effect_definitions(db_session, [row])
    db_session.commit()
    row["effect_name"] = "更新后的灼烧"

    summary = import_effect_definitions(db_session, [row])

    assert summary["effects_updated"] == 1
    definition = db_session.get(EffectDefinition, "effect_test_burn")
    assert definition is not None
    assert definition.effect_name == "更新后的灼烧"


def test_get_effect_definition_status_reports_versions_and_counts(
    db_session: Session,
) -> None:
    """状态导入状态查询应返回当前库中的数量、版本和分类分布。"""
    import_effect_definitions(
        db_session,
        [
            _row("effect_test_burn"),
            {
                **_row("effect_test_starfall"),
                "effect_name": "测试星陨",
                "category": "mark",
                "owner_scope": "side",
                "data_version": "test_v2",
            },
        ],
    )

    status = get_effect_definition_status(db_session)

    assert status["transaction"] == "read_only_status"
    assert status["total_effects"] == 2
    assert {"data_version": "test", "count": 1} in status["data_versions"]
    assert {"data_version": "test_v2", "count": 1} in status["data_versions"]
    assert {"category": "abnormal", "count": 1} in status["categories"]
    assert {"category": "mark", "count": 1} in status["categories"]
    assert {"owner_scope": "elf", "count": 1} in status["owner_scopes"]
    assert {"owner_scope": "side", "count": 1} in status["owner_scopes"]
    assert status["effect_ids"] == ["effect_test_burn", "effect_test_starfall"]
