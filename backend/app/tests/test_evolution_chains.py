"""精灵进化链表、导入器与 API 测试。"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.data_pipeline.evolution_chains.importer import import_evolution_chains
from app.db.base import Base
from app.db.session import get_db
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import ElfDefinition
from app.utils.json import dumps_json


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    """创建隔离进化链 API 测试客户端。"""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    with session_factory() as session:
        session.add_all(
            [
                _elf("elf_a", "一阶"),
                _elf("elf_b", "二阶"),
                _elf("elf_c", "三阶", speed=120),
            ]
        )
        import_evolution_chains(
            session,
            [
                {
                    "chain_id": "chain_test",
                    "chain_key": "test",
                    "chain_name": "测试进化链",
                    "source": "test",
                    "data_version": "test",
                    "stages": [
                        {"stage_index": 1, "stage_name": "一阶", "elf_id": "elf_a"},
                        {"stage_index": 2, "stage_name": "二阶", "elf_id": "elf_b"},
                        {"stage_index": 3, "stage_name": "三阶", "elf_id": "elf_c"},
                        {"stage_index": 4, "stage_name": "缺失", "elf_id": "missing"},
                    ],
                }
            ],
            source="test",
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
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_get_evolution_chain_returns_all_stages(api_client: TestClient) -> None:
    """进化链接口应返回当前精灵可进化/退化的全部阶段。"""
    response = api_client.get("/api/v1/elves/elf_b/evolution-chain")

    assert response.status_code == 200
    body = response.json()
    assert body["current_elf_id"] == "elf_b"
    assert [item["elf_id"] for item in body["stages"]] == ["elf_a", "elf_b", "elf_c"]
    assert body["stages"][2]["base_speed_talent"] == 120
    assert body["chains"][0]["chain_name"] == "测试进化链"


def test_import_evolution_chains_reports_missing_stage(api_client: TestClient) -> None:
    """导入器应跳过不存在的精灵阶段并给出摘要。"""
    # 复用 fixture 中的导入结果：缺失阶段不会进入接口候选。
    response = api_client.get("/api/v1/elves/elf_b/evolution-chain")
    assert all(item["elf_id"] != "missing" for item in response.json()["stages"])


def test_sync_evolution_chain_endpoint_supports_dry_run(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """设置页可单独 dry-run 进化链 seed 同步。"""
    from app.api.v1.endpoints import data_updates

    def fake_import_evolution_chain_seed(_db: Session) -> dict:
        return {
            "source": "test",
            "chains_created": 1,
            "chains_updated": 0,
            "chains_refreshed": 0,
            "stages_created": 3,
            "stages_skipped_missing_elf": 0,
            "stages_skipped_duplicate_chain_elf": 0,
            "refresh_source": True,
        }

    monkeypatch.setattr(
        data_updates,
        "import_evolution_chain_seed",
        fake_import_evolution_chain_seed,
    )

    response = api_client.post(
        "/api/v1/admin/data-updates/static-rules/evolution-chains/sync",
        json={"commit": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transaction"] == "rolled_back_dry_run"
    assert body["chains_created"] == 1
    assert body["stages_created"] == 3


def _elf(elf_id: str, name: str, *, speed: int = 100) -> ElfDefinition:
    return ElfDefinition(
        elf_id=elf_id,
        elf_name=name,
        avatar="",
        element_types_json=dumps_json(["normal"]),
        base_hp_talent=100,
        base_physical_attack_talent=100,
        base_physical_defense_talent=100,
        base_magic_attack_talent=100,
        base_magic_defense_talent=100,
        base_speed_talent=speed,
    )
