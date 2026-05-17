"""
状态快照服务模块。

快照用于保存事件发生时的状态事实。第一阶段重点保存 BattleEffectInstance，
保证后续公式确认后可以基于历史快照重算，而不是读取已经变化的当前状态。
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.battle import Battle
from app.models.effect import BattleEffectInstance, BattleEffectSnapshot
from app.services.effect_service import BattleEffectService
from app.utils.json import dumps_json, model_to_dict


class SnapshotService:
    """状态快照业务服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_effect_snapshot(
        self,
        battle_id: str,
        turn_number: int,
        source_event_id: str | None = None,
        *,
        commit: bool = True,
    ) -> BattleEffectSnapshot:
        """
        创建状态快照。

        快照内容包括：
        - 所有生效状态实例 ID；
        - 按 owner_scope 分组的状态 ID；
        - 完整状态实例副本；
        - 当前双方上场精灵 ID。
        """
        battle = self.db.get(Battle, battle_id)
        if battle is None or battle.deleted_at is not None:
            raise LookupError(f"战斗不存在：{battle_id}")

        effects = BattleEffectService(self.db).list_active_effects(battle_id)
        groups = self._group_effect_ids(effects)

        snapshot = BattleEffectSnapshot(
            snapshot_id=f"snapshot_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=turn_number,
            active_effect_instance_ids_json=dumps_json([item.instance_id for item in effects]),
            self_active_elf_id=battle.self_active_elf_id,
            enemy_active_elf_id=battle.enemy_active_elf_id,
            self_elf_effect_ids_json=dumps_json(groups["self_elf"]),
            enemy_elf_effect_ids_json=dumps_json(groups["enemy_elf"]),
            self_side_effect_ids_json=dumps_json(groups["self_side"]),
            enemy_side_effect_ids_json=dumps_json(groups["enemy_side"]),
            field_effect_ids_json=dumps_json(groups["field"]),
            skill_slot_effect_ids_json=dumps_json(groups["skill_slot"]),
            turn_effect_ids_json=dumps_json(groups["turn"]),
            full_snapshot_json=dumps_json([model_to_dict(item) for item in effects]),
            source_event_id=source_event_id,
        )
        self.db.add(snapshot)
        self.db.flush()
        battle.current_snapshot_id = snapshot.snapshot_id
        if commit:
            self.db.commit()
            self.db.refresh(snapshot)
        return snapshot

    @staticmethod
    def _group_effect_ids(effects: list[BattleEffectInstance]) -> dict[str, list[str]]:
        """按归属范围和阵营分组状态实例 ID。"""
        groups: dict[str, list[str]] = {
            "self_elf": [],
            "enemy_elf": [],
            "self_side": [],
            "enemy_side": [],
            "field": [],
            "skill_slot": [],
            "turn": [],
        }
        for item in effects:
            if item.owner_scope == "elf" and item.owner_side == "self":
                groups["self_elf"].append(item.instance_id)
            elif item.owner_scope == "elf" and item.owner_side == "enemy":
                groups["enemy_elf"].append(item.instance_id)
            elif item.owner_scope == "side" and item.owner_side == "self":
                groups["self_side"].append(item.instance_id)
            elif item.owner_scope == "side" and item.owner_side == "enemy":
                groups["enemy_side"].append(item.instance_id)
            elif item.owner_scope == "field":
                groups["field"].append(item.instance_id)
            elif item.owner_scope == "skill_slot":
                groups["skill_slot"].append(item.instance_id)
            elif item.owner_scope == "turn":
                groups["turn"].append(item.instance_id)
        return groups
