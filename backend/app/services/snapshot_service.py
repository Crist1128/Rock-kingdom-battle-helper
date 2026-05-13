import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.effect import BattleEffectSnapshot
from app.services.effect_service import BattleEffectService


class SnapshotService:
    """状态快照服务骨架。第一阶段快照直接保存实例 ID 列表和展示分组 JSON。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_effect_snapshot(
        self,
        battle_id: str,
        turn_number: int,
        source_event_id: str | None = None,
    ) -> BattleEffectSnapshot:
        effects = BattleEffectService(self.db).list_active_effects(battle_id)
        active_ids = [item.instance_id for item in effects]
        snapshot = BattleEffectSnapshot(
            snapshot_id=f"snapshot_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=turn_number,
            active_effect_instance_ids_json=json.dumps(active_ids, ensure_ascii=False),
            full_snapshot_json=json.dumps(
                [self._model_to_dict(item) for item in effects], ensure_ascii=False, default=str
            ),
            source_event_id=source_event_id,
        )
        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    @staticmethod
    def _model_to_dict(model: object) -> dict:
        return {column.name: getattr(model, column.name) for column in model.__table__.columns}  # type: ignore[attr-defined]
