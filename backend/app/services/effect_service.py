from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.effect import BattleEffectInstance
from app.models.static import EffectDefinition


class BattleEffectService:
    """统一状态实例服务骨架。后续在这里实现 apply/remove/stack/switch_clear。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_active_effects(self, battle_id: str) -> list[BattleEffectInstance]:
        stmt = select(BattleEffectInstance).where(
            BattleEffectInstance.battle_id == battle_id,
            BattleEffectInstance.is_active.is_(True),
        )
        return list(self.db.scalars(stmt).all())

    def get_definition(self, effect_id: str) -> EffectDefinition | None:
        return self.db.get(EffectDefinition, effect_id)
