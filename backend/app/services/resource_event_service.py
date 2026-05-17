"""
生命 / 能量变化事件服务。

该服务补齐第一阶段 MVP 中除伤害外的资源事实记录能力，例如治疗、能量获得、
能量消耗和手动校正。所有资源变化事件都会绑定 BattleEffectSnapshot，保证后续
公式确认或事件回放时可以基于当时的状态上下文重算。
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import BattleEventType, EventSource
from app.models.battle import Battle, BattleElfState
from app.models.event import BattleEvent, ResourceChangeEvent
from app.schemas.event import ResourceChangeEventCreate, ResourceChangeEventCreateResult
from app.services.battle_service import BattleService
from app.services.snapshot_service import SnapshotService
from app.utils.json import dumps_json


class ResourceEventService:
    """手动资源变化事件业务服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_resource_change_event(
        self,
        battle_id: str,
        payload: ResourceChangeEventCreate,
    ) -> ResourceChangeEventCreateResult:
        """
        创建治疗 / 能量变化事件并同步更新 BattleElfState。

        设计边界：
        - 本服务只记录用户输入的事实，不推导隐藏公式；
        - value_type=percent 时主要更新 current_hp_percent；
        - value_type=value 时根据 resource_type 更新 current_hp_value 或 energy；
        - 如果传入 after_value，优先把 after_value 作为最新观测值。这样便于人工修正。
        """
        battle = BattleService(self.db).require_battle(battle_id)
        turn_number = payload.turn_number if payload.turn_number is not None else battle.turn_number
        event_type = self._event_type(payload)

        battle_event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=turn_number,
            event_type=event_type,
            actor_side=payload.source_side,
            actor_elf_id=payload.source_elf_id,
            target_side=payload.target_side,
            target_elf_id=payload.target_elf_id,
            skill_id=payload.skill_id,
            skill_confirmed=payload.skill_id is not None,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
            payload_json=dumps_json(payload.model_dump(mode="json")),
            notes=payload.notes,
        )
        self.db.add(battle_event)
        self.db.flush()

        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle_id,
            turn_number,
            source_event_id=battle_event.event_id,
            commit=False,
        )
        battle_event.snapshot_id = snapshot.snapshot_id

        resource_event = ResourceChangeEvent(
            event_id=f"resource_event_{uuid4().hex}",
            battle_id=battle_id,
            battle_event_id=battle_event.event_id,
            resource_type=payload.resource_type,
            change_type=payload.change_type,
            source_side=payload.source_side,
            source_elf_id=payload.source_elf_id,
            target_side=payload.target_side,
            target_elf_id=payload.target_elf_id,
            value_type=payload.value_type,
            value=payload.value,
            before_value=payload.before_value,
            after_value=payload.after_value,
            confidence=payload.confidence,
            manual_override=True,
        )
        self.db.add(resource_event)
        self._update_target_state(battle, payload)
        self.db.commit()
        self.db.refresh(battle_event)
        self.db.refresh(resource_event)
        return ResourceChangeEventCreateResult(
            battle_event=battle_event,
            resource_change_event=resource_event,
            snapshot_id=snapshot.snapshot_id,
        )

    @staticmethod
    def _event_type(payload: ResourceChangeEventCreate) -> str:
        """根据资源类型和变化类型选择通用事件类型。"""
        if payload.resource_type == "hp" and payload.change_type == "heal":
            return BattleEventType.HEAL.value
        if payload.resource_type == "energy":
            return BattleEventType.ENERGY_CHANGE.value
        return "resource_change"

    def _update_target_state(self, battle: Battle, payload: ResourceChangeEventCreate) -> None:
        """把资源变化同步到当前运行时精灵状态。"""
        if payload.target_side is None or payload.target_elf_id is None:
            return
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle.battle_id,
                BattleElfState.side == payload.target_side,
                BattleElfState.elf_id == payload.target_elf_id,
            )
        ).first()
        if state is None:
            return

        if payload.resource_type == "hp":
            self._update_hp_state(state, payload)
        elif payload.resource_type == "energy":
            self._update_energy_state(state, payload)

    @staticmethod
    def _update_hp_state(state: BattleElfState, payload: ResourceChangeEventCreate) -> None:
        """根据手动资源事件更新生命值或生命百分比。"""
        if payload.value_type == "percent":
            if payload.after_value is not None:
                state.current_hp_percent = max(min(payload.after_value, 100.0), 0.0)
            elif payload.change_type == "heal" and state.current_hp_percent is not None:
                state.current_hp_percent = min(state.current_hp_percent + payload.value, 100.0)
            elif (
                payload.change_type in {"damage", "consume"}
                and state.current_hp_percent is not None
            ):
                state.current_hp_percent = max(state.current_hp_percent - payload.value, 0.0)
        else:
            if payload.after_value is not None:
                state.current_hp_value = max(int(payload.after_value), 0)
            elif state.current_hp_value is not None:
                delta = int(payload.value)
                if payload.change_type == "heal":
                    state.current_hp_value += delta
                elif payload.change_type in {"damage", "consume"}:
                    state.current_hp_value = max(state.current_hp_value - delta, 0)
        state.is_defeated = state.current_hp_value == 0 or state.current_hp_percent == 0

    @staticmethod
    def _update_energy_state(state: BattleElfState, payload: ResourceChangeEventCreate) -> None:
        """根据手动资源事件更新能量。"""
        if payload.after_value is not None:
            state.energy = max(int(payload.after_value), 0)
            return
        delta = int(payload.value)
        if payload.change_type in {"gain", "heal", "add"}:
            state.energy += delta
        elif payload.change_type in {"consume", "spend", "remove"}:
            state.energy = max(state.energy - delta, 0)
