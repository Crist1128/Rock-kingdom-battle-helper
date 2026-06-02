"""状态定义查询 API 测试。"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.data_pipeline.effects.importer import import_effect_definitions
from app.db.base import Base
from app.db.session import get_db
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.utils.json import loads_json


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    """创建隔离的状态定义 API 测试客户端。"""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(engine)
    with session_factory() as session:
        import_effect_definitions(session, [_starfall_row()])
        session.commit()

    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_list_effects_returns_review_fields(api_client: TestClient) -> None:
    """状态定义列表应返回前端审阅完整规则所需字段。"""
    response = api_client.get("/api/v1/effects", params={"q": "星陨"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    effect = body[0]
    assert effect["effect_id"] == "effect_starfall_mark"
    assert effect["target_scope"] == "side"
    assert effect["attach_target_type"] == "side"
    assert effect["default_layers"] == 1
    assert effect["stack_rule"] == "add_layers"
    assert effect["duration_type"] == "until_removed"
    assert effect["clear_by_mark_clear"] is True
    assert effect["can_be_doubled"] is True
    assert effect["formula_hooks_json"] == '["post_attack_trigger_damage"]'
    resource_modifier = loads_json(effect["resource_modifier_json"], {})
    assert resource_modifier["uses_type_effectiveness"] is True
    assert effect["special_rule_id"] == "starfall_damage"
    assert effect["developer_notes"] == "测试星陨按幻系克制"
    assert effect["data_version"] == "test"


def test_get_effect_returns_same_review_fields(api_client: TestClient) -> None:
    """单个状态定义查询应与列表一样返回完整审阅字段。"""
    response = api_client.get("/api/v1/effects/effect_starfall_mark")

    assert response.status_code == 200
    effect = response.json()
    assert effect["effect_name"] == "星陨印记"
    resource_modifier = loads_json(effect["resource_modifier_json"], {})
    assert resource_modifier["element_type"] == "幻"


def _starfall_row() -> dict:
    """构造最小星陨状态定义。"""
    return {
        "effect_id": "effect_starfall_mark",
        "effect_name": "星陨印记",
        "icon": None,
        "category": "mark",
        "polarity": "negative",
        "display_group": "mark",
        "display_priority": 220,
        "owner_scope": "side",
        "target_scope": "side",
        "attach_target_type": "side",
        "is_visible_icon": True,
        "is_recognizable_by_icon": False,
        "recognition_alias_json": ["星陨", "星陨印记"],
        "default_layers": 1,
        "max_layers": None,
        "stack_rule": "add_layers",
        "refresh_rule": None,
        "duration_type": "until_removed",
        "default_duration_turns": None,
        "default_duration_uses": None,
        "clear_on_switch": False,
        "clear_by_abnormal_cleanse": False,
        "clear_by_stat_clear": False,
        "clear_by_mark_clear": True,
        "clear_by_weather_replace": False,
        "clear_by_skill_specific": True,
        "can_be_transferred": True,
        "can_be_converted": False,
        "can_be_inherited": False,
        "can_be_stolen": True,
        "can_be_doubled": True,
        "conflict_group": None,
        "conflict_policy": None,
        "formula_hooks_json": ["post_attack_trigger_damage"],
        "stat_modifier_json": None,
        "damage_modifier_json": None,
        "skill_modifier_json": None,
        "action_modifier_json": None,
        "resource_modifier_json": {
            "settlement_type": "post_attack",
            "damage_kind": "attack",
            "element_type": "幻",
            "uses_type_effectiveness": True,
            "affected_by_reduction": True,
        },
        "special_rule_id": "starfall_damage",
        "developer_notes": "测试星陨按幻系克制",
        "data_version": "test",
    }
