"""战斗事件重放服务。

当前服务先落地完整重放的骨架和最小运行时状态重建能力：
- 实时估计/evidence 由 EstimateService 从事件流重建；
- BattleElfState 的首发/切换、HP、能量按非作废事件流重算；
- BattleEffectInstance 按 EffectChangeEvent 重建最终状态；
- 按非作废事件流重建事件后 BattleEffectSnapshot 链；
- 自动结算副作用暂不重演。
"""

from collections import defaultdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.default_skills import DEFAULT_INITIAL_ENERGY
from app.core.enums import BattleEventType, Side
from app.db.base import utc_now
from app.models.battle import Battle, BattleElfState
from app.models.effect import BattleEffectInstance, BattleEffectSnapshot
from app.models.event import BattleEvent, DamageEvent, EffectChangeEvent, ResourceChangeEvent
from app.models.static import ElfDefinition
from app.services.estimate_service import EstimateService
from app.services.snapshot_service import SnapshotService
from app.utils.json import dumps_json, loads_json


class EventReplayService:
    """按事件流重建战斗派生状态。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def replay_from_event(
        self,
        battle_id: str,
        event_id: str,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        """从指定事件触发整场派生状态重建。

        现阶段为了避免半段事件重放导致状态不可逆，实际执行的是整场非作废事件流重建。
        `event_id` 用作触发点和审计标识。
        """
        battle = self._require_battle(battle_id)
        self._require_event(battle_id, event_id)

        events = self._ordered_events(battle_id)
        estimate_result = EstimateService(self.db).rebuild_battle_estimates_from_events(
            battle_id,
            from_event_id=event_id,
            commit=False,
        )
        runtime_result = self._rebuild_runtime_state(battle, events)

        if commit:
            self.db.commit()

        status = (
            "runtime_and_estimate_rebuilt"
            if runtime_result["runtime_replay_status"] == "partial_runtime_rebuilt"
            else "estimate_rebuilt"
        )
        return {
            **estimate_result,
            **runtime_result,
            "status": status,
            "message": (
                "已重建实时估计/evidence，并按非作废事件流重算基础运行时状态、"
                "状态实例和事件后快照链；自动结算副作用仍待后续阶段接入。"
            ),
        }

    def _rebuild_runtime_state(
        self,
        battle: Battle,
        events: list[BattleEvent],
    ) -> dict[str, Any]:
        states = list(
            self.db.scalars(
                select(BattleElfState)
                .where(BattleElfState.battle_id == battle.battle_id)
                .order_by(BattleElfState.side, BattleElfState.created_at)
            ).all()
        )
        state_by_key = {(state.side, state.elf_id): state for state in states}
        initial_active = self._initial_active_elf_ids(battle)
        self._restore_runtime_form_baseline(states, events)
        self._reset_runtime_states(battle, states, initial_active)

        event_ids = [event.event_id for event in events]
        self._soft_delete_event_snapshots(battle.battle_id, event_ids)
        resources_by_event_id: dict[str, list[ResourceChangeEvent]] = defaultdict(list)
        effect_changes_by_event_id: dict[str, list[EffectChangeEvent]] = defaultdict(list)
        damage_by_event_id: dict[str, DamageEvent] = {}
        self.db.execute(
            delete(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle.battle_id
            )
        )
        if event_ids:
            for item in self.db.scalars(
                select(ResourceChangeEvent).where(ResourceChangeEvent.battle_event_id.in_(event_ids))
            ).all():
                resources_by_event_id[item.battle_event_id].append(item)
            for item in self.db.scalars(
                select(EffectChangeEvent).where(EffectChangeEvent.battle_event_id.in_(event_ids))
            ).all():
                effect_changes_by_event_id[item.battle_event_id].append(item)
            damage_by_event_id = {
                item.battle_event_id: item
                for item in self.db.scalars(
                    select(DamageEvent).where(DamageEvent.battle_event_id.in_(event_ids))
                ).all()
            }

        switch_event_count = 0
        resource_event_count = 0
        effect_change_event_count = 0
        damage_fallback_count = 0
        skipped_runtime_event_count = 0
        unsupported_event_types: set[str] = set()
        replayed_turn_number = battle.turn_number
        effect_instances_by_id: dict[str, BattleEffectInstance] = {}
        snapshot_rebuilt_count = 0
        runtime_snapshot_id: str | None = None

        for event in events:
            if self._apply_switch_event(battle, state_by_key, event):
                switch_event_count += 1
            self._apply_runtime_form_event(state_by_key, event)
            if event.event_type == BattleEventType.TURN_END.value:
                replayed_turn_number = self._turn_number_after_event(event, replayed_turn_number)

            effect_changes = effect_changes_by_event_id.get(event.event_id, [])
            for change in effect_changes:
                if self._apply_effect_change_event(effect_instances_by_id, change):
                    effect_change_event_count += 1
                else:
                    skipped_runtime_event_count += 1

            resources = resources_by_event_id.get(event.event_id, [])
            if resources:
                for resource in resources:
                    if self._apply_resource_event(state_by_key, resource):
                        resource_event_count += 1
                    else:
                        skipped_runtime_event_count += 1
            else:
                damage_event = damage_by_event_id.get(event.event_id)
                if damage_event is not None and self._apply_damage_fallback(
                    state_by_key,
                    damage_event,
                ):
                    damage_fallback_count += 1

            if (
                not resources
                and event.event_id not in damage_by_event_id
                and not self._event_has_runtime_handler(event)
            ):
                unsupported_event_types.add(event.event_type)

            snapshot = SnapshotService(self.db).create_effect_snapshot(
                battle.battle_id,
                event.turn_number,
                source_event_id=event.event_id,
                commit=False,
            )
            event.snapshot_id = snapshot.snapshot_id
            runtime_snapshot_id = snapshot.snapshot_id
            snapshot_rebuilt_count += 1

        if runtime_snapshot_id is None:
            snapshot = SnapshotService(self.db).create_effect_snapshot(
                battle.battle_id,
                replayed_turn_number,
                commit=False,
            )
            runtime_snapshot_id = snapshot.snapshot_id
            snapshot_rebuilt_count = 1

        battle.turn_number = replayed_turn_number
        active_effect_count = sum(
            1 for instance in effect_instances_by_id.values() if instance.is_active
        )
        return {
            "runtime_replay_status": "partial_runtime_rebuilt",
            "runtime_state_updated_count": len(states),
            "runtime_switch_event_count": switch_event_count,
            "runtime_resource_event_count": resource_event_count,
            "runtime_effect_change_event_count": effect_change_event_count,
            "runtime_active_effect_count": active_effect_count,
            "runtime_snapshot_id": runtime_snapshot_id,
            "runtime_snapshot_rebuilt_count": snapshot_rebuilt_count,
            "runtime_snapshot_effect_count": active_effect_count,
            "runtime_damage_fallback_count": damage_fallback_count,
            "runtime_skipped_event_count": skipped_runtime_event_count,
            "runtime_unsupported_event_types": sorted(unsupported_event_types),
        }
    def _soft_delete_event_snapshots(self, battle_id: str, event_ids: list[str]) -> None:
        """软删除本次重放会重新绑定的旧事件快照，避免重复重放持续堆积。"""
        if not event_ids:
            return
        deleted_at = utc_now()
        snapshots = self.db.scalars(
            select(BattleEffectSnapshot).where(
                BattleEffectSnapshot.battle_id == battle_id,
                BattleEffectSnapshot.source_event_id.in_(event_ids),
                BattleEffectSnapshot.deleted_at.is_(None),
            )
        ).all()
        for snapshot in snapshots:
            snapshot.deleted_at = deleted_at

    def _reset_runtime_states(
        self,
        battle: Battle,
        states: list[BattleElfState],
        initial_active: dict[str, str | None],
    ) -> None:
        for state in states:
            max_hp = self._max_hp_from_state(state)
            if state.side == Side.SELF.value and max_hp is not None:
                state.current_hp_value = max_hp
            elif state.side == Side.ENEMY.value:
                state.current_hp_value = None
            state.current_hp_percent = 100.0
            state.energy = DEFAULT_INITIAL_ENERGY
            state.is_defeated = False
            active_elf_id = initial_active.get(state.side)
            state.is_active_elf = active_elf_id == state.elf_id
            state.last_switch_turn = 0 if state.is_active_elf else None

        battle.self_active_elf_id = initial_active.get(Side.SELF.value)
        battle.enemy_active_elf_id = initial_active.get(Side.ENEMY.value)

    @staticmethod
    def _restore_runtime_form_baseline(
        states: list[BattleElfState],
        events: list[BattleEvent],
    ) -> None:
        """重放前先恢复运行时形态事件记录的原始面板，避免当前有效形态污染基线。"""
        state_by_id = {state.state_id: state for state in states}
        seen_state_ids: set[str] = set()
        for event in events:
            if event.event_type != BattleEventType.RUNTIME_FORM_CHANGE.value:
                continue
            payload = loads_json(event.payload_json, {}) or {}
            if not isinstance(payload, dict):
                continue
            state_id = payload.get("state_id")
            if not state_id or str(state_id) in seen_state_ids:
                continue
            state = state_by_id.get(str(state_id))
            if state is None:
                continue
            panel_before = payload.get("panel_before")
            if isinstance(panel_before, dict):
                state.panel_stats_json = dumps_json(panel_before)
            state.runtime_form_elf_id = None
            state.runtime_form_elf_name = None
            state.runtime_form_avatar = None
            state.runtime_form_reason = None
            seen_state_ids.add(str(state_id))

    def _initial_active_elf_ids(self, battle: Battle) -> dict[str, str | None]:
        snapshot = self.db.scalars(
            select(BattleEffectSnapshot)
            .where(BattleEffectSnapshot.battle_id == battle.battle_id)
            .order_by(BattleEffectSnapshot.turn_number, BattleEffectSnapshot.created_at)
        ).first()
        if snapshot is not None:
            return {
                Side.SELF.value: snapshot.self_active_elf_id,
                Side.ENEMY.value: snapshot.enemy_active_elf_id,
            }
        return {
            Side.SELF.value: battle.self_active_elf_id,
            Side.ENEMY.value: battle.enemy_active_elf_id,
        }

    def _apply_switch_event(
        self,
        battle: Battle,
        state_by_key: dict[tuple[str | None, str | None], BattleElfState],
        event: BattleEvent,
    ) -> bool:
        if event.event_type != BattleEventType.SWITCH_ELF.value:
            return False
        payload = loads_json(event.payload_json, {}) or {}
        side = event.target_side or event.actor_side
        elf_id = event.target_elf_id
        if isinstance(payload, dict):
            side = side or payload.get("side")
            elf_id = elf_id or payload.get("to_elf_id")
        if side not in {Side.SELF.value, Side.ENEMY.value} or not elf_id:
            return False

        found = False
        for (state_side, _), state in state_by_key.items():
            if state_side != side:
                continue
            state.is_active_elf = state.elf_id == elf_id
            if state.is_active_elf:
                state.last_switch_turn = event.turn_number
                found = True
            elif state.last_switch_turn == event.turn_number:
                state.last_switch_turn = None
        if not found:
            return False
        if side == Side.SELF.value:
            battle.self_active_elf_id = elf_id
        else:
            battle.enemy_active_elf_id = elf_id
        return True

    def _apply_runtime_form_event(
        self,
        state_by_key: dict[tuple[str | None, str | None], BattleElfState],
        event: BattleEvent,
    ) -> bool:
        if event.event_type != BattleEventType.RUNTIME_FORM_CHANGE.value:
            return False
        payload = loads_json(event.payload_json, {}) or {}
        if not isinstance(payload, dict):
            return False
        side = event.actor_side or payload.get("side")
        original_elf_id = event.actor_elf_id or payload.get("original_elf_id")
        state = state_by_key.get((side, original_elf_id))
        if state is None:
            return False

        panel_after = payload.get("panel_after")
        if isinstance(panel_after, dict):
            state.panel_stats_json = dumps_json(panel_after)
        hp_after = payload.get("hp_after")
        if isinstance(hp_after, dict):
            current_hp_value = hp_after.get("current_hp_value")
            current_hp_percent = hp_after.get("current_hp_percent")
            state.current_hp_value = int(current_hp_value) if current_hp_value is not None else None
            state.current_hp_percent = (
                float(current_hp_percent) if current_hp_percent is not None else None
            )
        nature_id = payload.get("nature_id")
        if nature_id:
            state.nature_id = str(nature_id)
        individual = payload.get("individual_talent_distribution")
        if isinstance(individual, dict):
            state.individual_talent_distribution_json = dumps_json(individual)

        effective_elf_id = payload.get("effective_elf_id")
        if effective_elf_id and str(effective_elf_id) != state.elf_id:
            elf = self.db.get(ElfDefinition, str(effective_elf_id))
            state.runtime_form_elf_id = str(effective_elf_id)
            state.runtime_form_elf_name = elf.elf_name if elf is not None else None
            state.runtime_form_avatar = elf.avatar if elf is not None else None
            state.runtime_form_reason = payload.get("reason")
        else:
            state.runtime_form_elf_id = None
            state.runtime_form_elf_name = None
            state.runtime_form_avatar = None
            state.runtime_form_reason = None
        return True

    def _apply_resource_event(
        self,
        state_by_key: dict[tuple[str | None, str | None], BattleElfState],
        resource: ResourceChangeEvent,
    ) -> bool:
        state = state_by_key.get((resource.target_side, resource.target_elf_id))
        if state is None:
            return False
        if resource.resource_type == "hp":
            return self._apply_hp_resource_event(state, resource)
        if resource.resource_type == "energy":
            return self._apply_energy_resource_event(state, resource)
        return False

    def _apply_hp_resource_event(
        self,
        state: BattleElfState,
        resource: ResourceChangeEvent,
    ) -> bool:
        if resource.value_type == "percent":
            if resource.after_value is not None:
                state.current_hp_percent = self._clamp_percent(resource.after_value)
            elif resource.change_type in {"damage", "consume"}:
                state.current_hp_percent = self._clamp_percent(
                    (state.current_hp_percent or 0) - resource.value
                )
            elif resource.change_type in {"heal", "gain", "add"}:
                state.current_hp_percent = self._clamp_percent(
                    (state.current_hp_percent or 0) + resource.value
                )
            else:
                return False
        else:
            if resource.after_value is not None:
                state.current_hp_value = max(int(resource.after_value), 0)
            elif state.current_hp_value is not None:
                value = int(resource.value)
                if resource.change_type in {"damage", "consume"}:
                    state.current_hp_value = max(state.current_hp_value - value, 0)
                elif resource.change_type in {"heal", "gain", "add"}:
                    state.current_hp_value = state.current_hp_value + value
                else:
                    return False
            else:
                return False
            max_hp = self._max_hp_from_state(state)
            if max_hp is not None:
                state.current_hp_percent = self._clamp_percent(
                    state.current_hp_value / max_hp * 100
                )
        state.is_defeated = state.current_hp_value == 0 or state.current_hp_percent == 0
        return True

    @staticmethod
    def _apply_energy_resource_event(
        state: BattleElfState,
        resource: ResourceChangeEvent,
    ) -> bool:
        if resource.after_value is not None:
            state.energy = max(int(resource.after_value), 0)
            return True
        value = int(resource.value)
        if resource.change_type in {"consume", "spend", "remove"}:
            state.energy = max((state.energy or 0) - value, 0)
            return True
        if resource.change_type in {"gain", "heal", "add"}:
            state.energy = (state.energy or 0) + value
            return True
        return False

    def _apply_damage_fallback(
        self,
        state_by_key: dict[tuple[str | None, str | None], BattleElfState],
        damage_event: DamageEvent,
    ) -> bool:
        state = state_by_key.get((damage_event.defender_side, damage_event.defender_elf_id))
        if state is None or damage_event.hp_percent_after is None:
            return False
        state.current_hp_percent = self._clamp_percent(damage_event.hp_percent_after)
        state.is_defeated = state.current_hp_percent == 0
        return True

    def _apply_effect_change_event(
        self,
        effect_instances_by_id: dict[str, BattleEffectInstance],
        change: EffectChangeEvent,
    ) -> bool:
        if not change.effect_instance_id:
            return False
        instance = effect_instances_by_id.get(change.effect_instance_id)
        if instance is None and change.change_type in {
            "apply",
            "stack",
            "refresh",
            "switch_keep",
        }:
            instance = self._create_replayed_effect_instance(change)
            effect_instances_by_id[instance.instance_id] = instance
        if instance is None:
            return False

        if change.change_type in {"remove", "switch_clear", "dispel"}:
            instance.is_active = False
            instance.layers = max(int(change.layers_after or 0), 0)
            instance.last_updated_turn = change.turn_number
            return True

        instance.is_active = True
        if change.layers_after is not None:
            instance.layers = max(int(change.layers_after), 0)
        if change.duration_after is not None:
            instance.remaining_turns = change.duration_after
            instance.expire_turn = change.turn_number + change.duration_after
        instance.last_updated_turn = change.turn_number
        return True

    def _create_replayed_effect_instance(
        self,
        change: EffectChangeEvent,
    ) -> BattleEffectInstance:
        instance = BattleEffectInstance(
            instance_id=change.effect_instance_id,
            battle_id=change.battle_id,
            effect_id=change.effect_id,
            category=change.category or "unknown",
            owner_scope=change.owner_scope,
            owner_side=change.target_side,
            owner_elf_id=change.target_elf_id,
            owner_skill_slot_id=change.target_skill_slot_id,
            field_id="main" if change.owner_scope == "field" else None,
            source_side=None,
            source_elf_id=change.source_elf_id,
            source_skill_id=change.source_skill_id,
            source_event_id=change.battle_event_id,
            layers=max(int(change.layers_after or 1), 0),
            remaining_turns=change.duration_after,
            remaining_uses=None,
            is_active=not self._effect_change_removes_instance(change),
            applied_turn=change.turn_number,
            expire_turn=(
                change.turn_number + change.duration_after
                if change.duration_after is not None
                else None
            ),
            last_updated_turn=change.turn_number,
            recognition_source=change.source,
            recognition_confidence=change.recognition_confidence,
            manual_override=change.manual_override,
            notes=change.reason,
        )
        self.db.add(instance)
        return instance

    @staticmethod
    def _effect_change_removes_instance(change: EffectChangeEvent) -> bool:
        return change.change_type in {"remove", "switch_clear", "dispel"} or (
            change.layers_after is not None and change.layers_after <= 0
        )

    @staticmethod
    def _turn_number_after_event(event: BattleEvent, current_turn_number: int) -> int:
        payload = loads_json(event.payload_json, {}) or {}
        if isinstance(payload, dict):
            next_turn = payload.get("next_turn_number")
            if isinstance(next_turn, int):
                return next_turn
        return max(current_turn_number, event.turn_number)

    @staticmethod
    def _event_has_runtime_handler(event: BattleEvent) -> bool:
        return event.event_type in {
            BattleEventType.SWITCH_ELF.value,
            BattleEventType.TURN_END.value,
            BattleEventType.DAMAGE.value,
            BattleEventType.COMBO_DAMAGE.value,
            BattleEventType.HEAL.value,
            BattleEventType.ENERGY_CHANGE.value,
            BattleEventType.RUNTIME_FORM_CHANGE.value,
            "resource_change",
        }

    def _ordered_events(self, battle_id: str) -> list[BattleEvent]:
        return list(
            self.db.scalars(
                select(BattleEvent)
                .where(BattleEvent.battle_id == battle_id, BattleEvent.is_voided.is_(False))
                .order_by(BattleEvent.turn_number, BattleEvent.action_order, BattleEvent.created_at)
            ).all()
        )

    def _require_battle(self, battle_id: str) -> Battle:
        battle = self.db.get(Battle, battle_id)
        if battle is None or battle.deleted_at is not None:
            raise LookupError(f"战斗不存在：{battle_id}")
        return battle

    def _require_event(self, battle_id: str, event_id: str) -> BattleEvent:
        event = self.db.get(BattleEvent, event_id)
        if event is None or event.battle_id != battle_id:
            raise LookupError(f"事件不存在：{event_id}")
        return event

    @staticmethod
    def _max_hp_from_state(state: BattleElfState) -> int | None:
        panel = loads_json(state.panel_stats_json, {}) or {}
        if not isinstance(panel, dict):
            return None
        raw = panel.get("hp")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_percent(value: float) -> float:
        return max(min(round(float(value), 4), 100.0), 0.0)
