"""
统一状态效果服务模块。

本模块实现 BattleEffectSystem 的第一阶段能力：状态查询、手动施加、手动移除、
切换清除与切换保留记录。所有异常、天气、印记、属性修正都统一走同一套状态实例。
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import BattleEventType, EventSource, OwnerScope
from app.models.battle import Battle
from app.models.effect import BattleEffectInstance
from app.models.event import BattleEvent, EffectChangeEvent
from app.models.static import EffectDefinition
from app.schemas.effect import EffectApplyInput, EffectRemoveInput
from app.utils.json import dumps_json


class BattleEffectService:
    """
    统一状态效果业务服务。

    服务层负责把状态定义字段转换为运行时行为：
    - stack_rule 决定重复施加时如何处理层数；
    - clear_on_switch 决定切换精灵时清除还是保留；
    - owner_scope 决定状态挂载在精灵、队伍侧、战场或技能槽。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_active_effects(self, battle_id: str) -> list[BattleEffectInstance]:
        """获取战斗中所有生效的状态实例。"""
        stmt = select(BattleEffectInstance).where(
            BattleEffectInstance.battle_id == battle_id,
            BattleEffectInstance.is_active.is_(True),
        )
        return list(self.db.scalars(stmt).all())

    def get_definition(self, effect_id: str) -> EffectDefinition | None:
        """获取状态定义。"""
        return self.db.get(EffectDefinition, effect_id)

    def apply_effect(
        self,
        payload: EffectApplyInput,
        *,
        commit: bool = True,
    ) -> BattleEffectInstance:
        """
        施加或刷新状态。

        第一阶段支持最常见的三种重复施加策略：
        - add：在现有层数上增加，受 max_layers 限制；
        - refresh：刷新持续时间，不改变层数；
        - replace / 其他：直接覆盖为新层数和持续时间。
        """
        battle = self._require_battle(payload.battle_id)
        definition = self._require_definition(payload.effect_id)
        turn_number = payload.turn_number if payload.turn_number is not None else battle.turn_number
        existing = self._find_existing_instance(payload, definition)
        battle_event = self._create_battle_event(
            battle_id=payload.battle_id,
            turn_number=turn_number,
            event_type=BattleEventType.EFFECT_APPLY.value,
            actor_side=payload.source_side,
            actor_elf_id=payload.source_elf_id,
            target_side=payload.owner_side,
            target_elf_id=payload.owner_elf_id,
            skill_id=payload.source_skill_id,
            payload={"effect_id": definition.effect_id, "owner_scope": payload.owner_scope},
            notes=payload.notes,
        )

        if existing is not None:
            layers_before = existing.layers
            self._update_existing_instance(existing, definition, payload, turn_number)
            instance = existing
            layers_after = existing.layers
        else:
            layers_before = None
            layers = payload.layers if payload.layers is not None else definition.default_layers
            instance = BattleEffectInstance(
                instance_id=f"effect_instance_{uuid4().hex}",
                battle_id=payload.battle_id,
                effect_id=definition.effect_id,
                category=definition.category,
                owner_scope=payload.owner_scope,
                owner_side=payload.owner_side,
                owner_elf_id=payload.owner_elf_id,
                owner_skill_slot_id=payload.owner_skill_slot_id,
                field_id=payload.field_id,
                source_side=payload.source_side,
                source_elf_id=payload.source_elf_id,
                source_skill_id=payload.source_skill_id,
                source_event_id=battle_event.event_id,
                layers=layers,
                remaining_turns=payload.remaining_turns or definition.default_duration_turns,
                remaining_uses=payload.remaining_uses or definition.default_duration_uses,
                is_active=True,
                applied_turn=turn_number,
                expire_turn=self._calculate_expire_turn(turn_number, payload, definition),
                last_updated_turn=turn_number,
                recognition_source=EventSource.MANUAL_INPUT.value,
                recognition_confidence=1.0,
                manual_override=True,
                notes=payload.notes,
            )
            self.db.add(instance)
            layers_after = layers

        self.db.flush()
        self._create_effect_change_event(
            battle_id=payload.battle_id,
            battle_event_id=battle_event.event_id,
            turn_number=turn_number,
            change_type="apply",
            definition=definition,
            instance=instance,
            target_side=payload.owner_side,
            target_elf_id=payload.owner_elf_id,
            target_skill_slot_id=payload.owner_skill_slot_id,
            layers_before=layers_before,
            layers_after=layers_after,
            reason="manual_apply",
            source_skill_id=payload.source_skill_id,
            source_elf_id=payload.source_elf_id,
        )
        self._attach_snapshot_to_event(battle_event, payload.battle_id, turn_number)
        if commit:
            self.db.commit()
            self.db.refresh(instance)
        return instance

    def remove_effect(
        self,
        instance_id: str,
        payload: EffectRemoveInput,
        *,
        commit: bool = True,
    ) -> BattleEffectInstance:
        """手动移除状态实例，并记录 EffectChangeEvent。"""
        instance = self.db.get(BattleEffectInstance, instance_id)
        if instance is None:
            raise LookupError(f"状态实例不存在：{instance_id}")
        battle = self._require_battle(instance.battle_id)
        definition = self._require_definition(instance.effect_id)
        turn_number = payload.turn_number if payload.turn_number is not None else battle.turn_number
        event = self._create_battle_event(
            battle_id=instance.battle_id,
            turn_number=turn_number,
            event_type=BattleEventType.EFFECT_REMOVE.value,
            target_side=instance.owner_side,
            target_elf_id=instance.owner_elf_id,
            payload={"effect_instance_id": instance.instance_id, "reason": payload.reason},
            notes=payload.reason,
        )
        layers_before = instance.layers
        instance.is_active = False
        instance.last_updated_turn = turn_number
        self._create_effect_change_event(
            battle_id=instance.battle_id,
            battle_event_id=event.event_id,
            turn_number=turn_number,
            change_type="remove",
            definition=definition,
            instance=instance,
            target_side=instance.owner_side,
            target_elf_id=instance.owner_elf_id,
            target_skill_slot_id=instance.owner_skill_slot_id,
            layers_before=layers_before,
            layers_after=0,
            reason=payload.reason,
        )
        self._attach_snapshot_to_event(event, instance.battle_id, turn_number)
        if commit:
            self.db.commit()
            self.db.refresh(instance)
        return instance

    def switch_clear_effects(
        self,
        battle_id: str,
        side: str,
        leaving_elf_id: str,
        turn_number: int,
        battle_event_id: str,
    ) -> list[EffectChangeEvent]:
        """
        处理精灵切换时的状态清除/保留。

        只处理 owner_scope=elf 且挂在离场精灵身上的状态。队伍侧、战场、技能槽
        状态不会因精灵切换被这个流程清除。
        """
        instances = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle_id,
                BattleEffectInstance.owner_scope == OwnerScope.ELF.value,
                BattleEffectInstance.owner_side == side,
                BattleEffectInstance.owner_elf_id == leaving_elf_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()
        events: list[EffectChangeEvent] = []
        for instance in instances:
            definition = self._require_definition(instance.effect_id)
            if definition.clear_on_switch:
                change_type = "switch_clear"
                layers_after = 0
                instance.is_active = False
                instance.last_updated_turn = turn_number
            else:
                change_type = "switch_keep"
                layers_after = instance.layers
            events.append(
                self._create_effect_change_event(
                    battle_id=battle_id,
                    battle_event_id=battle_event_id,
                    turn_number=turn_number,
                    change_type=change_type,
                    definition=definition,
                    instance=instance,
                    target_side=side,
                    target_elf_id=leaving_elf_id,
                    target_skill_slot_id=instance.owner_skill_slot_id,
                    layers_before=instance.layers,
                    layers_after=layers_after,
                    reason="switch_elf",
                )
            )
        return events

    def _find_existing_instance(
        self,
        payload: EffectApplyInput,
        definition: EffectDefinition,
    ) -> BattleEffectInstance | None:
        """查找同一状态在同一挂载目标上的现有生效实例。"""
        stmt = select(BattleEffectInstance).where(
            BattleEffectInstance.battle_id == payload.battle_id,
            BattleEffectInstance.effect_id == definition.effect_id,
            BattleEffectInstance.owner_scope == payload.owner_scope,
            BattleEffectInstance.owner_side == payload.owner_side,
            BattleEffectInstance.owner_elf_id == payload.owner_elf_id,
            BattleEffectInstance.owner_skill_slot_id == payload.owner_skill_slot_id,
            BattleEffectInstance.field_id == payload.field_id,
            BattleEffectInstance.is_active.is_(True),
        )
        return self.db.scalars(stmt).first()

    def _update_existing_instance(
        self,
        instance: BattleEffectInstance,
        definition: EffectDefinition,
        payload: EffectApplyInput,
        turn_number: int,
    ) -> None:
        """根据 stack_rule 更新已有状态实例。"""
        incoming_layers = (
            payload.layers if payload.layers is not None else definition.default_layers
        )
        if definition.stack_rule == "add":
            next_layers = instance.layers + incoming_layers
            if definition.max_layers is not None:
                next_layers = min(next_layers, definition.max_layers)
            instance.layers = next_layers
        elif definition.stack_rule == "refresh":
            # refresh 只刷新持续时间，层数保留不变。
            pass
        else:
            instance.layers = incoming_layers
        instance.remaining_turns = payload.remaining_turns or definition.default_duration_turns
        instance.remaining_uses = payload.remaining_uses or definition.default_duration_uses
        instance.expire_turn = self._calculate_expire_turn(turn_number, payload, definition)
        instance.last_updated_turn = turn_number
        instance.notes = payload.notes

    def _create_battle_event(
        self,
        *,
        battle_id: str,
        turn_number: int,
        event_type: str,
        actor_side: str | None = None,
        actor_elf_id: str | None = None,
        target_side: str | None = None,
        target_elf_id: str | None = None,
        skill_id: str | None = None,
        payload: dict | None = None,
        notes: str | None = None,
    ) -> BattleEvent:
        """创建与状态变化关联的通用事件。"""
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=turn_number,
            event_type=event_type,
            actor_side=actor_side,
            actor_elf_id=actor_elf_id,
            target_side=target_side,
            target_elf_id=target_elf_id,
            skill_id=skill_id,
            skill_confirmed=skill_id is not None,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
            payload_json=dumps_json(payload or {}),
            notes=notes,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def _create_effect_change_event(
        self,
        *,
        battle_id: str,
        battle_event_id: str,
        turn_number: int,
        change_type: str,
        definition: EffectDefinition,
        instance: BattleEffectInstance,
        target_side: str | None,
        target_elf_id: str | None,
        target_skill_slot_id: str | None,
        layers_before: int | None,
        layers_after: int | None,
        reason: str | None,
        source_skill_id: str | None = None,
        source_elf_id: str | None = None,
    ) -> EffectChangeEvent:
        """创建状态变化详情事件。"""
        event = EffectChangeEvent(
            event_id=f"effect_change_{uuid4().hex}",
            battle_id=battle_id,
            battle_event_id=battle_event_id,
            turn_number=turn_number,
            change_type=change_type,
            effect_instance_id=instance.instance_id,
            effect_id=definition.effect_id,
            effect_name=definition.effect_name,
            category=definition.category,
            target_side=target_side,
            target_elf_id=target_elf_id,
            target_skill_slot_id=target_skill_slot_id,
            owner_scope=instance.owner_scope,
            layers_before=layers_before,
            layers_after=layers_after,
            duration_before=None,
            duration_after=instance.remaining_turns,
            source_skill_id=source_skill_id,
            source_elf_id=source_elf_id,
            reason=reason,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def _attach_snapshot_to_event(
        self,
        battle_event: BattleEvent,
        battle_id: str,
        turn_number: int,
    ) -> None:
        """
        为状态变化事件创建并绑定快照。

        状态变化本身会改变后续计算上下文，所以施加和移除状态后立即保存快照。
        这里使用局部导入避免 SnapshotService 与 BattleEffectService 的循环导入。
        """
        from app.services.snapshot_service import SnapshotService

        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle_id,
            turn_number,
            source_event_id=battle_event.event_id,
            commit=False,
        )
        battle_event.snapshot_id = snapshot.snapshot_id


    @staticmethod
    def _calculate_expire_turn(
        turn_number: int,
        payload: EffectApplyInput,
        definition: EffectDefinition,
    ) -> int | None:
        """根据剩余回合计算过期回合；未知持续时间返回 None。"""
        remaining_turns = payload.remaining_turns or definition.default_duration_turns
        if remaining_turns is None:
            return None
        return turn_number + remaining_turns

    def _require_battle(self, battle_id: str) -> Battle:
        """读取战斗并校验存在。"""
        battle = self.db.get(Battle, battle_id)
        if battle is None or battle.deleted_at is not None:
            raise LookupError(f"战斗不存在：{battle_id}")
        return battle

    def _require_definition(self, effect_id: str) -> EffectDefinition:
        """读取状态定义并校验存在。"""
        definition = self.db.get(EffectDefinition, effect_id)
        if definition is None or definition.deleted_at is not None:
            raise LookupError(f"状态定义不存在：{effect_id}")
        return definition
