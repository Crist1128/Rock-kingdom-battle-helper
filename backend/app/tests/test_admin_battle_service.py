"""管理端战斗物理清理服务测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import BattlePhase
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import estimate as _estimate_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.battle import Battle, BattleElfState
from app.models.estimate import EnemyPanelEstimate, EnemyPanelEstimateEvidence
from app.models.static import ElfDefinition
from app.services.admin_battle_service import AdminBattleService
from app.utils.json import dumps_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建启用外键约束的独立内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _set_foreign_keys(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_purge_archived_battle_deletes_realtime_estimates_first(db_session: Session) -> None:
    """归档清理应先删实时反推证据和估计表，避免 battle 主表外键失败。"""
    _seed_archived_battle_with_estimate(db_session)

    result = AdminBattleService(db_session).purge_archived_battles(dry_run=False, limit=50)

    assert result.battle_count == 1
    assert result.rows["enemy_panel_estimate_evidence"] == 1
    assert result.rows["enemy_panel_estimate"] == 1
    assert db_session.get(Battle, "battle_archived") is None
    assert db_session.scalars(select(EnemyPanelEstimate)).all() == []
    assert db_session.scalars(select(EnemyPanelEstimateEvidence)).all() == []


def _seed_archived_battle_with_estimate(db_session: Session) -> None:
    db_session.add(
        ElfDefinition(
            elf_id="elf_enemy",
            elf_name="测试敌方",
            avatar="",
            element_types_json=dumps_json(["normal"]),
            base_hp_talent=100,
            base_physical_attack_talent=100,
            base_physical_defense_talent=100,
            base_magic_attack_talent=100,
            base_magic_defense_talent=100,
            base_speed_talent=100,
        )
    )
    db_session.add(Battle(battle_id="battle_archived", phase=BattlePhase.ARCHIVED.value))
    db_session.flush()
    db_session.add(
        BattleElfState(
            state_id="state_enemy",
            battle_id="battle_archived",
            side="enemy",
            elf_id="elf_enemy",
            elf_name="测试敌方",
            avatar="",
            panel_stats_json=dumps_json(
                {
                    "hp": 100,
                    "physical_attack": 100,
                    "physical_defense": 100,
                    "magic_attack": 100,
                    "magic_defense": 100,
                    "speed": 100,
                }
            ),
        )
    )
    db_session.flush()
    db_session.add(
        EnemyPanelEstimate(
            estimate_id="estimate_enemy",
            battle_id="battle_archived",
            battle_elf_state_id="state_enemy",
            elf_id="elf_enemy",
            default_config_json=dumps_json({"nature_id": "nature_test"}),
        )
    )
    db_session.flush()
    db_session.add(
        EnemyPanelEstimateEvidence(
            evidence_id="evidence_enemy",
            estimate_id="estimate_enemy",
            battle_id="battle_archived",
            source_event_id="event_damage_1",
            observation_type="damage_dealt",
        )
    )
    db_session.commit()
