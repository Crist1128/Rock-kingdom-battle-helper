"""技能规则人工维护 API 测试。"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.db.base import Base
from app.db.session import get_db
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import SkillDefinition
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def api_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """创建隔离的技能规则 API 测试客户端。"""
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
        session.add_all(
            [
                _skill("skill_clear", "清晰规则"),
                _skill("skill_unknown", "模糊技能"),
            ]
        )
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
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_list_skill_rule_reviews_marks_unreviewed(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """审阅队列应能列出尚未人工处理的技能。"""
    client, _session_factory = api_client

    response = client.get("/api/v1/skills/review", params={"review_status": "unreviewed"})

    assert response.status_code == 200
    body = response.json()
    assert {item["skill_id"] for item in body} == {"skill_clear", "skill_unknown"}
    assert {item["review_status"] for item in body} == {"unreviewed"}


def test_update_skill_rules_can_store_structured_rule(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """明确规则可以写入结构化 JSON，并标记为 structured。"""
    client, session_factory = api_client

    response = client.put(
        "/api/v1/skills/skill_clear/rules",
        json={
            "review_status": "structured",
            "review_notes": "确认减伤 70%，应对攻击成功时生效。",
            "damage_rule": {
                "damage_type": "defense_modifier",
                "damage_reduction": 0.7,
                "response_rule": {"condition": "response_attack_success", "target": "attack"},
            },
            "effect_operations": [
                {
                    "op_type": "apply_effect",
                    "effect_id": "effect_test_guard",
                    "target": "self",
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "structured"
    assert body["has_damage_rule"] is True
    assert body["has_effect_operations"] is True
    with session_factory() as session:
        skill = session.get(SkillDefinition, "skill_clear")
        assert skill is not None
        damage_rule = loads_json(skill.damage_rule_json, {})
        operations = loads_json(skill.effect_operations_json, [])
    assert damage_rule["damage_reduction"] == 0.7
    assert damage_rule["manual_review"]["status"] == "structured"
    assert operations[0]["op_type"] == "apply_effect"


def test_update_skill_rules_can_mark_ambiguous_without_executable_rule(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """模糊技能只记录待确认信息，不写入可执行 effect_operations。"""
    client, session_factory = api_client

    response = client.put(
        "/api/v1/skills/skill_unknown/rules",
        json={
            "review_status": "ambiguous",
            "review_notes": "描述里有延伸效果，但触发条件和目标不清楚，暂不实现。",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "ambiguous"
    assert body["has_damage_rule"] is False
    assert body["has_effect_operations"] is False
    with session_factory() as session:
        skill = session.get(SkillDefinition, "skill_unknown")
        assert skill is not None
        damage_rule = loads_json(skill.damage_rule_json, {})
    assert damage_rule == {
        "manual_review": {
            "status": "ambiguous",
            "notes": "描述里有延伸效果，但触发条件和目标不清楚，暂不实现。",
            "source": "manual_skill_rule_editor",
        }
    }
    assert skill.effect_operations_json is None


def test_skill_rule_capability_audit_reports_supported_and_reserved_rules(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """能力审计应区分已有执行链和仍保留的 future hook。"""
    client, session_factory = api_client
    with session_factory() as session:
        skill = session.get(SkillDefinition, "skill_clear")
        assert skill is not None
        skill.effect_operations_json = dumps_json(
            [
                {"op_type": "apply_effect", "effect_id": "effect_test"},
                {"op_type": "force_switch_out"},
            ]
        )
        skill.damage_rule_json = dumps_json(
            {
                "manual_review": {
                    "status": "partial",
                    "future_hooks": [
                        {"hook_type": "charge_turn_mechanic", "status": "reserved"},
                        {"hook_type": "dedication_gain", "status": "reserved"},
                    ],
                }
            }
        )
        session.commit()

    response = client.get("/api/v1/skills/capability-audit")

    assert response.status_code == 200
    body = response.json()
    assert body["total_skills"] == 2
    assert body["executable_operation_counts"]["apply_effect"] == 1
    assert body["unsupported_operation_counts"]["force_switch_out"] == 1
    assert body["supported_future_hook_counts"]["charge_turn_mechanic"] == 1
    assert body["reserved_future_hook_counts"]["dedication_gain"] == 1
    assert any(
        item["key"] == "charge_minimal_state_machine"
        for item in body["implemented_capabilities"]
    )
    assert any(item["key"] == "dedication" for item in body["pending_capabilities"])


def _skill(skill_id: str, name: str) -> SkillDefinition:
    return SkillDefinition(
        skill_id=skill_id,
        skill_name=name,
        element_type="normal",
        skill_category="status",
        base_power=None,
        base_energy_cost=0,
        priority_modifier=0,
    )
