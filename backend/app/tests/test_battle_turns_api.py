"""最小回合推进 API 测试。"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.core.enums import BattleEventType, BattlePhase
from app.db.base import Base
from app.db.session import get_db
from app.models import battle as _battle_models  # noqa: F401
from app.models import candidate as _candidate_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import estimate as _estimate_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle
from app.models.candidate import BuildCandidate
from app.models.effect import BattleEffectInstance, BattleEffectSnapshot
from app.models.estimate import EnemyPanelEstimate
from app.models.event import BattleEvent, DamageEvent, EffectChangeEvent, ResourceChangeEvent
from app.models.static import EffectDefinition, ElfDefinition, NatureDefinition, SkillDefinition
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def api_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """创建隔离的回合 API 测试客户端。"""
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
                Battle(
                    battle_id="battle_1",
                    phase=BattlePhase.BATTLE.value,
                    turn_number=3,
                ),
                Battle(
                    battle_id="preparation_battle",
                    phase=BattlePhase.PREPARATION.value,
                    turn_number=0,
                ),
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


def test_end_turn_creates_event_snapshot_and_advances_turn(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """结束回合应写入 turn_end 事件、创建快照并推进回合号。"""
    client, session_factory = api_client

    response = client.post("/api/v1/battles/battle_1/turns/end", json={"notes": "结束第 3 回合"})

    assert response.status_code == 200
    body = response.json()
    assert body["ended_turn_number"] == 3
    assert body["next_turn_number"] == 4
    assert body["settlement_status"] == "settled"
    assert body["settlement_events"] == []
    assert body["battle"]["turn_number"] == 4
    assert body["battle_event"]["event_type"] == BattleEventType.TURN_END.value
    assert body["battle_event"]["turn_number"] == 3
    assert body["snapshot_id"]

    with session_factory() as session:
        battle = session.get(Battle, "battle_1")
        assert battle is not None
        assert battle.turn_number == 4
        assert battle.current_snapshot_id == body["snapshot_id"]
        event = session.scalar(
            select(BattleEvent).where(BattleEvent.event_type == BattleEventType.TURN_END.value)
        )
        assert event is not None
        assert event.snapshot_id == body["snapshot_id"]
        snapshot = session.get(BattleEffectSnapshot, body["snapshot_id"])
        assert snapshot is not None
        assert snapshot.turn_number == 4
        assert snapshot.source_event_id == event.event_id


def test_end_turn_settles_burn_damage_and_layer_change(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """结束回合会自动结算 P0 灼烧伤害，并按规则把层数减半。"""
    client, session_factory = api_client
    with session_factory() as session:
        session.add(
            Battle(
                battle_id="battle_settle",
                phase=BattlePhase.BATTLE.value,
                turn_number=1,
                self_active_elf_id="elf_self",
            )
        )
        session.add(
            ElfDefinition(
                elf_id="elf_self",
                elf_name="测试精灵",
                avatar="",
                element_types_json=dumps_json(["草"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            )
        )
        session.add(
            _effect_definition(
                effect_id="effect_burn",
                effect_name="灼烧",
                resource_rule={
                    "settlement_type": "end_turn",
                    "damage_kind": "status",
                    "percent_of": "target_max_hp",
                    "percent_per_layer": 0.02,
                    "element_type": "火",
                    "uses_type_effectiveness": True,
                    "after_settlement": {"layer_change": "halve_floor"},
                },
            )
        )
        session.flush()
        session.add(
            _elf_state(
                battle_id="battle_settle",
                side="self",
                elf_id="elf_self",
                hp=500,
            )
        )
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_burn",
                battle_id="battle_settle",
                effect_id="effect_burn",
                category="abnormal",
                owner_scope="elf",
                owner_side="self",
                owner_elf_id="elf_self",
                layers=10,
                is_active=True,
                applied_turn=1,
                manual_override=True,
            )
        )
        session.commit()

    response = client.post("/api/v1/battles/battle_settle/turns/end", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["settlement_status"] == "settled"
    assert body["battle"]["turn_number"] == 2
    assert body["settlement_events"][0]["effect_id"] == "effect_burn"
    assert body["settlement_events"][0]["damage_value"] == 100
    assert body["settlement_events"][0]["layers_before"] == 10
    assert body["settlement_events"][0]["layers_after"] == 5

    with session_factory() as session:
        state = session.scalar(
            select(_battle_models.BattleElfState).where(
                _battle_models.BattleElfState.battle_id == "battle_settle",
                _battle_models.BattleElfState.elf_id == "elf_self",
            )
        )
        assert state is not None
        assert state.current_hp_value == 400
        assert state.current_hp_percent == 80.0

        instance = session.get(BattleEffectInstance, "effect_instance_burn")
        assert instance is not None
        assert instance.layers == 5
        assert instance.is_active is True

        damage_event = session.scalar(
            select(DamageEvent).where(DamageEvent.battle_id == "battle_settle")
        )
        assert damage_event is not None
        assert damage_event.damage_value == 100
        assert damage_event.special_formula_id == "effect_burn"
        assert damage_event.formula_context_json is not None

        resource_event = session.scalar(
            select(ResourceChangeEvent).where(ResourceChangeEvent.battle_id == "battle_settle")
        )
        assert resource_event is not None
        assert resource_event.change_type == "damage"
        assert resource_event.value == 100

        effect_change = session.scalar(
            select(EffectChangeEvent).where(EffectChangeEvent.battle_id == "battle_settle")
        )
        assert effect_change is not None
        assert effect_change.change_type == "settlement_layer_change"


def test_damage_event_triggers_starfall_and_candidate_observation(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """攻击后星陨会生成额外伤害事件，并把伤害写入实时估计。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_two_active_elves(session, battle_id="battle_starfall", enemy_hp=500)
        session.add(
            SkillDefinition(
                skill_id="skill_fire",
                skill_name="火系测试技能",
                element_type="火",
                skill_category="physical",
                base_power=50,
                base_energy_cost=0,
                priority_modifier=0,
            )
        )
        session.add(
            _effect_definition(
                effect_id="effect_starfall_mark",
                effect_name="星陨印记",
                category="mark",
                owner_scope="side",
                hooks=["post_attack_trigger_damage"],
                resource_rule={
                    "settlement_type": "post_attack",
                    "damage_kind": "attack",
                    "element_type": "幻",
                    "uses_type_effectiveness": True,
                    "affected_by_reduction": True,
                    "after_settlement": {"layer_change": "clear"},
                },
                special_rule_id="starfall_damage",
            )
        )
        session.flush()
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_starfall",
                battle_id="battle_starfall",
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
        _seed_candidate(session, battle_id="battle_starfall", elf_id="elf_enemy")
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_starfall/damage-events",
        json={
            "attacker_side": "self",
            "attacker_elf_id": "elf_self",
            "defender_side": "enemy",
            "defender_elf_id": "elf_enemy",
            "skill_id": "skill_fire",
            "skill_confirmed": True,
            "damage_display_type": "single_damage",
            "damage_value": 10,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["post_settlement_events"][0]["effect_id"] == "effect_starfall_mark"
    assert body["post_settlement_events"][0]["damage_value"] == 50
    assert body["post_settlement_events"][0]["layers_after"] == 0
    assert body["post_settlement_events"][0]["observation_result"]["status"] == "estimate_updated"

    with session_factory() as session:
        damage_events = list(
            session.scalars(
                select(DamageEvent)
                .where(DamageEvent.battle_id == "battle_starfall")
                .order_by(DamageEvent.created_at)
            ).all()
        )
        assert len(damage_events) == 2
        assert damage_events[1].damage_value == 50
        assert damage_events[1].special_formula_id == "starfall_damage"

        state = session.scalar(
            select(_battle_models.BattleElfState).where(
                _battle_models.BattleElfState.battle_id == "battle_starfall",
                _battle_models.BattleElfState.elf_id == "elf_enemy",
            )
        )
        assert state is not None
        assert state.current_hp_value == 440

        instance = session.get(BattleEffectInstance, "effect_instance_starfall")
        assert instance is not None
        assert instance.is_active is False

        candidate = session.get(BuildCandidate, "candidate_battle_starfall")
        assert candidate is not None
        assert candidate.evidence_ids_json is None
        estimate = session.scalar(
            select(EnemyPanelEstimate).where(
                EnemyPanelEstimate.battle_id == "battle_starfall",
                EnemyPanelEstimate.elf_id == "elf_enemy",
            )
        )
        assert estimate is not None
        summary = loads_json(estimate.evidence_summary_json, [])
        assert summary[-1]["observation_type"] == "damage_value"


def test_damage_event_records_defense_skill_context(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """伤害事件应记录防御技能和应对结果，并把 defense_skill_id 接入规则解析。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_two_active_elves(session, battle_id="battle_defense_context")
        session.add_all(
            [
                SkillDefinition(
                    skill_id="skill_fire",
                    skill_name="火系测试技能",
                    element_type="火",
                    skill_category="physical",
                    base_power=50,
                    base_energy_cost=0,
                    priority_modifier=0,
                ),
                SkillDefinition(
                    skill_id="skill_guard",
                    skill_name="防御测试技能",
                    element_type="普通",
                    skill_category="status",
                    base_power=None,
                    base_energy_cost=1,
                    priority_modifier=0,
                    damage_rule_json=dumps_json(
                        {
                            "damage_type": "defense_modifier",
                            "damage_reduction": 0.7,
                            "active": True,
                            "condition": "response_attack_success",
                        }
                    ),
                ),
            ]
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_defense_context/damage-events",
        json={
            "attacker_side": "self",
            "attacker_elf_id": "elf_self",
            "defender_side": "enemy",
            "defender_elf_id": "elf_enemy",
            "skill_id": "skill_fire",
            "skill_confirmed": True,
            "defense_skill_id": "skill_guard",
            "response_attack_success": True,
            "response_defense_success": False,
            "damage_display_type": "single_damage",
            "damage_value": 10,
        },
    )

    assert response.status_code == 201
    body = response.json()
    event_payload = loads_json(body["battle_event"]["payload_json"], {})
    assert event_payload["defense_skill_id"] == "skill_guard"
    assert event_payload["response_attack_success"] is True
    assert event_payload["response_defense_success"] is False

    context = loads_json(body["damage_event"]["formula_context_json"], {})
    assert context["defense_skill_id"] == "skill_guard"
    assert context["response_attack_success"] is True
    assert context["response_defense_success"] is False
    assert context["rule_resolution_enabled"] is True
    damage_reductions = context["rule_resolution_details"]["damage_reductions"]
    assert damage_reductions["items"][0]["source_id"] == "skill_guard"
    assert damage_reductions["items"][0]["reduction"] == "0.7"
    assert context["damage_reductions"] == ["0.7"]


def test_switch_in_settles_thorn_mark(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """切换入场会结算己方队伍侧棘刺印记。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_two_active_elves(session, battle_id="battle_thorn", self_active_elf_id="elf_old")
        session.add(
            ElfDefinition(
                elf_id="elf_new",
                elf_name="新上场测试精灵",
                avatar="",
                element_types_json=dumps_json(["火"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            )
        )
        session.flush()
        session.add(
            _elf_state(
                battle_id="battle_thorn",
                side="self",
                elf_id="elf_new",
                hp=500,
                is_active_elf=False,
            )
        )
        session.add(
            _effect_definition(
                effect_id="effect_thorn_mark",
                effect_name="棘刺印记",
                category="mark",
                owner_scope="side",
                hooks=["switch_in_status_damage"],
                resource_rule={
                    "settlement_type": "switch_in",
                    "damage_kind": "true",
                    "percent_of": "target_max_hp",
                    "percent_per_layer": 0.06,
                    "uses_type_effectiveness": False,
                    "after_settlement": {"layer_change": "unchanged"},
                },
            )
        )
        session.flush()
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_thorn",
                battle_id="battle_thorn",
                effect_id="effect_thorn_mark",
                category="mark",
                owner_scope="side",
                owner_side="self",
                layers=2,
                is_active=True,
                applied_turn=1,
                manual_override=True,
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/battles/battle_thorn/switch",
        json={"side": "self", "elf_id": "elf_new"},
    )

    assert response.status_code == 200
    with session_factory() as session:
        new_state = session.scalar(
            select(_battle_models.BattleElfState).where(
                _battle_models.BattleElfState.battle_id == "battle_thorn",
                _battle_models.BattleElfState.elf_id == "elf_new",
            )
        )
        assert new_state is not None
        assert new_state.current_hp_value == 440
        damage_event = session.scalar(
            select(DamageEvent).where(DamageEvent.battle_id == "battle_thorn")
        )
        assert damage_event is not None
        assert damage_event.damage_value == 60


def test_end_turn_blizzard_applies_freeze_to_both_active_elves(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """暴风雪天气的回合末 apply_effect 会给双方当前上场精灵施加冻结。"""
    client, session_factory = api_client
    with session_factory() as session:
        _seed_two_active_elves(session, battle_id="battle_blizzard")
        session.add(
            _effect_definition(
                effect_id="effect_freeze",
                effect_name="冻结",
                resource_rule={
                    "settlement_type": "threshold",
                    "damage_kind": "threshold_defeat",
                    "threshold_percent_per_layer": 5,
                },
                hooks=["freeze_threshold_check"],
            )
        )
        session.add(
            _effect_definition(
                effect_id="weather_blizzard",
                effect_name="暴风雪",
                category="weather",
                owner_scope="field",
                hooks=["end_turn_apply_effect"],
                resource_rule={
                    "settlement_type": "end_turn",
                    "operation": "apply_effect",
                    "effect_id": "effect_freeze",
                    "target": "both_active_elves",
                    "layers": 2,
                },
            )
        )
        session.flush()
        session.add(
            BattleEffectInstance(
                instance_id="effect_instance_blizzard",
                battle_id="battle_blizzard",
                effect_id="weather_blizzard",
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

    response = client.post("/api/v1/battles/battle_blizzard/turns/end", json={})

    assert response.status_code == 200
    body = response.json()
    applied = [
        item for item in body["settlement_events"] if item.get("operation") == "apply_effect"
    ]
    assert len(applied) == 2
    assert {item["target_side"] for item in applied} == {"self", "enemy"}
    with session_factory() as session:
        freeze_instances = list(
            session.scalars(
                select(BattleEffectInstance).where(
                    BattleEffectInstance.battle_id == "battle_blizzard",
                    BattleEffectInstance.effect_id == "effect_freeze",
                )
            ).all()
        )
        assert len(freeze_instances) == 2
        assert {item.layers for item in freeze_instances} == {2}


def test_end_turn_rejects_non_battle_phase(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """准备阶段不能结束回合。"""
    client, _session_factory = api_client

    response = client.post("/api/v1/battles/preparation_battle/turns/end", json={})

    assert response.status_code == 400


def _effect_definition(
    *,
    effect_id: str,
    effect_name: str,
    resource_rule: dict,
    category: str = "abnormal",
    owner_scope: str = "elf",
    hooks: list[str] | None = None,
    special_rule_id: str | None = None,
) -> EffectDefinition:
    """构造回合结算测试用的状态定义。"""
    return EffectDefinition(
        effect_id=effect_id,
        effect_name=effect_name,
        category=category,
        polarity="neutral" if category == "weather" else "negative",
        display_group=category,
        display_priority=100,
        owner_scope=owner_scope,
        target_scope="field" if owner_scope == "field" else "single_elf",
        attach_target_type=owner_scope,
        is_visible_icon=True,
        is_recognizable_by_icon=False,
        default_layers=1,
        stack_rule="replace" if owner_scope == "field" else "add_layers",
        duration_type="until_removed",
        clear_on_switch=owner_scope == "elf",
        formula_hooks_json=dumps_json(hooks or ["end_turn_status_damage"]),
        resource_modifier_json=dumps_json(resource_rule),
        special_rule_id=special_rule_id,
    )


def _elf_state(
    *,
    battle_id: str,
    side: str,
    elf_id: str,
    hp: int,
    is_active_elf: bool = True,
    physical_attack: int = 100,
    physical_defense: int = 100,
    magic_attack: int = 100,
    magic_defense: int = 100,
    speed: int = 100,
) -> _battle_models.BattleElfState:
    """构造测试精灵运行时状态。"""
    return _battle_models.BattleElfState(
        state_id=f"state_{battle_id}_{side}_{elf_id}",
        battle_id=battle_id,
        side=side,
        elf_id=elf_id,
        elf_name="测试精灵",
        avatar="",
        panel_stats_json=dumps_json(
            {
                "hp": hp,
                "physical_attack": physical_attack,
                "physical_defense": physical_defense,
                "magic_attack": magic_attack,
                "magic_defense": magic_defense,
                "speed": speed,
            }
        ),
        current_hp_value=hp,
        current_hp_percent=100.0,
        energy=0,
        active_effect_instance_ids_json=dumps_json([]),
        is_active_elf=is_active_elf,
        is_defeated=False,
        manual_override=True,
    )


def _seed_two_active_elves(
    session: Session,
    *,
    battle_id: str,
    self_active_elf_id: str = "elf_self",
    enemy_active_elf_id: str = "elf_enemy",
    self_hp: int = 500,
    enemy_hp: int = 500,
) -> None:
    """构造一场 battle 阶段、双方各一个上场精灵的测试战斗。"""
    session.add(
        Battle(
            battle_id=battle_id,
            phase=BattlePhase.BATTLE.value,
            turn_number=1,
            self_active_elf_id=self_active_elf_id,
            enemy_active_elf_id=enemy_active_elf_id,
        )
    )
    session.add_all(
        [
            ElfDefinition(
                elf_id=self_active_elf_id,
                elf_name="己方测试精灵",
                avatar="",
                element_types_json=dumps_json(["火"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
            ElfDefinition(
                elf_id=enemy_active_elf_id,
                elf_name="敌方测试精灵",
                avatar="",
                element_types_json=dumps_json(["草"]),
                base_hp_talent=100,
                base_physical_attack_talent=100,
                base_physical_defense_talent=100,
                base_magic_attack_talent=100,
                base_magic_defense_talent=100,
                base_speed_talent=100,
            ),
        ]
    )
    session.flush()
    session.add(
        _elf_state(
            battle_id=battle_id,
            side="self",
            elf_id=self_active_elf_id,
            hp=self_hp,
            physical_attack=200,
        )
    )
    session.add(
        _elf_state(
            battle_id=battle_id,
            side="enemy",
            elf_id=enemy_active_elf_id,
            hp=enemy_hp,
            physical_defense=100,
            magic_defense=150,
        )
    )


def _seed_candidate(session: Session, *, battle_id: str, elf_id: str) -> None:
    """为目标敌方精灵构造一个候选，用于验证 Observation 软评分写入。"""
    session.add(
        NatureDefinition(
            nature_id=f"nature_{battle_id}",
            nature_name="测试性格",
            positive_stat="physical_attack",
            positive_multiplier=1.0,
            negative_stat="physical_defense",
            negative_multiplier=1.0,
            neutral_multiplier=1.0,
        )
    )
    session.flush()
    session.add(
        BuildCandidate(
            candidate_id=f"candidate_{battle_id}",
            battle_id=battle_id,
            side="enemy",
            elf_id=elf_id,
            nature_id=f"nature_{battle_id}",
            individual_talent_distribution_json=dumps_json({}),
            final_hp=500,
            final_physical_attack=100,
            final_physical_defense=100,
            final_magic_attack=100,
            final_magic_defense=150,
            final_speed=100,
            match_score=0,
            confidence=0,
            is_excluded=False,
        )
    )
