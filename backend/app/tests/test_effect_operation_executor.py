"""阶段 D 技能效果操作执行器测试。"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.core.enums import BattleEventType, BattlePhase
from app.data_pipeline.skill_operations.importer import import_skill_effect_operations
from app.db.base import Base
from app.db.session import get_db
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.effect import BattleEffectInstance, BattleEffectSnapshot
from app.models.event import EffectChangeEvent, ResourceChangeEvent
from app.models.static import EffectDefinition, ElfDefinition, SkillDefinition
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def api_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """创建隔离的执行器测试客户端。"""
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


def test_skill_use_applies_starfall_mark_to_enemy_side(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """skill_use 会执行 effect_operations_json 并把星陨挂到敌方 side。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(session, skill_id="skill_projection", layers=4)
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/events",
        json={
            "turn_number": 1,
            "event_type": BattleEventType.SKILL_USE.value,
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "target_side": "enemy",
            "target_elf_id": "elf_enemy",
            "skill_id": "skill_projection",
            "skill_confirmed": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    payload = loads_json(body["payload_json"], {})
    results = payload["effect_operation_results"]
    assert results[0]["status"] == "executed"
    assert results[0]["owner_scope"] == "side"
    assert results[0]["owner_side"] == "enemy"
    assert results[0]["layers_after"] == 4
    assert body["snapshot_id"]

    with session_factory() as session:
        instance = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == "battle_ops",
                BattleEffectInstance.effect_id == "effect_starfall_mark",
            )
        )
        assert instance is not None
        assert instance.owner_scope == "side"
        assert instance.owner_side == "enemy"
        assert instance.owner_elf_id is None
        assert instance.layers == 4

        change = session.scalar(
            select(EffectChangeEvent).where(
                EffectChangeEvent.battle_id == "battle_ops",
                EffectChangeEvent.effect_id == "effect_starfall_mark",
            )
        )
        assert change is not None
        assert change.battle_event_id == body["event_id"]
        assert change.source == "system_calculated"

        snapshot = session.get(BattleEffectSnapshot, body["snapshot_id"])
        assert snapshot is not None
        snapshot_items = loads_json(snapshot.full_snapshot_json, [])
        assert snapshot_items[0]["effect_id"] == "effect_starfall_mark"


def test_dedicated_skill_event_endpoint_executes_operations(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """专用 skill-events 接口会生成 skill_use 并传递条件旗标。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(
            session,
            skill_id="skill_projection",
            layers=4,
            condition="response_defense_success",
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/skill-events",
        json={
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "target_side": "enemy",
            "target_elf_id": "elf_enemy",
            "skill_id": "skill_projection",
            "condition_flags": {"response_defense_success": True},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["turn_number"] == 1
    assert body["event_type"] == BattleEventType.SKILL_USE.value
    payload = loads_json(body["payload_json"], {})
    assert payload["condition_flags"] == {"response_defense_success": True}
    assert payload["effect_operation_results"][0]["status"] == "executed"
    assert body["snapshot_id"]

    with session_factory() as session:
        instance = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == "battle_ops",
                BattleEffectInstance.effect_id == "effect_starfall_mark",
            )
        )
        assert instance is not None
        assert instance.owner_side == "enemy"
        assert instance.layers == 4


def test_skill_use_adds_layers_to_existing_starfall_mark(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """重复施加星陨时按 add_layers 累加层数。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(session, skill_id="skill_projection", layers=4)
        session.flush()
        session.add(
            BattleEffectInstance(
                instance_id="existing_starfall",
                battle_id="battle_ops",
                effect_id="effect_starfall_mark",
                category="mark",
                owner_scope="side",
                owner_side="enemy",
                layers=2,
                is_active=True,
                applied_turn=1,
                manual_override=True,
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/events",
        json={
            "turn_number": 1,
            "event_type": BattleEventType.SKILL_USE.value,
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "target_side": "enemy",
            "target_elf_id": "elf_enemy",
            "skill_id": "skill_projection",
            "skill_confirmed": True,
        },
    )

    assert response.status_code == 201
    payload = loads_json(response.json()["payload_json"], {})
    assert payload["effect_operation_results"][0]["layers_before"] == 2
    assert payload["effect_operation_results"][0]["layers_after"] == 6

    with session_factory() as session:
        instance = session.get(BattleEffectInstance, "existing_starfall")
        assert instance is not None
        assert instance.layers == 6
        change = session.scalar(
            select(EffectChangeEvent).where(EffectChangeEvent.battle_id == "battle_ops")
        )
        assert change is not None
        assert change.change_type == "stack"


def test_conditional_operation_is_skipped_when_condition_unknown(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """应对分支未确认时只返回 unknown，不写入状态。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(
            session,
            skill_id="skill_meditation",
            layers=2,
            condition="response_attack_success",
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/events",
        json={
            "turn_number": 1,
            "event_type": BattleEventType.SKILL_USE.value,
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "target_side": "enemy",
            "target_elf_id": "elf_enemy",
            "skill_id": "skill_meditation",
            "skill_confirmed": True,
        },
    )

    assert response.status_code == 201
    payload = loads_json(response.json()["payload_json"], {})
    assert payload["effect_operation_results"][0]["status"] == "unknown"
    assert payload["effect_operation_results"][0]["reason"] == "unknown"
    with session_factory() as session:
        instance_count = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == "battle_ops",
                BattleEffectInstance.effect_id == "effect_starfall_mark",
            )
        )
        assert instance_count is None


def test_multiply_layers_executes_only_when_condition_is_true(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """二律背反这类应对成功翻倍分支可由 payload 显式触发。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(session, skill_id="skill_double", layers=1)
        skill = session.get(SkillDefinition, "skill_double")
        assert skill is not None
        skill.effect_operations_json = dumps_json(
            [
                {
                    "op_type": "multiply_layers",
                    "effect_id": "effect_starfall_mark",
                    "target": "enemy_side",
                    "multiplier": 2,
                    "condition": "response_defense_success",
                }
            ]
        )
        session.flush()
        session.add(
            BattleEffectInstance(
                instance_id="existing_starfall",
                battle_id="battle_ops",
                effect_id="effect_starfall_mark",
                category="mark",
                owner_scope="side",
                owner_side="enemy",
                layers=3,
                is_active=True,
                applied_turn=1,
                manual_override=True,
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/events",
        json={
            "turn_number": 1,
            "event_type": BattleEventType.SKILL_USE.value,
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "target_side": "enemy",
            "target_elf_id": "elf_enemy",
            "skill_id": "skill_double",
            "skill_confirmed": True,
            "payload_json": dumps_json(
                {"condition_flags": {"response_defense_success": True}}
            ),
        },
    )

    assert response.status_code == 201
    payload = loads_json(response.json()["payload_json"], {})
    assert payload["effect_operation_results"][0]["operation"] == "multiply_layers"
    assert payload["effect_operation_results"][0]["layers_before"] == 3
    assert payload["effect_operation_results"][0]["layers_after"] == 6
    with session_factory() as session:
        instance = session.get(BattleEffectInstance, "existing_starfall")
        assert instance is not None
        assert instance.layers == 6


def test_dynamic_apply_effect_uses_existing_layers(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """动态层数可读取目标已有状态层数，缺失时不会假造。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(session, skill_id="skill_dynamic", layers=1)
        skill = session.get(SkillDefinition, "skill_dynamic")
        assert skill is not None
        skill.effect_operations_json = dumps_json(
            [
                {
                    "op_type": "dynamic_apply_effect",
                    "effect_id": "effect_starfall_mark",
                    "target": "enemy_side",
                    "layers_from": "existing_effect_layers",
                }
            ]
        )
        session.flush()
        session.add(
            BattleEffectInstance(
                instance_id="existing_starfall",
                battle_id="battle_ops",
                effect_id="effect_starfall_mark",
                category="mark",
                owner_scope="side",
                owner_side="enemy",
                layers=2,
                is_active=True,
                applied_turn=1,
                manual_override=True,
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/events",
        json={
            "turn_number": 1,
            "event_type": BattleEventType.SKILL_USE.value,
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "target_side": "enemy",
            "target_elf_id": "elf_enemy",
            "skill_id": "skill_dynamic",
            "skill_confirmed": True,
        },
    )

    assert response.status_code == 201
    payload = loads_json(response.json()["payload_json"], {})
    assert payload["effect_operation_results"][0]["layers_before"] == 2
    assert payload["effect_operation_results"][0]["layers_after"] == 4


def test_change_weather_replaces_existing_weather(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """change_weather 会清掉旧天气并施加新天气。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(session, skill_id="skill_weather", layers=1)
        session.add(_weather_definition("weather_rain", "雨天"))
        session.add(_weather_definition("weather_blizzard", "暴风雪"))
        skill = session.get(SkillDefinition, "skill_weather")
        assert skill is not None
        skill.effect_operations_json = dumps_json(
            [
                {
                    "op_type": "change_weather",
                    "effect_id": "weather_blizzard",
                    "target": "field",
                    "layers": 1,
                }
            ]
        )
        session.flush()
        session.add(
            BattleEffectInstance(
                instance_id="existing_rain",
                battle_id="battle_ops",
                effect_id="weather_rain",
                category="weather",
                owner_scope="field",
                field_id="main",
                layers=1,
                is_active=True,
                applied_turn=1,
                manual_override=True,
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/events",
        json={
            "turn_number": 1,
            "event_type": BattleEventType.SKILL_USE.value,
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "skill_id": "skill_weather",
            "skill_confirmed": True,
        },
    )

    assert response.status_code == 201
    payload = loads_json(response.json()["payload_json"], {})
    assert payload["effect_operation_results"][0]["operation"] == "change_weather"
    assert payload["effect_operation_results"][0]["removed_effects"][0]["effect_id"] == (
        "weather_rain"
    )
    with session_factory() as session:
        rain = session.get(BattleEffectInstance, "existing_rain")
        assert rain is not None
        assert rain.is_active is False
        blizzard = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == "battle_ops",
                BattleEffectInstance.effect_id == "weather_blizzard",
            )
        )
        assert blizzard is not None
        assert blizzard.is_active is True


def test_resource_change_and_remove_effect_share_skill_event(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """资源变化和移除状态都挂在同一个 skill_use 主事件下。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(session, skill_id="skill_cleanup", layers=1)
        skill = session.get(SkillDefinition, "skill_cleanup")
        assert skill is not None
        skill.effect_operations_json = dumps_json(
            [
                {
                    "op_type": "resource_change",
                    "target": "enemy_side",
                    "resource_type": "hp",
                    "change_type": "damage",
                    "value_type": "value",
                    "value": 50,
                },
                {
                    "op_type": "remove_effect",
                    "effect_id": "effect_starfall_mark",
                    "target": "enemy_side",
                },
            ]
        )
        session.flush()
        session.add(
            BattleEffectInstance(
                instance_id="existing_starfall",
                battle_id="battle_ops",
                effect_id="effect_starfall_mark",
                category="mark",
                owner_scope="side",
                owner_side="enemy",
                layers=2,
                is_active=True,
                applied_turn=1,
                manual_override=True,
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/events",
        json={
            "turn_number": 1,
            "event_type": BattleEventType.SKILL_USE.value,
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "target_side": "enemy",
            "target_elf_id": "elf_enemy",
            "skill_id": "skill_cleanup",
            "skill_confirmed": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    payload = loads_json(body["payload_json"], {})
    assert [item["operation"] for item in payload["effect_operation_results"]] == [
        "resource_change",
        "remove_effect",
    ]
    with session_factory() as session:
        enemy = session.get(BattleElfState, "state_enemy")
        assert enemy is not None
        assert enemy.current_hp_value == 450
        resource_event = session.scalar(
            select(ResourceChangeEvent).where(ResourceChangeEvent.battle_id == "battle_ops")
        )
        assert resource_event is not None
        assert resource_event.battle_event_id == body["event_id"]
        instance = session.get(BattleEffectInstance, "existing_starfall")
        assert instance is not None
        assert instance.is_active is False


def test_conditional_branch_executes_child_operations(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """conditional_branch 满足条件时会执行子操作。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_battle_with_starfall_skill(session, skill_id="skill_branch", layers=1)
        skill = session.get(SkillDefinition, "skill_branch")
        assert skill is not None
        skill.effect_operations_json = dumps_json(
            [
                {
                    "op_type": "conditional_branch",
                    "condition": "response_attack_success",
                    "operations": [
                        {
                            "op_type": "apply_effect",
                            "effect_id": "effect_starfall_mark",
                            "target": "enemy_side",
                            "layers": 2,
                        }
                    ],
                }
            ]
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_ops/events",
        json={
            "turn_number": 1,
            "event_type": BattleEventType.SKILL_USE.value,
            "actor_side": "self",
            "actor_elf_id": "elf_self",
            "target_side": "enemy",
            "target_elf_id": "elf_enemy",
            "skill_id": "skill_branch",
            "skill_confirmed": True,
            "payload_json": dumps_json({"response_attack_success": True}),
        },
    )

    assert response.status_code == 201
    payload = loads_json(response.json()["payload_json"], {})
    branch_result = payload["effect_operation_results"][0]
    assert branch_result["operation"] == "conditional_branch"
    assert branch_result["child_results"][0]["status"] == "executed"
    with session_factory() as session:
        instance = session.scalar(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == "battle_ops",
                BattleEffectInstance.effect_id == "effect_starfall_mark",
            )
        )
        assert instance is not None
        assert instance.layers == 2


def test_skill_operation_importer_updates_by_skill_name_and_can_rollback(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """技能操作导入器按 skill_name 更新，调用方 rollback 时不会落库。"""
    _client, session_factory = api_client
    rows = [
        {
            "skill_name": "超维投射",
            "operations": [
                {
                    "op_type": "apply_effect",
                    "effect_id": "effect_starfall_mark",
                    "target": "enemy_side",
                    "layers": 4,
                }
            ],
        },
        {
            "skill_name": "星轨裂变",
            "operations": [
                {
                    "op_type": "apply_effect",
                    "effect_id": "effect_starfall_mark",
                    "target": "enemy_side",
                    "layers": 2,
                }
            ],
        },
    ]
    with session_factory() as session:
        session.add(_skill("skill_projection", "超维投射"))
        session.add(_skill("skill_split", "星轨裂变"))
        session.commit()

    with session_factory() as session:
        summary = import_skill_effect_operations(session, rows)
        assert summary["updated"] == 2
        assert session.get(SkillDefinition, "skill_projection").effect_operations_json is not None
        session.rollback()

    with session_factory() as session:
        assert session.get(SkillDefinition, "skill_projection").effect_operations_json is None
        summary = import_skill_effect_operations(session, rows)
        session.commit()
        assert summary["updated"] == 2

    with session_factory() as session:
        operations = loads_json(
            session.get(SkillDefinition, "skill_split").effect_operations_json,
            [],
        )
        assert operations[0]["layers"] == 2


def _seed_battle_with_starfall_skill(
    session: Session,
    *,
    skill_id: str,
    layers: int,
    condition: str = "always",
) -> None:
    """构造一场带星陨技能操作的测试战斗。"""
    session.add(
        Battle(
            battle_id="battle_ops",
            phase=BattlePhase.BATTLE.value,
            turn_number=1,
            self_active_elf_id="elf_self",
            enemy_active_elf_id="elf_enemy",
        )
    )
    session.add_all(
        [
            _elf("elf_self", "己方测试精灵", ["火"]),
            _elf("elf_enemy", "敌方测试精灵", ["草"]),
        ]
    )
    session.flush()
    session.add(
        BattleElfState(
            state_id="state_self",
            battle_id="battle_ops",
            side="self",
            elf_id="elf_self",
            elf_name="己方测试精灵",
            avatar="",
            panel_stats_json=dumps_json({"hp": 500}),
            current_hp_value=500,
            current_hp_percent=100.0,
            energy=0,
            is_active_elf=True,
            is_defeated=False,
            manual_override=True,
        )
    )
    session.add(
        BattleElfState(
            state_id="state_enemy",
            battle_id="battle_ops",
            side="enemy",
            elf_id="elf_enemy",
            elf_name="敌方测试精灵",
            avatar="",
            panel_stats_json=dumps_json({"hp": 500}),
            current_hp_value=500,
            current_hp_percent=100.0,
            energy=0,
            is_active_elf=True,
            is_defeated=False,
            manual_override=True,
        )
    )
    session.add(_starfall_definition())
    session.add(
        _skill(
            skill_id,
            "星陨测试技能",
            operations=[
                {
                    "op_type": "apply_effect",
                    "effect_id": "effect_starfall_mark",
                    "target": "enemy_side",
                    "layers": layers,
                    "condition": condition,
                    "timing": "on_skill_use",
                }
            ],
        )
    )
    session.flush()


def _elf(elf_id: str, elf_name: str, element_types: list[str]) -> ElfDefinition:
    """构造精灵定义。"""
    return ElfDefinition(
        elf_id=elf_id,
        elf_name=elf_name,
        avatar="",
        element_types_json=dumps_json(element_types),
        base_hp_talent=100,
        base_physical_attack_talent=100,
        base_physical_defense_talent=100,
        base_magic_attack_talent=100,
        base_magic_defense_talent=100,
        base_speed_talent=100,
    )


def _skill(
    skill_id: str,
    skill_name: str,
    operations: list[dict] | None = None,
) -> SkillDefinition:
    """构造技能定义。"""
    return SkillDefinition(
        skill_id=skill_id,
        skill_name=skill_name,
        element_type="幻",
        skill_category="status",
        base_power=None,
        base_energy_cost=0,
        priority_modifier=0,
        effect_operations_json=dumps_json(operations) if operations is not None else None,
    )


def _starfall_definition() -> EffectDefinition:
    """构造星陨印记定义。"""
    return EffectDefinition(
        effect_id="effect_starfall_mark",
        effect_name="星陨印记",
        category="mark",
        polarity="negative",
        display_group="mark",
        display_priority=220,
        owner_scope="side",
        target_scope="side",
        attach_target_type="side",
        is_visible_icon=True,
        is_recognizable_by_icon=False,
        default_layers=1,
        max_layers=None,
        stack_rule="add_layers",
        duration_type="until_removed",
        clear_on_switch=False,
        formula_hooks_json=dumps_json(["post_attack_trigger_damage"]),
        resource_modifier_json=dumps_json(
            {
                "settlement_type": "post_attack",
                "damage_kind": "attack",
                "element_type": "幻",
                "uses_type_effectiveness": True,
            }
        ),
        special_rule_id="starfall_damage",
    )


def _weather_definition(effect_id: str, effect_name: str) -> EffectDefinition:
    """构造天气定义。"""
    return EffectDefinition(
        effect_id=effect_id,
        effect_name=effect_name,
        category="weather",
        polarity="neutral",
        display_group="weather",
        display_priority=300,
        owner_scope="field",
        target_scope="field",
        attach_target_type="field",
        is_visible_icon=True,
        is_recognizable_by_icon=False,
        default_layers=1,
        max_layers=1,
        stack_rule="replace",
        duration_type="turns",
        default_duration_turns=7,
        clear_on_switch=False,
        clear_by_weather_replace=True,
        conflict_group="weather",
        conflict_policy="replace_old",
    )
