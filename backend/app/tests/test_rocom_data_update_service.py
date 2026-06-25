"""Tests for rocom data update job safety and progress behavior."""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import EffectDefinition, SkillDefinition
from app.services import rocom_data_update_service as service
from app.services.rocom_data_update_service import RocomUpdateParams
from app.utils.json import dumps_json, loads_json


@pytest.fixture(autouse=True)
def clear_rocom_update_jobs():
    """Keep in-memory job registry isolated between tests."""
    with service._jobs_lock:
        service._jobs.clear()
    yield
    with service._jobs_lock:
        service._jobs.clear()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """Create an isolated in-memory database for project seed import tests."""
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


def test_validate_update_params_rejects_limited_commit_refresh() -> None:
    """A partial scrape must not be committed as a full static refresh."""
    params = RocomUpdateParams(commit=True, refresh_static=True, limit=3)

    with pytest.raises(ValueError):
        service._validate_update_params(params)


def test_validate_update_params_allows_limited_dry_run_refresh() -> None:
    """Limited refresh is allowed when commit is false because the transaction rolls back."""
    params = RocomUpdateParams(commit=False, refresh_static=True, limit=3)

    service._validate_update_params(params)


def test_validate_update_params_rejects_new_only_refresh_static() -> None:
    """New-only mode must not soft-delete missing rows as a full refresh."""
    params = RocomUpdateParams(update_mode="new_only", refresh_static=True)

    with pytest.raises(ValueError):
        service._validate_update_params(params)


def test_create_rocom_update_job_rejects_dangerous_params_without_polluting_jobs() -> None:
    """Dangerous params should fail before a background job is registered."""
    params = RocomUpdateParams(commit=True, refresh_static=True, limit=3)

    with pytest.raises(ValueError):
        service.create_rocom_update_job(params)

    assert service.list_rocom_update_jobs() == []


def test_rocom_update_job_progress_is_returned_in_status() -> None:
    """Progress updates should be visible through the job status payload."""
    job = service.create_rocom_update_job(RocomUpdateParams())

    service._update_job_progress(
        job["job_id"],
        {"stage": "scrape_sprites", "message": "test", "current": 1, "total": 2, "percent": 50},
    )

    status = service.get_rocom_update_job(job["job_id"])
    assert status is not None
    assert status["progress"]["stage"] == "scrape_sprites"
    assert status["progress"]["percent"] == 50


def test_import_project_seed_rules_adds_effects_and_updates_strength_skill(
    db_session: Session,
) -> None:
    """Project seed import should make cleaned rocom skill operations executable on an empty DB."""
    db_session.add(
        SkillDefinition(
            skill_id="rocom_skill_5656feeb59",
            skill_name="力量增效",
            element_type="普通",
            skill_category="status",
            base_power=None,
            base_energy_cost=1,
            priority_modifier=0,
            effect_operations_json=dumps_json(
                [
                    {
                        "operation": "apply_effect",
                        "effect_id": "effect_physical_attack_up_layered",
                        "target": "actor_side",
                        "layers": 10,
                    }
                ]
            ),
        )
    )
    db_session.commit()

    summary = service.import_project_seed_rules(db_session)

    effect = db_session.get(EffectDefinition, "effect_physical_attack_up_layered")
    skill = db_session.get(SkillDefinition, "rocom_skill_5656feeb59")
    assert effect is not None
    assert effect.owner_scope == "elf"
    assert effect.stack_rule == "add_layers"
    assert skill is not None
    operations = loads_json(skill.effect_operations_json, [])
    assert operations[0]["op_type"] == "apply_effect"
    assert operations[0]["layers"] == 10
    assert summary["effect_seed_files"]
    assert summary["skill_review_seed_files"][0]["skills_updated"] == 1
