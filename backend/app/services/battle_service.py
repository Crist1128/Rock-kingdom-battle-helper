"""
战斗服务模块。

本模块提供战斗生命周期和手动输入 MVP 的核心业务流程：
创建战斗、录入阵容、初始化敌方面板估计、切换精灵、记录通用事件和查询状态。
"""

from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats
from app.calculation.hit_rule_resolver import HitRuleResolver
from app.calculation.modifier_resolver import ModifierResolver
from app.calculation.rule_resolver import RuleResolver
from app.calculation.stat_calculator import (
    BaseTalentBlock,
    IndividualTalentDistribution,
    NatureRule,
    StatCalculator,
)
from app.core.default_skills import (
    DEFAULT_COMMON_SKILL_ID,
    DEFAULT_INITIAL_ENERGY,
    append_default_common_skill_ids,
)
from app.core.element_aliases import element_type_matches
from app.core.enums import BattleEventType, BattlePhase, EventSource, Side, StatKey
from app.models.battle import Battle, BattleElfState, BattleSkillSlot
from app.models.effect import BattleEffectInstance
from app.models.estimate import EnemyPanelEstimate, EnemyPanelEstimateEvidence
from app.models.event import BattleEvent, DamageEvent, EffectChangeEvent, ResourceChangeEvent
from app.models.static import (
    EffectDefinition,
    ElfDefinition,
    ElfLearnableSkill,
    NatureDefinition,
    PlayerElfBuild,
    PlayerElfBuildSkill,
    SkillDefinition,
)
from app.schemas.battle import (
    BattleCreate,
    BattleStateOut,
    EndTurnInput,
    EndTurnResult,
    LineupInput,
    LineupOut,
    RuntimeFormChangeInput,
    SkillSlotRuntimeUpdateInput,
    SwitchElfInput,
)
from app.schemas.event import (
    BattleEventCorrectInput,
    BattleEventCreate,
    BattleEventVoidInput,
    BattleReplayResult,
    BattleTimelineEventOut,
    BattleTimelineTurnOut,
)
from app.services.effect_operation_executor import EffectOperationExecutor
from app.services.effect_service import BattleEffectService
from app.services.estimate_service import EstimateService
from app.services.event_replay_service import EventReplayService
from app.services.snapshot_service import SnapshotService
from app.services.turn_settlement_service import TurnSettlementService
from app.utils.json import dumps_json, loads_json, model_to_dict


class BattleService:
    """
    战斗业务服务。

    服务层承担事务和跨表协调职责，API 层只负责 HTTP 参数与错误码转换。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_battle(self, payload: BattleCreate) -> Battle:
        """创建一场准备阶段的新战斗。"""
        battle = Battle(
            battle_id=f"battle_{uuid4().hex}",
            battle_name=payload.battle_name,
            notes=payload.notes,
            phase=BattlePhase.PREPARATION.value,
            turn_number=0,
        )
        self.db.add(battle)
        self.db.commit()
        self.db.refresh(battle)
        return battle

    def list_battles(
        self,
        *,
        phase: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Battle]:
        """列出战斗记录，默认隐藏已归档战斗。

        首页的“移除最近战斗”采用 archive 语义：保留事件、实时估计和快照，
        但从普通最近战斗列表中隐藏。因此未显式筛选阶段时默认排除
        ``phase = archived``。如果前端或管理页需要查看归档记录，可传
        ``include_archived=true``，或直接传 ``phase=archived``。
        """
        stmt = select(Battle).where(Battle.deleted_at.is_(None))
        if phase is not None:
            stmt = stmt.where(Battle.phase == phase)
        elif not include_archived:
            stmt = stmt.where(Battle.phase != BattlePhase.ARCHIVED.value)
        stmt = (
            stmt.order_by(Battle.updated_at.desc(), Battle.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())

    def finish_battle(self, battle_id: str) -> Battle:
        """将战斗标记为 finished。"""
        battle = self.require_battle(battle_id)
        if battle.phase == BattlePhase.ARCHIVED.value:
            raise ValueError("已归档战斗不能重新结束")
        battle.phase = BattlePhase.FINISHED.value
        self.db.commit()
        self.db.refresh(battle)
        return battle

    def archive_battle(self, battle_id: str) -> Battle:
        """将战斗标记为 archived，保留历史数据不删除。"""
        battle = self.require_battle(battle_id)
        battle.phase = BattlePhase.ARCHIVED.value
        self.db.commit()
        self.db.refresh(battle)
        return battle

    def end_turn(self, battle_id: str, payload: EndTurnInput) -> EndTurnResult:
        """结束当前回合，记录事件、创建快照并推进回合号。

        阶段 C 起会在推进回合前调用 TurnSettlementService，生成 P0 回合末状态
        结算事件；上下文不足的状态只返回 skipped/partial 摘要，不改写状态。
        """
        battle = self.require_battle(battle_id)
        if battle.phase != BattlePhase.BATTLE.value:
            raise ValueError("只有 battle 阶段可以结束回合")

        ended_turn_number = battle.turn_number
        next_turn_number = ended_turn_number + 1
        settlement_events = TurnSettlementService(self.db).settle_end_turn(
            battle=battle,
            turn_number=ended_turn_number,
        )
        end_turn_skill_runtime_results = self._apply_end_turn_skill_runtime_hooks(
            battle=battle,
            turn_number=ended_turn_number,
        )
        settlement_status = self._settlement_status(settlement_events)
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=ended_turn_number,
            event_type=BattleEventType.TURN_END.value,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
            payload_json=dumps_json(
                {
                    "ended_turn_number": ended_turn_number,
                    "next_turn_number": next_turn_number,
                    "settlement_status": settlement_status,
                    "settlement_events": settlement_events,
                    "end_turn_skill_runtime_results": end_turn_skill_runtime_results,
                }
            ),
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.flush()

        battle.turn_number = next_turn_number
        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle_id,
            next_turn_number,
            source_event_id=event.event_id,
            commit=False,
        )
        event.snapshot_id = snapshot.snapshot_id
        self.db.commit()
        self.db.refresh(battle)
        self.db.refresh(event)
        return EndTurnResult(
            battle=battle,
            battle_event=event,
            ended_turn_number=ended_turn_number,
            next_turn_number=next_turn_number,
            snapshot_id=snapshot.snapshot_id,
            settlement_status=settlement_status,
            settlement_events=settlement_events,
        )

    def setup_lineup(self, battle_id: str, payload: LineupInput) -> LineupOut:
        """
        录入双方阵容并初始化敌方面板估计档案。

        处理步骤：
        1. 清理该战斗旧的运行时数据和估计档案；
        2. 己方从 PlayerElfBuild 复制确定面板属性与技能槽；
        3. 敌方只根据 elf_id 创建未知面板运行时状态；
        4. 为每只敌方精灵创建实时面板估计档案；
        5. 生成准备阶段快照。
        """
        battle = self.require_battle(battle_id)
        if battle.phase != BattlePhase.PREPARATION.value:
            raise ValueError(
                "只有 preparation 阶段允许直接录入或重录阵容；"
                "战斗开始后的修正应走事件纠错流程"
            )

        self._validate_lineup(payload)
        self._clear_runtime_data(battle_id)

        created_count = 0
        self_active_elf_id: str | None = None
        enemy_active_elf_id: str | None = None

        for item in payload.elves:
            elf = self._require_elf(item.elf_id)
            if item.side == Side.SELF.value:
                state = self._create_self_elf_state(battle_id, item, elf)
            elif item.side == Side.ENEMY.value:
                state = self._create_enemy_elf_state(battle_id, item, elf)
            else:
                raise ValueError(f"未知阵营：{item.side}")

            self.db.add(state)
            if item.side == Side.ENEMY.value:
                EstimateService(self.db).create_for_enemy_state(
                    battle_id,
                    state,
                    replace_existing=True,
                    commit=False,
                )
            created_count += 1
            if item.is_active_elf and item.side == Side.SELF.value:
                self_active_elf_id = item.elf_id
            if item.is_active_elf and item.side == Side.ENEMY.value:
                enemy_active_elf_id = item.elf_id

        battle.self_active_elf_id = self_active_elf_id
        battle.enemy_active_elf_id = enemy_active_elf_id
        SnapshotService(self.db).create_effect_snapshot(battle_id, 0, commit=False)
        self.db.commit()

        return LineupOut(
            battle_id=battle_id,
            created_elf_state_count=created_count,
            self_active_elf_id=self_active_elf_id,
            enemy_active_elf_id=enemy_active_elf_id,
        )

    def start_battle(
        self,
        battle_id: str,
        self_active_elf_id: str | None = None,
        enemy_active_elf_id: str | None = None,
    ) -> Battle:
        """
        从准备阶段进入战斗阶段。

        如果请求中传入首发 ID，会同步更新 BattleElfState.is_active_elf。否则使用
        阵容录入时已经标记的首发。
        """
        battle = self.require_battle(battle_id)
        if self_active_elf_id is not None:
            self._set_active_elf(battle_id, Side.SELF.value, self_active_elf_id, battle.turn_number)
            battle.self_active_elf_id = self_active_elf_id
        if enemy_active_elf_id is not None:
            self._set_active_elf(
                battle_id,
                Side.ENEMY.value,
                enemy_active_elf_id,
                battle.turn_number,
            )
            battle.enemy_active_elf_id = enemy_active_elf_id

        if battle.self_active_elf_id is None or battle.enemy_active_elf_id is None:
            raise ValueError("进入战斗阶段前必须指定双方首发精灵")

        battle.phase = BattlePhase.BATTLE.value
        SnapshotService(self.db).create_effect_snapshot(battle_id, battle.turn_number, commit=False)
        self.db.commit()
        self.db.refresh(battle)
        return battle

    def switch_elf(self, battle_id: str, payload: SwitchElfInput) -> Battle:
        """
        切换当前上场精灵，并执行 clear_on_switch 规则。

        切换会创建一个 switch_elf 通用事件。离场精灵身上的状态按状态定义决定
        switch_clear 或 switch_keep，并写入 EffectChangeEvent。
        """
        battle = self.require_battle(battle_id)
        turn_number = payload.turn_number if payload.turn_number is not None else battle.turn_number
        old_elf_id = (
            battle.self_active_elf_id
            if payload.side == Side.SELF.value
            else battle.enemy_active_elf_id
        )
        self._set_active_elf(battle_id, payload.side, payload.elf_id, turn_number)

        if payload.side == Side.SELF.value:
            battle.self_active_elf_id = payload.elf_id
        elif payload.side == Side.ENEMY.value:
            battle.enemy_active_elf_id = payload.elf_id
        else:
            raise ValueError(f"未知阵营：{payload.side}")

        event_payload: dict[str, Any] = {"from_elf_id": old_elf_id, "to_elf_id": payload.elf_id}
        if old_elf_id == payload.elf_id:
            event_payload["switch_mode"] = "return_to_field"
        rule_conflicts = self._switch_rule_conflicts(
            battle_id=battle_id,
            side=payload.side,
            leaving_elf_id=old_elf_id,
        )
        if rule_conflicts:
            event_payload["rule_conflicts"] = rule_conflicts
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=turn_number,
            event_type=BattleEventType.SWITCH_ELF.value,
            actor_side=payload.side,
            actor_elf_id=old_elf_id,
            target_side=payload.side,
            target_elf_id=payload.elf_id,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
            payload_json=dumps_json(event_payload),
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.flush()

        pending_switch_results = self._apply_pending_next_switch_in_effects(
            battle_event=event,
            side=payload.side,
            old_elf_id=old_elf_id,
            new_elf_id=payload.elf_id,
        )
        if pending_switch_results:
            event_payload["pending_next_switch_in_results"] = pending_switch_results
            event.payload_json = dumps_json(event_payload)
        switch_out_skill_runtime_results = self._apply_switch_out_skill_runtime_hooks(
            battle_event=event,
            side=payload.side,
            old_elf_id=old_elf_id,
        )
        if switch_out_skill_runtime_results:
            event_payload["switch_out_skill_runtime_results"] = switch_out_skill_runtime_results
            event.payload_json = dumps_json(event_payload)

        if old_elf_id is not None:
            BattleEffectService(self.db).switch_clear_effects(
                battle_id=battle_id,
                side=payload.side,
                leaving_elf_id=old_elf_id,
                turn_number=turn_number,
                battle_event_id=event.event_id,
            )
        switch_in_settlement_events = TurnSettlementService(self.db).settle_switch_in(
            battle=battle,
            turn_number=turn_number,
            side=payload.side,
            elf_id=payload.elf_id,
        )
        if switch_in_settlement_events:
            event_payload["switch_in_settlement_events"] = switch_in_settlement_events
            event.payload_json = dumps_json(event_payload)

        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle_id,
            turn_number,
            source_event_id=event.event_id,
            commit=False,
        )
        event.snapshot_id = snapshot.snapshot_id
        self.db.commit()
        self.db.refresh(battle)
        return battle

    def _apply_pending_next_switch_in_effects(
        self,
        *,
        battle_event: BattleEvent,
        side: str,
        old_elf_id: str | None,
        new_elf_id: str,
    ) -> list[dict[str, Any]]:
        """执行由上一技能登记的“下一只入场精灵”效果。"""
        if old_elf_id is None:
            return []
        source_events = self.db.scalars(
            select(BattleEvent)
            .where(
                BattleEvent.battle_id == battle_event.battle_id,
                BattleEvent.event_type == BattleEventType.SKILL_USE.value,
                BattleEvent.actor_side == side,
                BattleEvent.actor_elf_id == old_elf_id,
                BattleEvent.is_voided.is_(False),
            )
            .order_by(
                BattleEvent.turn_number.desc(),
                BattleEvent.action_order.desc().nullslast(),
                BattleEvent.created_at.desc(),
            )
        ).all()
        results: list[dict[str, Any]] = []
        for source_event in source_events:
            payload = loads_json(source_event.payload_json, {})
            if not isinstance(payload, dict):
                continue
            pending = payload.get("pending_next_switch_in")
            if not isinstance(pending, list):
                continue
            changed_payload = False
            for item in pending:
                if not isinstance(item, dict) or item.get("consumed_by_switch_event_id"):
                    continue
                if item.get("source_side") not in {None, side}:
                    continue
                if item.get("source_elf_id") not in {None, old_elf_id}:
                    continue
                effect_type = item.get("effect_type")
                if effect_type == "inherit_positive_elf_effects":
                    result = self._inherit_positive_elf_effects_on_switch(
                        battle_event=battle_event,
                        side=side,
                        old_elf_id=old_elf_id,
                        new_elf_id=new_elf_id,
                    )
                elif effect_type == "resource_change":
                    result = self._apply_switch_in_resource_change(
                        battle_event=battle_event,
                        side=side,
                        new_elf_id=new_elf_id,
                        pending=item,
                    )
                elif effect_type == "force_switch":
                    result = {
                        "status": "recorded",
                        "effect_type": "force_switch",
                        "switch_mode": item.get("switch_mode"),
                    }
                else:
                    result = {"status": "skipped", "reason": "unsupported_pending_effect"}
                result["source_event_id"] = source_event.event_id
                results.append(result)
                item["consumed_by_switch_event_id"] = battle_event.event_id
                changed_payload = True
            if changed_payload:
                source_event.payload_json = dumps_json(payload)
        return results

    def _inherit_positive_elf_effects_on_switch(
        self,
        *,
        battle_event: BattleEvent,
        side: str,
        old_elf_id: str,
        new_elf_id: str,
    ) -> dict[str, Any]:
        """击鼓传花：把离场精灵的正面 elf 状态复制给入场精灵。"""
        if old_elf_id == new_elf_id:
            return {
                "status": "skipped",
                "effect_type": "inherit_positive_elf_effects",
                "reason": "same_elf_return_to_field",
            }
        definitions = {
            item.effect_id: item
            for item in self.db.scalars(
                select(EffectDefinition).where(EffectDefinition.deleted_at.is_(None))
            ).all()
        }
        inherited: list[dict[str, Any]] = []
        instances = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle_event.battle_id,
                BattleEffectInstance.owner_scope == "elf",
                BattleEffectInstance.owner_side == side,
                BattleEffectInstance.owner_elf_id == old_elf_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()
        for source_instance in instances:
            definition = definitions.get(source_instance.effect_id)
            if definition is None or definition.polarity != "positive":
                continue
            layers = max(int(source_instance.layers or 0), 0)
            if layers <= 0:
                continue
            target_instance = self.db.scalars(
                select(BattleEffectInstance).where(
                    BattleEffectInstance.battle_id == battle_event.battle_id,
                    BattleEffectInstance.effect_id == source_instance.effect_id,
                    BattleEffectInstance.owner_scope == "elf",
                    BattleEffectInstance.owner_side == side,
                    BattleEffectInstance.owner_elf_id == new_elf_id,
                    BattleEffectInstance.is_active.is_(True),
                )
            ).first()
            if target_instance is None:
                target_instance = BattleEffectInstance(
                    instance_id=f"effect_instance_{uuid4().hex}",
                    battle_id=battle_event.battle_id,
                    effect_id=source_instance.effect_id,
                    category=source_instance.category,
                    owner_scope="elf",
                    owner_side=side,
                    owner_elf_id=new_elf_id,
                    source_side=source_instance.source_side,
                    source_elf_id=source_instance.source_elf_id,
                    source_skill_id=source_instance.source_skill_id,
                    source_event_id=battle_event.event_id,
                    layers=layers,
                    remaining_turns=source_instance.remaining_turns,
                    remaining_uses=source_instance.remaining_uses,
                    is_active=True,
                    applied_turn=battle_event.turn_number,
                    expire_turn=source_instance.expire_turn,
                    last_updated_turn=battle_event.turn_number,
                    recognition_source=EventSource.SYSTEM_CALCULATED.value,
                    recognition_confidence=1.0,
                    manual_override=False,
                    notes="pending_switch_inherit_positive_effects",
                )
                self.db.add(target_instance)
                layers_before = None
                change_type = "inherit"
            else:
                layers_before = target_instance.layers
                next_layers = target_instance.layers + layers
                if definition.max_layers is not None:
                    next_layers = min(next_layers, definition.max_layers)
                target_instance.layers = next_layers
                target_instance.last_updated_turn = battle_event.turn_number
                change_type = "stack"
            self.db.flush()
            self.db.add(
                EffectChangeEvent(
                    event_id=f"effect_change_{uuid4().hex}",
                    battle_id=battle_event.battle_id,
                    battle_event_id=battle_event.event_id,
                    turn_number=battle_event.turn_number,
                    change_type=change_type,
                    effect_instance_id=target_instance.instance_id,
                    effect_id=definition.effect_id,
                    effect_name=definition.effect_name,
                    category=definition.category,
                    target_side=side,
                    target_elf_id=new_elf_id,
                    owner_scope="elf",
                    layers_before=layers_before,
                    layers_after=target_instance.layers,
                    duration_before=None,
                    duration_after=target_instance.remaining_turns,
                    source_skill_id=battle_event.skill_id,
                    source_elf_id=old_elf_id,
                    condition_branch="pending_next_switch_in",
                    reason="switch_inherit_positive_effects",
                    source=EventSource.SYSTEM_CALCULATED.value,
                    recognition_confidence=1.0,
                    manual_override=False,
                )
            )
            inherited.append(
                {
                    "effect_id": definition.effect_id,
                    "effect_name": definition.effect_name,
                    "source_instance_id": source_instance.instance_id,
                    "target_instance_id": target_instance.instance_id,
                    "layers": layers,
                    "layers_after": target_instance.layers,
                }
            )
        return {
            "status": "executed" if inherited else "skipped",
            "effect_type": "inherit_positive_elf_effects",
            "reason": None if inherited else "no_positive_elf_effects",
            "inherited": inherited,
        }

    def _apply_switch_in_resource_change(
        self,
        *,
        battle_event: BattleEvent,
        side: str,
        new_elf_id: str,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        """切换入场资源变化，目前用于加大功率给新入场精灵回能。"""
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle_event.battle_id,
                BattleElfState.side == side,
                BattleElfState.elf_id == new_elf_id,
            )
        ).first()
        if state is None:
            return {
                "status": "skipped",
                "effect_type": "resource_change",
                "reason": "state_missing",
            }
        resource_type = str(pending.get("resource_type") or "energy")
        change_type = str(pending.get("change_type") or "gain")
        value = int(pending.get("value") or 0)
        max_value = pending.get("max_value")
        try:
            max_value_int = int(max_value) if max_value is not None else None
        except (TypeError, ValueError):
            max_value_int = None
        if resource_type != "energy":
            return {
                "status": "skipped",
                "effect_type": "resource_change",
                "reason": "unsupported_resource_type",
            }
        before = state.energy
        if before is None:
            return {
                "status": "skipped",
                "effect_type": "resource_change",
                "reason": "energy_missing",
            }
        if change_type in {"gain", "heal", "recover"}:
            state.energy = int(before + value)
        elif change_type in {"consume", "lose", "damage"}:
            state.energy = max(int(before - value), 0)
        elif change_type == "manual_set":
            state.energy = max(value, 0)
        if max_value_int is not None:
            state.energy = min(state.energy, max_value_int)
        event = ResourceChangeEvent(
            event_id=f"resource_event_{uuid4().hex}",
            battle_id=battle_event.battle_id,
            battle_event_id=battle_event.event_id,
            resource_type=resource_type,
            change_type=change_type,
            source_side=battle_event.actor_side,
            source_elf_id=battle_event.actor_elf_id,
            target_side=side,
            target_elf_id=new_elf_id,
            value_type=str(pending.get("value_type") or "value"),
            value=float(value),
            before_value=float(before),
            after_value=float(state.energy),
            confidence=1.0,
            manual_override=False,
        )
        self.db.add(event)
        self.db.flush()
        return {
            "status": "executed",
            "effect_type": "resource_change",
            "resource_type": resource_type,
            "change_type": change_type,
            "target_side": side,
            "target_elf_id": new_elf_id,
            "value": value,
            "before_value": before,
            "after_value": state.energy,
            "resource_event_id": event.event_id,
        }

    def _apply_switch_out_skill_runtime_hooks(
        self,
        *,
        battle_event: BattleEvent,
        side: str,
        old_elf_id: str | None,
    ) -> list[dict[str, Any]]:
        """处理精灵离场时的技能槽持久修正。"""
        if old_elf_id is None:
            return []
        effect_id = "effect_skill_slot_use_count_up_persistent"
        definition = self.db.get(EffectDefinition, effect_id)
        if definition is None or definition.deleted_at is not None:
            return []
        slots = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == battle_event.battle_id,
                BattleSkillSlot.side == side,
                BattleSkillSlot.elf_id == old_elf_id,
            )
        ).all()
        results: list[dict[str, Any]] = []
        for slot in slots:
            skill = self.db.get(SkillDefinition, slot.skill_id)
            if skill is None or skill.deleted_at is not None:
                continue
            rule = loads_json(skill.damage_rule_json, {})
            manual_review = rule.get("manual_review") if isinstance(rule, dict) else None
            hooks = manual_review.get("future_hooks") if isinstance(manual_review, dict) else None
            if not isinstance(hooks, list):
                continue
            for hook in hooks:
                if not isinstance(hook, dict):
                    continue
                if hook.get("status") != "executable":
                    continue
                if hook.get("trigger") != "switch_out":
                    continue
                if hook.get("hook_type") != "persistent_skill_use_count_modifier":
                    continue
                delta = int(hook.get("use_count_delta") or 0)
                if delta <= 0:
                    continue
                existing = self.db.scalars(
                    select(BattleEffectInstance).where(
                        BattleEffectInstance.battle_id == battle_event.battle_id,
                        BattleEffectInstance.effect_id == effect_id,
                        BattleEffectInstance.owner_scope == "skill_slot",
                        BattleEffectInstance.owner_skill_slot_id == slot.slot_id,
                        BattleEffectInstance.is_active.is_(True),
                    )
                ).first()
                if existing is None:
                    instance = BattleEffectInstance(
                        instance_id=f"effect_instance_{uuid4().hex}",
                        battle_id=battle_event.battle_id,
                        effect_id=effect_id,
                        category=definition.category,
                        owner_scope="skill_slot",
                        owner_side=side,
                        owner_elf_id=old_elf_id,
                        owner_skill_slot_id=slot.slot_id,
                        source_side=side,
                        source_elf_id=old_elf_id,
                        source_skill_id=skill.skill_id,
                        source_event_id=battle_event.event_id,
                        layers=delta,
                        remaining_turns=None,
                        remaining_uses=None,
                        is_active=True,
                        applied_turn=battle_event.turn_number,
                        expire_turn=None,
                        last_updated_turn=battle_event.turn_number,
                        recognition_source=EventSource.SYSTEM_CALCULATED.value,
                        recognition_confidence=1.0,
                        manual_override=False,
                        notes="switch_out_persistent_skill_use_count_modifier",
                    )
                    self.db.add(instance)
                    layers_before = None
                    change_type = "apply"
                else:
                    instance = existing
                    layers_before = existing.layers
                    instance.layers += delta
                    instance.last_updated_turn = battle_event.turn_number
                    change_type = "stack"
                self.db.flush()
                self.db.add(
                    EffectChangeEvent(
                        event_id=f"effect_change_{uuid4().hex}",
                        battle_id=battle_event.battle_id,
                        battle_event_id=battle_event.event_id,
                        turn_number=battle_event.turn_number,
                        change_type=change_type,
                        effect_instance_id=instance.instance_id,
                        effect_id=effect_id,
                        effect_name=definition.effect_name,
                        category=definition.category,
                        target_side=side,
                        target_elf_id=old_elf_id,
                        target_skill_slot_id=slot.slot_id,
                        owner_scope="skill_slot",
                        layers_before=layers_before,
                        layers_after=instance.layers,
                        duration_before=None,
                        duration_after=None,
                        source_skill_id=skill.skill_id,
                        source_elf_id=old_elf_id,
                        condition_branch="switch_out",
                        reason="switch_out_skill_use_count_modifier",
                        source=EventSource.SYSTEM_CALCULATED.value,
                        recognition_confidence=1.0,
                        manual_override=False,
                    )
                )
                results.append(
                    {
                        "status": "executed",
                        "hook_type": "persistent_skill_use_count_modifier",
                        "trigger": "switch_out",
                        "skill_id": skill.skill_id,
                        "slot_id": slot.slot_id,
                        "effect_id": effect_id,
                        "use_count_delta": delta,
                        "layers_before": layers_before,
                        "layers_after": instance.layers,
                    }
                )
        return results

    def change_runtime_form(
        self,
        battle_id: str,
        state_id: str,
        payload: RuntimeFormChangeInput,
    ) -> BattleStateOut:
        """手动调整运行时有效形态。

        该操作用于退化、萌化面板回退等“当前按另一个种族值结算”的场景：保留原始
        BattleElfState.elf_id、性格和个体培养，只替换运行时有效形态并重算面板；
        不调用 switch_elf，因此不会触发切换清除、返场、入场结算或首回合机制。
        """
        battle = self.require_battle(battle_id)
        if payload.hp_policy != "keep_percent":
            raise ValueError("运行时形态调整当前仅支持 hp_policy=keep_percent")
        state = self.db.get(BattleElfState, state_id)
        if state is None or state.battle_id != battle_id:
            raise LookupError(f"战斗精灵状态不存在：{state_id}")

        target_elf_id = payload.effective_elf_id or state.elf_id
        target_elf = self._require_elf(target_elf_id)
        previous_effective_elf_id = self._effective_elf_id_for_state(state)
        panel_before = loads_json(state.panel_stats_json, {})
        hp_before = {
            "current_hp_value": state.current_hp_value,
            "current_hp_percent": state.current_hp_percent,
        }

        nature, individual, source = self._runtime_form_build_inputs(state)
        panel_after = StatCalculator.calculate_panel_stats(
            base=self._elf_to_base_talent_block(target_elf),
            individual=individual,
            nature=nature,
        )
        state.panel_stats_json = dumps_json(panel_after)
        if state.current_hp_percent is not None:
            percent = max(0.0, min(float(state.current_hp_percent), 100.0))
            state.current_hp_value = int(panel_after.hp * percent / 100)

        if payload.effective_elf_id is None or payload.effective_elf_id == state.elf_id:
            state.runtime_form_elf_id = None
            state.runtime_form_elf_name = None
            state.runtime_form_avatar = None
            state.runtime_form_reason = None
        else:
            state.runtime_form_elf_id = target_elf.elf_id
            state.runtime_form_elf_name = target_elf.elf_name
            state.runtime_form_avatar = target_elf.avatar
            state.runtime_form_reason = payload.reason

        event_payload = {
            "state_id": state.state_id,
            "side": state.side,
            "original_elf_id": state.elf_id,
            "previous_effective_elf_id": previous_effective_elf_id,
            "effective_elf_id": self._effective_elf_id_for_state(state),
            "hp_policy": payload.hp_policy,
            "build_input_source": source,
            "nature_id": state.nature_id,
            "individual_talent_distribution": loads_json(
                state.individual_talent_distribution_json,
                None,
            ),
            "panel_before": panel_before,
            "panel_after": panel_after.model_dump(),
            "hp_before": hp_before,
            "hp_after": {
                "current_hp_value": state.current_hp_value,
                "current_hp_percent": state.current_hp_percent,
            },
            "reason": payload.reason,
        }
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=battle.turn_number,
            event_type=BattleEventType.RUNTIME_FORM_CHANGE.value,
            actor_side=state.side,
            actor_elf_id=state.elf_id,
            target_side=state.side,
            target_elf_id=state.elf_id,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
            payload_json=dumps_json(event_payload),
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.flush()
        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle_id,
            battle.turn_number,
            source_event_id=event.event_id,
            commit=False,
        )
        event.snapshot_id = snapshot.snapshot_id
        self.db.commit()
        self.db.refresh(battle)
        return self.get_state(battle)

    def update_skill_slot_runtime(
        self,
        battle_id: str,
        slot_id: str,
        payload: SkillSlotRuntimeUpdateInput,
    ) -> BattleStateOut:
        """手动调整技能槽运行时值。

        `BattleSkillSlot.current_power` 已被 RuleResolver 和工作台预览优先读取，
        因此这里写入后，后续理论伤害、伤害事件计算都会优先使用该手动威力。
        该修改同时落一条事件，便于时间线审计和重放恢复。
        """
        battle = self.require_battle(battle_id)
        slot = self.db.get(BattleSkillSlot, slot_id)
        if slot is None or slot.battle_id != battle_id:
            raise LookupError(f"战斗技能槽不存在：{slot_id}")

        updated_fields = payload.model_fields_set & {"current_power", "current_energy_cost"}
        if not updated_fields:
            raise ValueError("至少需要提交 current_power 或 current_energy_cost")

        before = {
            "current_power": slot.current_power,
            "current_energy_cost": slot.current_energy_cost,
            "manual_override": slot.manual_override,
        }
        if "current_power" in updated_fields:
            slot.current_power = payload.current_power
        if "current_energy_cost" in updated_fields:
            slot.current_energy_cost = payload.current_energy_cost
        slot.manual_override = True
        after = {
            "current_power": slot.current_power,
            "current_energy_cost": slot.current_energy_cost,
            "manual_override": slot.manual_override,
        }

        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=battle.turn_number,
            event_type=BattleEventType.SKILL_SLOT_RUNTIME_CHANGE.value,
            actor_side=slot.side,
            actor_elf_id=slot.elf_id,
            target_side=slot.side,
            target_elf_id=slot.elf_id,
            skill_id=slot.skill_id,
            skill_confirmed=True,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
            payload_json=dumps_json(
                {
                    "slot_id": slot.slot_id,
                    "side": slot.side,
                    "elf_id": slot.elf_id,
                    "skill_id": slot.skill_id,
                    "slot_index": slot.slot_index,
                    "before": before,
                    "after": after,
                    "updated_fields": sorted(updated_fields),
                }
            ),
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.flush()
        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle_id,
            battle.turn_number,
            source_event_id=event.event_id,
            commit=False,
        )
        event.snapshot_id = snapshot.snapshot_id
        self.db.commit()
        self.db.refresh(battle)
        return self.get_state(battle)

    def get_state(self, battle: Battle) -> BattleStateOut:
        """获取战斗完整状态。"""
        elves = self.db.scalars(
            select(BattleElfState).where(BattleElfState.battle_id == battle.battle_id)
        ).all()
        effects = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle.battle_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()
        skill_slots = self.db.scalars(
            select(BattleSkillSlot).where(BattleSkillSlot.battle_id == battle.battle_id)
        ).all()
        estimates = self.db.scalars(
            select(EnemyPanelEstimate).where(
                EnemyPanelEstimate.battle_id == battle.battle_id,
                EnemyPanelEstimate.deleted_at.is_(None),
            )
        ).all()
        elf_dicts = self._battle_elf_state_dicts(elves, estimates)
        return BattleStateOut(
            battle=battle,
            elves=elf_dicts,
            active_effects=[model_to_dict(item) for item in effects],
            skill_slots=self._battle_skill_slot_dicts(
                battle,
                elves,
                effects,
                skill_slots,
                estimates,
            ),
            speed_preview=self._battle_speed_preview(battle, elves, effects, estimates),
            latest_snapshot_id=battle.current_snapshot_id,
        )

    def _battle_elf_state_dicts(
        self,
        elves: list[BattleElfState],
        estimates: list[EnemyPanelEstimate],
    ) -> list[dict[str, Any]]:
        """返回带性格和当前可计算面板来源的精灵状态。"""
        estimate_by_elf_id = {estimate.elf_id: estimate for estimate in estimates}
        result: list[dict[str, Any]] = []
        for state in elves:
            item = model_to_dict(state)
            item["effective_elf_id"] = self._effective_elf_id_for_state(state)
            item["effective_elf_name"] = state.runtime_form_elf_name or state.elf_name
            item["effective_avatar"] = state.runtime_form_avatar or state.avatar
            item["effective_form_source"] = (
                "runtime_form" if state.runtime_form_elf_id else "original"
            )
            panel_stats, panel_source = self._effective_panel_stats_for_state(
                state,
                estimate_by_elf_id.get(state.elf_id),
            )
            if panel_stats is not None:
                item["effective_panel_stats"] = panel_stats.model_dump()
                item["effective_panel_source"] = panel_source

            nature = self._nature_for_state(state, estimate_by_elf_id.get(state.elf_id))
            if nature is not None:
                item["nature_id"] = nature["nature_id"]
                item["nature_name"] = nature["nature_name"]
                item["nature_source"] = nature["source"]
            result.append(item)
        return result

    def _battle_skill_slot_dicts(
        self,
        battle: Battle,
        elves: list[BattleElfState],
        effects: list[BattleEffectInstance],
        skill_slots: list[BattleSkillSlot],
        estimates: list[EnemyPanelEstimate],
    ) -> list[dict[str, Any]]:
        """返回带静态技能信息和当前威力预览的技能槽。"""
        slot_dicts = [model_to_dict(item) for item in skill_slots]
        existing_keys = {
            (item.side, item.elf_id, item.skill_id)
            for item in skill_slots
        }
        for state in elves:
            confirmed_skill_ids = loads_json(state.confirmed_skill_ids_json, [])
            if not isinstance(confirmed_skill_ids, list):
                continue
            existing_indexes = [
                item.slot_index
                for item in skill_slots
                if item.side == state.side and item.elf_id == state.elf_id
            ]
            next_index = max(existing_indexes) + 1 if existing_indexes else 0
            for skill_index, raw_skill_id in enumerate(confirmed_skill_ids[:4]):
                skill_id = str(raw_skill_id)
                if (state.side, state.elf_id, skill_id) in existing_keys:
                    continue
                slot_dicts.append(
                    {
                        "slot_id": (
                            f"virtual_skill_slot:{battle.battle_id}:{state.side}:"
                            f"{state.elf_id}:{skill_id}"
                        ),
                        "battle_id": battle.battle_id,
                        "side": state.side,
                        "elf_id": state.elf_id,
                        "slot_index": skill_index if not existing_indexes else next_index,
                        "skill_id": skill_id,
                        "current_energy_cost": None,
                        "current_power": None,
                        "cooldown_remaining": None,
                        "active_effect_instance_ids_json": dumps_json([]),
                        "manual_override": False,
                        "slot_kind": "confirmed_virtual",
                        "is_virtual": True,
                    }
                )
                next_index += 1
                existing_keys.add((state.side, state.elf_id, skill_id))

        skill_ids = {str(item["skill_id"]) for item in slot_dicts if item.get("skill_id")}
        skills = {
            item.skill_id: item
            for item in self.db.scalars(
                select(SkillDefinition).where(SkillDefinition.skill_id.in_(skill_ids))
            ).all()
        } if skill_ids else {}
        elf_ids = {state.elf_id for state in elves}
        elf_ids.update(
            state.runtime_form_elf_id
            for state in elves
            if state.runtime_form_elf_id is not None
        )
        elf_definitions = {
            item.elf_id: item
            for item in self.db.scalars(
                select(ElfDefinition).where(ElfDefinition.elf_id.in_(elf_ids))
            ).all()
        } if elf_ids else {}
        state_by_key = {(state.side, state.elf_id): state for state in elves}
        estimate_by_elf_id = {estimate.elf_id: estimate for estimate in estimates}
        panel_by_key: dict[tuple[str, str], tuple[PanelStats, str]] = {}
        for state in elves:
            panel_stats, panel_source = self._effective_panel_stats_for_state(
                state,
                estimate_by_elf_id.get(state.elf_id),
            )
            if panel_stats is not None:
                panel_by_key[(state.side, state.elf_id)] = (panel_stats, panel_source)
        snapshot_payload = [model_to_dict(item) for item in effects]
        active_elf_by_side = {
            Side.SELF.value: battle.self_active_elf_id,
            Side.ENEMY.value: battle.enemy_active_elf_id,
        }

        enriched: list[dict[str, Any]] = []
        for slot in slot_dicts:
            skill = skills.get(str(slot.get("skill_id")))
            if skill is not None:
                slot["skill_name"] = skill.skill_name
                slot["skill_icon"] = skill.skill_icon
                slot["element_type"] = skill.element_type
                slot["skill_category"] = skill.skill_category
                slot["static_base_power"] = skill.base_power
                slot["base_energy_cost"] = skill.base_energy_cost
                slot["priority_modifier"] = skill.priority_modifier
                slot["damage_rule_json"] = skill.damage_rule_json
                slot["hit_rule_json"] = skill.hit_rule_json
                slot["effect_operations_json"] = skill.effect_operations_json
                slot["raw_description"] = skill.raw_description
                slot["skill_description"] = self._skill_original_description(skill)
                slot["effective_energy_cost"] = (
                    slot.get("current_energy_cost")
                    if slot.get("current_energy_cost") is not None
                    else skill.base_energy_cost
                )
                owner_state = state_by_key.get(
                    (str(slot.get("side") or ""), str(slot.get("elf_id") or ""))
                )
                attacker_effective_elf_id = (
                    self._effective_elf_id_for_state(owner_state)
                    if owner_state is not None
                    else str(slot.get("elf_id") or "")
                )
                elf = elf_definitions.get(attacker_effective_elf_id)
                attacker_elements = (
                    loads_json(elf.element_types_json, []) if elf is not None else []
                )
                if not isinstance(attacker_elements, list):
                    attacker_elements = []
                slot["attacker_element_types"] = [str(item) for item in attacker_elements]
                slot["effective_elf_id"] = attacker_effective_elf_id
                slot["power_preview"] = self._skill_slot_power_preview(
                    battle,
                    slot,
                    skill,
                    snapshot_payload,
                    [str(item) for item in attacker_elements],
                    active_elf_by_side,
                )
                slot["damage_preview"] = self._skill_slot_damage_preview(
                    battle,
                    slot,
                    skill,
                    elves,
                    state_by_key,
                    panel_by_key,
                    elf_definitions,
                    snapshot_payload,
                )
            else:
                slot["skill_name"] = None
                slot["power_preview"] = {"status": "skill_definition_missing"}
                slot["damage_preview"] = {"status": "skill_definition_missing"}
            if "slot_kind" not in slot:
                slot["slot_kind"] = "carried" if int(slot.get("slot_index") or 0) < 4 else "extra"
                slot["is_virtual"] = False
            enriched.append(slot)
        return sorted(
            enriched,
            key=lambda item: (
                str(item.get("side") or ""),
                str(item.get("elf_id") or ""),
                int(item.get("slot_index") or 0),
                str(item.get("skill_id") or ""),
            ),
        )

    @staticmethod
    def _skill_original_description(skill: SkillDefinition) -> str | None:
        """提取技能原始描述，优先使用爬虫/清洗阶段保留的 raw_description。"""
        if skill.raw_description and skill.raw_description.strip():
            return skill.raw_description.strip()
        rule_jsons = (
            skill.damage_rule_json,
            skill.effect_operations_json,
            skill.hit_rule_json,
        )
        for rule_json in rule_jsons:
            description = BattleService._raw_description_from_json(rule_json)
            if description:
                return description
        return None

    @staticmethod
    def _raw_description_from_json(raw_json: str | None) -> str | None:
        value = loads_json(raw_json, None)
        if isinstance(value, dict):
            raw_description = value.get("raw_description")
            if isinstance(raw_description, str) and raw_description.strip():
                return raw_description.strip()
        if isinstance(value, list):
            descriptions: list[str] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                raw_description = item.get("raw_description")
                if isinstance(raw_description, str) and raw_description.strip():
                    descriptions.append(raw_description.strip())
            if descriptions:
                return "；".join(dict.fromkeys(descriptions))
        return None

    def _battle_speed_preview(
        self,
        battle: Battle,
        elves: list[BattleElfState],
        effects: list[BattleEffectInstance],
        estimates: list[EnemyPanelEstimate],
    ) -> dict[str, Any]:
        """返回精简速度观察：只做当前速度与常见敌方档位对比，不写入推导。"""
        self_state = next(
            (
                item for item in elves
                if item.side == Side.SELF.value and item.elf_id == battle.self_active_elf_id
            ),
            None,
        )
        if self_state is None:
            return {"status": "missing_self_active"}

        estimate_by_elf_id = {estimate.elf_id: estimate for estimate in estimates}
        self_panel, self_panel_source = self._effective_panel_stats_for_state(self_state, None)
        if self_panel is None:
            return {"status": "missing_self_panel", "self_elf_id": self_state.elf_id}

        elf_ids = {self._effective_elf_id_for_state(state) for state in elves}
        elf_definitions = {
            item.elf_id: item
            for item in self.db.scalars(
                select(ElfDefinition).where(ElfDefinition.elf_id.in_(elf_ids))
            ).all()
        } if elf_ids else {}
        effect_definitions = self._effect_definitions_for_instances(effects)
        self_speed = self._speed_with_effect_modifiers(
            base_speed=self_panel.speed,
            side=self_state.side,
            elf_id=self_state.elf_id,
            effects=effects,
            effect_definitions=effect_definitions,
        )

        enemy_targets = [
            state for state in elves
            if state.side == Side.ENEMY.value
        ]
        enemy_team = [
            self._speed_preview_for_enemy_target(
                battle=battle,
                self_speed=self_speed,
                target_state=state,
                target_estimate=estimate_by_elf_id.get(state.elf_id),
                effects=effects,
                effect_definitions=effect_definitions,
                elf_definition=elf_definitions.get(self._effective_elf_id_for_state(state)),
            )
            for state in enemy_targets
        ]
        active_enemy = next(
            (item for item in enemy_team if item.get("is_active_target") is True),
            None,
        )

        return {
            "status": "resolved",
            "preview_scope": "speed_observation_only",
            "notes": "仅用于直观速度观察，不写入实时估计，也不做先手反推。",
            "self": {
                "side": self_state.side,
                "elf_id": self_state.elf_id,
                "elf_name": self_state.elf_name,
                "effective_elf_id": self._effective_elf_id_for_state(self_state),
                "effective_elf_name": self_state.runtime_form_elf_name or self_state.elf_name,
                "panel_source": self_panel_source,
                "base_speed": self_panel.speed,
                "speed_modifier": self_speed["modifier"],
                "current_speed": self_speed["current_speed"],
                "modifier_items": self_speed["items"],
                "unknown_factors": self_speed["unknown_factors"],
            },
            "active_enemy": active_enemy,
            "enemy_team": enemy_team,
            "assumptions": {
                "enemy_speed_individual_talent": 10,
                "neutral_speed_nature_multiplier": "1.0",
                "positive_speed_nature_multiplier": "1.2",
            },
        }

    def _speed_preview_for_enemy_target(
        self,
        *,
        battle: Battle,
        self_speed: dict[str, Any],
        target_state: BattleElfState,
        target_estimate: EnemyPanelEstimate | None,
        effects: list[BattleEffectInstance],
        effect_definitions: dict[str, EffectDefinition],
        elf_definition: ElfDefinition | None,
    ) -> dict[str, Any]:
        """计算单个敌方目标的推定/未加速/加速三档速度对比。"""
        target_speed_modifier = self._speed_with_effect_modifiers(
            base_speed=0,
            side=target_state.side,
            elf_id=target_state.elf_id,
            effects=effects,
            effect_definitions=effect_definitions,
        )
        rows: list[dict[str, Any]] = []
        target_panel, target_panel_source = self._effective_panel_stats_for_state(
            target_state,
            target_estimate,
        )
        if target_panel is not None:
            rows.append(
                self._speed_preview_row(
                    self_current_speed=int(self_speed["current_speed"]),
                    label=self._speed_panel_source_label(target_panel_source),
                    source=target_panel_source,
                    enemy_base_speed=target_panel.speed,
                    enemy_speed_modifier=int(target_speed_modifier["modifier"]),
                    unknown_factors=target_speed_modifier["unknown_factors"],
                )
            )

        if elf_definition is not None:
            neutral_base_speed = self._assumed_speed_for_elf(
                elf_definition,
                nature_multiplier=Decimal("1.0"),
                speed_individual=10,
            )
            positive_base_speed = self._assumed_speed_for_elf(
                elf_definition,
                nature_multiplier=Decimal("1.2"),
                speed_individual=10,
            )
            rows.extend(
                [
                    self._speed_preview_row(
                        self_current_speed=int(self_speed["current_speed"]),
                        label="未加速性格 + 速度资质10",
                        source="assumption_neutral_speed_10",
                        enemy_base_speed=neutral_base_speed,
                        enemy_speed_modifier=int(target_speed_modifier["modifier"]),
                        unknown_factors=target_speed_modifier["unknown_factors"],
                    ),
                    self._speed_preview_row(
                        self_current_speed=int(self_speed["current_speed"]),
                        label="加速性格 + 速度资质10",
                        source="assumption_positive_speed_10",
                        enemy_base_speed=positive_base_speed,
                        enemy_speed_modifier=int(target_speed_modifier["modifier"]),
                        unknown_factors=target_speed_modifier["unknown_factors"],
                    ),
                ]
            )

        return {
            "side": target_state.side,
            "elf_id": target_state.elf_id,
            "elf_name": target_state.elf_name,
            "effective_elf_id": self._effective_elf_id_for_state(target_state),
            "effective_elf_name": target_state.runtime_form_elf_name or target_state.elf_name,
            "is_active_target": target_state.elf_id == battle.enemy_active_elf_id,
            "speed_modifier": int(target_speed_modifier["modifier"]),
            "modifier_items": target_speed_modifier["items"],
            "unknown_factors": target_speed_modifier["unknown_factors"],
            "rows": rows,
        }

    @staticmethod
    def _speed_preview_row(
        *,
        self_current_speed: int,
        label: str,
        source: str,
        enemy_base_speed: int,
        enemy_speed_modifier: int,
        unknown_factors: list[str],
    ) -> dict[str, Any]:
        enemy_current_speed = max(enemy_base_speed + enemy_speed_modifier, 0)
        delta = self_current_speed - enemy_current_speed
        if delta > 0:
            relation = "self_faster"
        elif delta < 0:
            relation = "enemy_faster"
        else:
            relation = "speed_tie"
        return {
            "label": label,
            "source": source,
            "enemy_base_speed": enemy_base_speed,
            "enemy_speed_modifier": enemy_speed_modifier,
            "enemy_current_speed": enemy_current_speed,
            "self_current_speed": self_current_speed,
            "delta": delta,
            "relation": relation,
            "is_close": 0 < abs(delta) <= 3,
            "unknown_factors": list(unknown_factors),
        }

    @staticmethod
    def _speed_panel_source_label(panel_source: str) -> str:
        labels = {
            "runtime_state": "当前面板",
            "enemy_estimated_panel": "推定配置",
            "enemy_default_panel": "默认配置",
        }
        return labels.get(panel_source, "推定配置")

    @staticmethod
    def _assumed_speed_for_elf(
        elf: ElfDefinition,
        *,
        nature_multiplier: Decimal,
        speed_individual: int,
    ) -> int:
        return StatCalculator.calculate_non_hp(
            elf.base_speed_talent,
            speed_individual,
            nature_multiplier,
        )

    def _effect_definitions_for_instances(
        self,
        effects: list[BattleEffectInstance],
    ) -> dict[str, EffectDefinition]:
        effect_ids = {effect.effect_id for effect in effects if effect.effect_id}
        return {
            item.effect_id: item
            for item in self.db.scalars(
                select(EffectDefinition).where(EffectDefinition.effect_id.in_(effect_ids))
            ).all()
        } if effect_ids else {}

    def _speed_with_effect_modifiers(
        self,
        *,
        base_speed: int,
        side: str,
        elf_id: str,
        effects: list[BattleEffectInstance],
        effect_definitions: dict[str, EffectDefinition],
    ) -> dict[str, Any]:
        """把当前已结构化的速度 flat 修正叠加到基础速度上。"""
        modifier = Decimal("0")
        items: list[dict[str, Any]] = []
        unknown_factors: list[str] = []
        for effect in effects:
            if not self._effect_applies_to_speed_target(effect, side, elf_id):
                continue
            definition = effect_definitions.get(effect.effect_id)
            if definition is None or definition.deleted_at is not None:
                continue
            rule = loads_json(definition.stat_modifier_json, {})
            for stat_modifier in self._iter_speed_stat_modifiers(rule):
                value = self._flat_speed_modifier_value(stat_modifier, effect.layers)
                if value is None:
                    unknown_factors.append(f"speed_modifier_not_supported:{effect.effect_id}")
                    continue
                modifier += value
                items.append(
                    {
                        "effect_id": effect.effect_id,
                        "effect_name": definition.effect_name,
                        "layers": effect.layers,
                        "value": int(value),
                    }
                )
        modifier_int = int(modifier)
        return {
            "base_speed": base_speed,
            "modifier": modifier_int,
            "current_speed": max(base_speed + modifier_int, 0),
            "items": items,
            "unknown_factors": sorted(set(unknown_factors)),
        }

    @staticmethod
    def _effect_applies_to_speed_target(
        effect: BattleEffectInstance,
        side: str,
        elf_id: str,
    ) -> bool:
        if effect.owner_scope == "field":
            return True
        if effect.owner_scope == "side":
            return effect.owner_side == side
        if effect.owner_scope == "elf":
            return effect.owner_side == side and effect.owner_elf_id == elf_id
        return False

    @staticmethod
    def _iter_speed_stat_modifiers(rule: Any) -> list[dict[str, Any]]:
        if not isinstance(rule, dict):
            return []
        modifiers = rule.get("modifiers")
        if isinstance(modifiers, list):
            return [
                item for item in modifiers
                if isinstance(item, dict) and item.get("stat") == StatKey.SPEED.value
            ]
        if rule.get("stat") == StatKey.SPEED.value:
            return [rule]
        return []

    @staticmethod
    def _flat_speed_modifier_value(
        modifier: dict[str, Any],
        layers: int,
    ) -> Decimal | None:
        value_type = modifier.get("value_type")
        modifier_type = modifier.get("modifier_type")
        is_flat = value_type == "flat_add" or modifier_type in {"flat_add", "flat_speed"}
        if not is_flat:
            return None
        if modifier.get("value_per_layer") is not None:
            return Decimal(str(modifier["value_per_layer"])) * Decimal(str(layers or 1))
        if modifier.get("value") is not None:
            return Decimal(str(modifier["value"]))
        return None

    def _skill_slot_damage_preview(
        self,
        battle: Battle,
        slot: dict[str, Any],
        skill: SkillDefinition,
        elves: list[BattleElfState],
        state_by_key: dict[tuple[str, str], BattleElfState],
        panel_by_key: dict[tuple[str, str], tuple[PanelStats, str]],
        elf_definitions: dict[str, ElfDefinition],
        snapshot_payload: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """计算技能对对方当前上场和后备精灵的理论伤害。"""
        if skill.skill_category not in {"physical", "magic"} or skill.base_power is None:
            return {
                "status": "not_attack_skill",
                "reason": "skill_category_or_power_not_supported",
                "current_target": None,
                "targets": [],
            }

        attacker_side = str(slot.get("side") or "")
        attacker_elf_id = str(slot.get("elf_id") or "")
        attacker_panel_entry = panel_by_key.get((attacker_side, attacker_elf_id))
        if attacker_panel_entry is None:
            return {
                "status": "missing_attacker_panel",
                "current_target": None,
                "targets": [],
            }
        attacker_panel, attacker_panel_source = attacker_panel_entry
        defender_side = Side.ENEMY.value if attacker_side == Side.SELF.value else Side.SELF.value
        active_target_elf_id = (
            battle.enemy_active_elf_id if defender_side == Side.ENEMY.value
            else battle.self_active_elf_id
        )

        targets: list[dict[str, Any]] = []
        for target_state in elves:
            if target_state.side != defender_side:
                continue
            target = self._damage_preview_for_target(
                battle=battle,
                slot=slot,
                skill=skill,
                attacker_panel=attacker_panel,
                attacker_panel_source=attacker_panel_source,
                target_state=target_state,
                target_panel_entry=panel_by_key.get((target_state.side, target_state.elf_id)),
                attacker_definition=elf_definitions.get(
                    self._effective_elf_id_for_state(
                        state_by_key.get((attacker_side, attacker_elf_id))
                    )
                ),
                defender_definition=elf_definitions.get(
                    self._effective_elf_id_for_state(target_state)
                ),
                snapshot_payload=snapshot_payload,
                is_active_target=target_state.elf_id == active_target_elf_id,
            )
            targets.append(target)

        current_target = next((item for item in targets if item.get("is_active_target")), None)
        return {
            "status": "resolved" if current_target is not None else "no_opposing_targets",
            "preview_scope": "theoretical_current_state",
            "current_target": current_target,
            "targets": targets,
        }

    def _damage_preview_for_target(
        self,
        *,
        battle: Battle,
        slot: dict[str, Any],
        skill: SkillDefinition,
        attacker_panel: PanelStats,
        attacker_panel_source: str,
        target_state: BattleElfState,
        target_panel_entry: tuple[PanelStats, str] | None,
        attacker_definition: ElfDefinition | None,
        defender_definition: ElfDefinition | None,
        snapshot_payload: list[dict[str, Any]],
        is_active_target: bool,
    ) -> dict[str, Any]:
        base_result: dict[str, Any] = {
            "side": target_state.side,
            "elf_id": target_state.elf_id,
            "elf_name": target_state.elf_name,
            "effective_elf_id": self._effective_elf_id_for_state(target_state),
            "effective_elf_name": target_state.runtime_form_elf_name or target_state.elf_name,
            "is_active_target": is_active_target,
            "current_hp_percent": target_state.current_hp_percent,
        }
        if target_panel_entry is None:
            return {
                **base_result,
                "status": "formula_unavailable",
                "missing_parts": ["defender_panel_stats"],
                "unknown_factors": [],
            }

        defender_panel, defender_panel_source = target_panel_entry
        attacker_elements = self._element_types_from_definition(attacker_definition)
        defender_elements = self._element_types_from_definition(defender_definition)
        payload = {"resolve_rules": True}
        base_power = (
            slot.get("current_power")
            if slot.get("current_power") is not None
            else skill.base_power
        )
        context = DamageFormulaContext(
            battle_id=battle.battle_id,
            attacker_side=str(slot.get("side") or ""),
            attacker_elf_id=str(slot.get("elf_id") or ""),
            defender_side=target_state.side,
            defender_elf_id=target_state.elf_id,
            skill_id=skill.skill_id,
            skill_element_type=skill.element_type,
            skill_category=skill.skill_category,
            base_power=base_power,
            attacker_panel_stats=attacker_panel,
            defender_panel_stats=defender_panel,
            defender_max_hp=defender_panel.hp,
            defender_hp_percent=target_state.current_hp_percent,
            attacker_element_types=attacker_elements,
            defender_element_types=defender_elements,
            snapshot_payload=snapshot_payload,
        )
        resolved_context = RuleResolver(self.db).resolve_damage_context(context, payload)
        skill_modifier = self._skill_power_modifier_from_effects(
            resolved_context,
            snapshot_payload,
            str(slot.get("slot_id") or ""),
        )
        resolved_context.power_multiplier = (
            Decimal(str(resolved_context.power_multiplier)) * skill_modifier["multiplier"]
        )
        resolved_context.flat_power_bonus = (
            Decimal(str(resolved_context.flat_power_bonus)) + skill_modifier["flat_power_bonus"]
        )
        base_hit_count = int(resolved_context.hit_count or 1) + int(
            skill_modifier["hit_count_delta"]
        )
        resolved_context.hit_count = max(
            int(
                Decimal(str(base_hit_count))
                * Decimal(str(skill_modifier.get("hit_count_multiplier") or "1"))
            ),
            1,
        )
        if skill_modifier["items"]:
            resolved_context.rule_resolution_details["skill_modifier"] = skill_modifier["items"]
        result = DamageCalculator().calculate(resolved_context)
        percent = (
            round(result.damage_value / defender_panel.hp * 100, 2)
            if result.damage_value is not None and defender_panel.hp
            else None
        )
        explanation = result.explanation or {}
        rule_details = explanation.get("rule_resolution_details")
        if not isinstance(rule_details, dict):
            rule_details = resolved_context.rule_resolution_details
        return {
            **base_result,
            "status": result.status,
            "damage_value": result.damage_value,
            "damage_percent": percent,
            "damage_percent_text": f"{percent}%" if percent is not None else None,
            "confidence": result.confidence,
            "missing_parts": result.missing_parts,
            "unknown_factors": result.unknown_factors,
            "attacker_panel_source": attacker_panel_source,
            "defender_panel_source": defender_panel_source,
            "defender_max_hp": defender_panel.hp,
            "single_damage": explanation.get("single_damage"),
            "hit_count": explanation.get("hit_count"),
            "hit_count_source": explanation.get("hit_count_source"),
            "total_damage": explanation.get("total_damage"),
            "hit_rule": rule_details.get("hit_rule") if isinstance(rule_details, dict) else None,
            "multipliers": {
                "display_power": explanation.get("display_power"),
                "stab": self._rule_detail_value(rule_details, "stab_multiplier"),
                "type": self._rule_detail_value(rule_details, "type_multiplier"),
                "weather": self._rule_detail_value(rule_details, "weather_multiplier"),
                "stat_stage": self._rule_detail_value(rule_details, "stat_stage_multiplier"),
                "power": self._format_decimal(Decimal(str(resolved_context.power_multiplier))),
            },
        }

    def _skill_slot_power_preview(
        self,
        battle: Battle,
        slot: dict[str, Any],
        skill: SkillDefinition,
        snapshot_payload: list[dict[str, Any]],
        attacker_element_types: list[str],
        active_elf_by_side: dict[str, str | None],
    ) -> dict[str, Any]:
        """计算当前工作台技能槽上的公式输入威力预览。"""
        base_power = (
            slot.get("current_power")
            if slot.get("current_power") is not None
            else skill.base_power
        )
        if base_power is None:
            return {
                "status": "no_power",
                "base_power": None,
                "effective_display_power": None,
                "preview_scope": "non_damage_or_unknown_power",
            }
        attacker_side = str(slot.get("side") or "")
        defender_side = Side.ENEMY.value if attacker_side == Side.SELF.value else Side.SELF.value
        context = DamageFormulaContext(
            battle_id=battle.battle_id,
            attacker_side=attacker_side,
            attacker_elf_id=str(slot.get("elf_id") or ""),
            defender_side=defender_side,
            defender_elf_id=active_elf_by_side.get(defender_side),
            skill_id=skill.skill_id,
            skill_element_type=skill.element_type,
            skill_category=skill.skill_category,
            base_power=base_power,
            attacker_element_types=attacker_element_types,
            snapshot_payload=snapshot_payload,
        )
        context.stab_multiplier = (
            Decimal("1.25")
            if any(
                element_type_matches(skill.element_type, item)
                for item in attacker_element_types
            )
            else Decimal("1")
        )
        details = ModifierResolver(self.db).resolve_formula_modifiers(context, {})
        skill_modifier = self._skill_power_modifier_from_effects(
            context,
            snapshot_payload,
            str(slot.get("slot_id") or ""),
        )
        context.power_multiplier = skill_modifier["multiplier"]
        flat_power_bonus = skill_modifier["flat_power_bonus"]

        effective_power = (
            (Decimal(str(base_power)) + flat_power_bonus)
            * Decimal(str(context.power_multiplier))
            * Decimal(str(context.stat_stage_multiplier))
            * Decimal(str(context.stab_multiplier))
            * Decimal(str(context.weather_multiplier))
        )
        return {
            "status": "resolved",
            "base_power": base_power,
            "static_base_power": skill.base_power,
            "effective_display_power": self._decimal_to_number(effective_power),
            "effective_display_power_text": self._format_decimal(effective_power),
            "preview_scope": "current_state_without_type_effectiveness_or_response",
            "multipliers": {
                "stab": self._format_decimal(Decimal(str(context.stab_multiplier))),
                "stat_stage": self._format_decimal(Decimal(str(context.stat_stage_multiplier))),
                "weather": self._format_decimal(Decimal(str(context.weather_multiplier))),
                "skill_power": self._format_decimal(Decimal(str(context.power_multiplier))),
            },
            "flat_power_bonus": str(flat_power_bonus),
            "details": {
                **details,
                "skill_modifier": skill_modifier["items"],
            },
            "unknown_factors": context.unknown_factors,
        }

    def _skill_power_modifier_from_effects(
        self,
        context: DamageFormulaContext,
        snapshot_payload: list[dict[str, Any]],
        slot_id: str,
    ) -> dict[str, Any]:
        """从快照状态解析技能威力、连击和费用修正。"""
        return self._skill_effect_modifiers_from_snapshot(context, snapshot_payload, slot_id)

    def _skill_effect_modifiers_for_event(
        self,
        event: BattleEvent,
        skill: SkillDefinition,
        slot: BattleSkillSlot | None,
    ) -> dict[str, Any]:
        """技能扣能前按当前 active 状态解析费用修正。"""
        snapshot_payload = self._active_effect_snapshot_payload(event.battle_id)
        base_power = (
            slot.current_power
            if slot is not None and slot.current_power is not None
            else skill.base_power
        )
        context = DamageFormulaContext(
            battle_id=event.battle_id,
            attacker_side=str(event.actor_side or ""),
            attacker_elf_id=str(event.actor_elf_id or ""),
            defender_side=EffectOperationExecutor._opposite_side(event.actor_side),
            skill_id=skill.skill_id,
            skill_element_type=skill.element_type,
            skill_category=skill.skill_category,
            base_power=base_power,
            snapshot_payload=snapshot_payload,
        )
        payload = loads_json(event.payload_json, {})
        condition_flags = payload.get("condition_flags") if isinstance(payload, dict) else None
        if isinstance(condition_flags, dict):
            context.rule_resolution_details["condition_flags"] = {
                str(key): value is True
                for key, value in condition_flags.items()
            }
        return self._skill_effect_modifiers_from_snapshot(
            context,
            snapshot_payload,
            slot.slot_id if slot is not None else "",
        )

    def _skill_effect_modifiers_from_snapshot(
        self,
        context: DamageFormulaContext,
        snapshot_payload: list[dict[str, Any]],
        slot_id: str,
    ) -> dict[str, Any]:
        multiplier = Decimal("1")
        flat_power_bonus = Decimal("0")
        hit_count_delta = 0
        hit_count_multiplier = Decimal("1")
        use_count_delta = 0
        energy_cost_delta = 0
        items: list[dict[str, Any]] = []
        for item in snapshot_payload:
            if not isinstance(item, dict):
                continue
            definition = self.db.get(EffectDefinition, str(item.get("effect_id") or ""))
            if definition is None or definition.deleted_at is not None:
                continue
            if definition.category == "weather":
                continue
            remaining_uses = item.get("remaining_uses")
            if isinstance(remaining_uses, int | float) and int(remaining_uses) <= 0:
                continue
            if not self._skill_modifier_snapshot_item_applies(context, item, slot_id):
                continue
            rule = loads_json(definition.skill_modifier_json, {})
            if not isinstance(rule, dict) or not rule:
                continue
            if not self._skill_modifier_rule_matches(context, rule):
                continue
            layers = self._snapshot_layers(item)
            item_power_add = Decimal("0")
            if rule.get("power_add") is not None:
                item_power_add += Decimal(str(rule["power_add"]))
            if rule.get("power_add_per_layer") is not None:
                item_power_add += Decimal(str(rule["power_add_per_layer"])) * layers
            flat_power_bonus += item_power_add

            item_hit_count_delta = 0
            if rule.get("hit_count_delta") is not None:
                item_hit_count_delta += int(rule["hit_count_delta"])
            if rule.get("hit_count_delta_per_layer") is not None:
                item_hit_count_delta += int(
                    Decimal(str(rule["hit_count_delta_per_layer"])) * layers
                )
            hit_count_delta += item_hit_count_delta

            item_hit_count_multiplier = Decimal("1")
            if rule.get("hit_count_multiplier") is not None:
                item_hit_count_multiplier *= Decimal(str(rule["hit_count_multiplier"]))
            if rule.get("hit_count_multiplier_add_per_layer") is not None:
                item_hit_count_multiplier *= (
                    Decimal("1")
                    + Decimal(str(rule["hit_count_multiplier_add_per_layer"])) * layers
                )
            if item_hit_count_multiplier < 0:
                item_hit_count_multiplier = Decimal("0")
            hit_count_multiplier *= item_hit_count_multiplier

            item_use_count_delta = 0
            if rule.get("use_count_delta") is not None:
                item_use_count_delta += int(rule["use_count_delta"])
            if rule.get("use_count_delta_per_layer") is not None:
                item_use_count_delta += int(
                    Decimal(str(rule["use_count_delta_per_layer"])) * layers
                )
            use_count_delta += item_use_count_delta

            item_energy_cost_delta = 0
            if rule.get("energy_cost_delta") is not None:
                item_energy_cost_delta += int(rule["energy_cost_delta"])
            if rule.get("energy_cost_delta_per_layer") is not None:
                item_energy_cost_delta += int(
                    Decimal(str(rule["energy_cost_delta_per_layer"])) * layers
                )
            energy_cost_delta += item_energy_cost_delta

            rule_multiplier = self._skill_modifier_multiplier(rule, layers)
            if (
                rule_multiplier is None
                and item_power_add == 0
                and item_hit_count_delta == 0
                and item_hit_count_multiplier == 1
                and item_use_count_delta == 0
                and item_energy_cost_delta == 0
            ):
                continue
            if rule_multiplier is not None:
                multiplier *= rule_multiplier
            items.append(
                {
                    "effect_id": definition.effect_id,
                    "effect_instance_id": item.get("instance_id"),
                    "effect_name": definition.effect_name,
                    "modifier_type": rule.get("modifier_type"),
                    "remaining_uses": remaining_uses,
                    "layers": str(layers),
                    "multiplier": str(rule_multiplier or Decimal("1")),
                    "power_add": str(item_power_add),
                    "hit_count_delta": item_hit_count_delta,
                    "hit_count_multiplier": str(item_hit_count_multiplier),
                    "use_count_delta": item_use_count_delta,
                    "energy_cost_delta": item_energy_cost_delta,
                    "requires_burst": rule.get("requires_burst") is True,
                }
            )
        return {
            "multiplier": multiplier,
            "flat_power_bonus": flat_power_bonus,
            "hit_count_delta": hit_count_delta,
            "hit_count_multiplier": hit_count_multiplier,
            "use_count_delta": use_count_delta,
            "energy_cost_delta": energy_cost_delta,
            "items": items,
        }

    def _active_effect_snapshot_payload(self, battle_id: str) -> list[dict[str, Any]]:
        """把当前 active 状态转成与快照相同的轻量结构。"""
        return [
            model_to_dict(item)
            for item in self.db.scalars(
                select(BattleEffectInstance).where(
                    BattleEffectInstance.battle_id == battle_id,
                    BattleEffectInstance.is_active.is_(True),
                )
            ).all()
        ]

    @staticmethod
    def _snapshot_layers(item: dict[str, Any]) -> Decimal:
        try:
            return Decimal(str(item.get("layers", 1)))
        except Exception:
            return Decimal("1")

    @staticmethod
    def _skill_modifier_snapshot_item_applies(
        context: DamageFormulaContext,
        item: dict[str, Any],
        slot_id: str,
    ) -> bool:
        owner_scope = item.get("owner_scope")
        owner_side = item.get("owner_side")
        owner_elf_id = item.get("owner_elf_id")
        if owner_scope == "field":
            return True
        if owner_scope == "side":
            return owner_side == context.attacker_side
        if owner_scope == "elf":
            return owner_side == context.attacker_side and (
                context.attacker_elf_id is None or owner_elf_id == context.attacker_elf_id
            )
        if owner_scope == "skill_slot":
            return item.get("owner_skill_slot_id") == slot_id
        return False

    @staticmethod
    def _skill_modifier_rule_matches(
        context: DamageFormulaContext,
        rule: dict[str, Any],
    ) -> bool:
        element_type = rule.get("element_type")
        if element_type is not None and not element_type_matches(
            element_type,
            context.skill_element_type,
        ):
            return False
        required_condition_flag = rule.get("required_condition_flag")
        if required_condition_flag is not None:
            condition_flags = context.rule_resolution_details.get("condition_flags", {})
            if not isinstance(condition_flags, dict) or condition_flags.get(
                str(required_condition_flag)
            ) is not True:
                return False
        if rule.get("requires_burst") is True:
            condition_flags = context.rule_resolution_details.get("condition_flags", {})
            if not isinstance(condition_flags, dict):
                return False
            if not (
                condition_flags.get("burst_triggered") is True
                or condition_flags.get("burst_active") is True
            ):
                return False
        skill_category = rule.get("skill_category")
        if skill_category is not None:
            if isinstance(skill_category, list):
                allowed_categories = {str(item) for item in skill_category}
            elif str(skill_category) in {"attack", "physical_or_magic"}:
                allowed_categories = {"physical", "magic"}
            else:
                allowed_categories = {str(skill_category)}
            if context.skill_category not in allowed_categories:
                return False
        return True

    @staticmethod
    def _skill_modifier_multiplier(
        rule: dict[str, Any],
        layers: Decimal | None = None,
    ) -> Decimal | None:
        """解析技能威力倍率，支持固定倍率和按层数叠加的百分比倍率。"""
        value = rule.get("value")
        if value is None:
            value = rule.get("power_multiplier")
        if value is None:
            value = rule.get("damage_multiplier")
        if value is None:
            value = rule.get("multiplier")
        per_layer_value = (
            rule.get("power_multiplier_add_per_layer")
            if rule.get("power_multiplier_add_per_layer") is not None
            else rule.get("multiplier_add_per_layer")
        )
        if per_layer_value is not None:
            layer_count = layers if layers is not None else Decimal("1")
            return Decimal("1") + Decimal(str(per_layer_value)) * layer_count
        if value is None:
            return None
        value_type = str(rule.get("value_type") or "")
        decimal_value = Decimal(str(value))
        if value_type in {"percent_add", "add_percent"}:
            return Decimal("1") + decimal_value
        return decimal_value

    def _resolve_charge_state_for_skill_event(
        self,
        event: BattleEvent,
        skill: SkillDefinition,
    ) -> dict[str, Any]:
        """解析蓄力技能在本次选择中的阶段。

        已确认口径：第一次选择蓄力技能会扣能并进入蓄力准备；第二回合需再次
        选择同一技能释放；切换清除蓄力准备。当前按“释放不重复扣能”处理，
        若后续实测确认第二次仍扣能，只需要调整这里的 cost override。
        """
        if not self._skill_requires_charge(skill):
            return {"phase": "not_required"}
        ready = self._active_charge_ready_instance(event)
        if ready is not None and ready.source_skill_id == skill.skill_id:
            return {
                "phase": "charge_released",
                "ready_effect_instance_id": ready.instance_id,
                "charged_skill_id": ready.source_skill_id,
                "release_energy_cost_policy": "no_second_cost",
            }
        bypass = self._active_next_charge_free_instance(event)
        if bypass is not None:
            return {
                "phase": "charge_bypassed",
                "bypass_effect_instance_id": bypass.instance_id,
                "release_energy_cost_policy": "no_second_cost",
            }
        if ready is not None and ready.source_skill_id != skill.skill_id:
            return {
                "phase": "blocked_different_skill_charged",
                "ready_effect_instance_id": ready.instance_id,
                "charged_skill_id": ready.source_skill_id,
                "selected_skill_id": skill.skill_id,
            }
        return {
            "phase": "charge_started",
            "selected_skill_id": skill.skill_id,
            "first_turn_energy_cost_policy": "consume_now",
        }

    def _apply_charge_state_resolution(
        self,
        event: BattleEvent,
        skill: SkillDefinition,
        charge_state: dict[str, Any],
    ) -> None:
        """根据蓄力阶段施加或移除蓄力状态。"""
        phase = charge_state.get("phase")
        if phase == "charge_started":
            results = EffectOperationExecutor(self.db).execute_operations_for_event(
                event,
                [
                    {
                        "op_type": "apply_effect",
                        "effect_id": "effect_charge_ready",
                        "target": "actor_side",
                        "layers": 1,
                        "condition": "always",
                        "timing": "on_skill_use",
                    }
                ],
            )
            charge_state["state_operation_results"] = results
            return
        if phase == "charge_released":
            instance_id = charge_state.get("ready_effect_instance_id")
            if isinstance(instance_id, str):
                charge_state["state_operation_results"] = (
                    EffectOperationExecutor(self.db).execute_operations_for_event(
                        event,
                        [
                            {
                                "op_type": "remove_effect",
                                "effect_id": "effect_charge_ready",
                                "target": "actor_side",
                                "condition": "always",
                                "timing": "on_skill_use",
                            }
                        ],
                    )
                )
            return
        if phase == "charge_bypassed":
            instance_id = charge_state.get("bypass_effect_instance_id")
            if isinstance(instance_id, str):
                charge_state["state_operation_results"] = (
                    EffectOperationExecutor(self.db).execute_operations_for_event(
                        event,
                        [
                            {
                                "op_type": "remove_effect",
                                "effect_id": "effect_next_charge_free",
                                "target": "actor_side",
                                "condition": "always",
                                "timing": "on_skill_use",
                            }
                        ],
                    )
                )

    def _active_charge_ready_instance(self, event: BattleEvent) -> BattleEffectInstance | None:
        return self._active_actor_effect_instance(event, "effect_charge_ready")

    def _active_next_charge_free_instance(self, event: BattleEvent) -> BattleEffectInstance | None:
        return self._active_actor_effect_instance(event, "effect_next_charge_free")

    def _active_actor_effect_instance(
        self,
        event: BattleEvent,
        effect_id: str,
    ) -> BattleEffectInstance | None:
        if event.actor_side is None or event.actor_elf_id is None:
            return None
        return self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == event.battle_id,
                BattleEffectInstance.effect_id == effect_id,
                BattleEffectInstance.owner_scope == "elf",
                BattleEffectInstance.owner_side == event.actor_side,
                BattleEffectInstance.owner_elf_id == event.actor_elf_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).first()

    @staticmethod
    def _skill_requires_charge(skill: SkillDefinition) -> bool:
        rule = loads_json(skill.damage_rule_json, {})
        if not isinstance(rule, dict):
            return False
        manual_review = rule.get("manual_review")
        hooks = manual_review.get("future_hooks") if isinstance(manual_review, dict) else None
        if not isinstance(hooks, list):
            return False
        charge_hook_types = {
            "charge_before_attack",
            "charge_turn_mechanic",
            "charge_then_apply_effects",
        }
        return any(
            isinstance(hook, dict) and hook.get("hook_type") in charge_hook_types
            for hook in hooks
        )

    def _effective_panel_stats_for_state(
        self,
        state: BattleElfState,
        estimate: EnemyPanelEstimate | None,
    ) -> tuple[PanelStats, str] | tuple[None, str]:
        state_panel = self._panel_stats_from_json(state.panel_stats_json)
        if state_panel is not None:
            return state_panel, "runtime_state"
        if state.side == Side.ENEMY.value and estimate is not None:
            estimated_panel = self._panel_stats_from_json(estimate.estimated_panel_json)
            if estimated_panel is not None:
                return estimated_panel, "enemy_estimated_panel"
            default_panel = self._panel_stats_from_json(estimate.default_panel_json)
            if default_panel is not None:
                return default_panel, "enemy_default_panel"
        return None, "missing"

    def _nature_for_state(
        self,
        state: BattleElfState,
        estimate: EnemyPanelEstimate | None,
    ) -> dict[str, str] | None:
        if state.nature_id:
            nature = self.db.get(NatureDefinition, state.nature_id)
            if nature is not None and nature.deleted_at is None:
                return {
                    "nature_id": nature.nature_id,
                    "nature_name": nature.nature_name,
                    "source": "runtime_state",
                }
        if state.side == Side.ENEMY.value and estimate is not None:
            config = loads_json(estimate.default_config_json, {})
            nature_id = config.get("nature_id") if isinstance(config, dict) else None
            nature = self.db.get(NatureDefinition, str(nature_id)) if nature_id else None
            if nature is not None and nature.deleted_at is None:
                return {
                    "nature_id": nature.nature_id,
                    "nature_name": nature.nature_name,
                    "source": "enemy_default_config",
                }

        if state.side == Side.SELF.value:
            build = self.db.scalars(
                select(PlayerElfBuild).where(
                    PlayerElfBuild.elf_id == state.elf_id,
                    PlayerElfBuild.final_stats_json == state.panel_stats_json,
                    PlayerElfBuild.deleted_at.is_(None),
                )
            ).first()
            if build is not None:
                nature = self.db.get(NatureDefinition, build.nature_id)
                if nature is not None and nature.deleted_at is None:
                    return {
                        "nature_id": nature.nature_id,
                        "nature_name": nature.nature_name,
                        "source": "matched_player_build",
                    }
        return None

    def _runtime_form_build_inputs(
        self,
        state: BattleElfState,
    ) -> tuple[NatureRule, IndividualTalentDistribution, str]:
        """读取形态切换时需要保留的性格与个体培养。"""
        nature_id = state.nature_id
        individual_payload = loads_json(state.individual_talent_distribution_json, None)
        source = "runtime_state"

        if not nature_id or not isinstance(individual_payload, dict):
            if state.side == Side.ENEMY.value:
                estimate = self.db.scalars(
                    select(EnemyPanelEstimate).where(
                        EnemyPanelEstimate.battle_id == state.battle_id,
                        EnemyPanelEstimate.elf_id == state.elf_id,
                        EnemyPanelEstimate.deleted_at.is_(None),
                    )
                ).first()
                config = loads_json(estimate.default_config_json, {}) if estimate else {}
                if isinstance(config, dict):
                    nature_id = nature_id or config.get("nature_id")
                    individual_payload = (
                        individual_payload
                        if isinstance(individual_payload, dict)
                        else config.get("individual_talent_distribution")
                    )
                    source = "enemy_default_config"
            elif state.side == Side.SELF.value:
                build = self.db.scalars(
                    select(PlayerElfBuild).where(
                        PlayerElfBuild.elf_id == state.elf_id,
                        PlayerElfBuild.deleted_at.is_(None),
                    )
                ).first()
                if build is not None:
                    nature_id = nature_id or build.nature_id
                    individual_payload = (
                        individual_payload
                        if isinstance(individual_payload, dict)
                        else loads_json(build.individual_talent_distribution_json, {})
                    )
                    source = "matched_player_build_fallback"

        if not nature_id or not isinstance(individual_payload, dict):
            raise ValueError("缺少性格或个体培养快照，无法在保留培养的前提下重算运行时形态")
        nature = self.db.get(NatureDefinition, str(nature_id))
        if nature is None or nature.deleted_at is not None:
            raise ValueError(f"性格不存在：{nature_id}")
        try:
            individual = IndividualTalentDistribution(**individual_payload)
        except ValueError as exc:
            raise ValueError("个体培养快照格式不正确，无法重算运行时形态") from exc
        state.nature_id = nature.nature_id
        state.individual_talent_distribution_json = dumps_json(individual)
        return self._nature_to_rule(nature), individual, source

    @staticmethod
    def _effective_elf_id_for_state(state: BattleElfState | None) -> str:
        if state is None:
            return ""
        return state.runtime_form_elf_id or state.elf_id

    @staticmethod
    def _panel_stats_from_json(raw_json: str | None) -> PanelStats | None:
        stats = loads_json(raw_json, {})
        if not isinstance(stats, dict):
            return None
        required = (
            "hp",
            "physical_attack",
            "physical_defense",
            "magic_attack",
            "magic_defense",
            "speed",
        )
        if any(stats.get(key) is None for key in required):
            return None
        try:
            return PanelStats(
                hp=int(stats["hp"]),
                physical_attack=int(stats["physical_attack"]),
                physical_defense=int(stats["physical_defense"]),
                magic_attack=int(stats["magic_attack"]),
                magic_defense=int(stats["magic_defense"]),
                speed=int(stats["speed"]),
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _element_types_from_definition(definition: ElfDefinition | None) -> list[str]:
        if definition is None:
            return []
        value = loads_json(definition.element_types_json, [])
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]

    @staticmethod
    def _elf_to_base_talent_block(elf: ElfDefinition) -> BaseTalentBlock:
        return BaseTalentBlock(
            hp=elf.base_hp_talent,
            physical_attack=elf.base_physical_attack_talent,
            physical_defense=elf.base_physical_defense_talent,
            magic_attack=elf.base_magic_attack_talent,
            magic_defense=elf.base_magic_defense_talent,
            speed=elf.base_speed_talent,
        )

    @staticmethod
    def _nature_to_rule(nature: NatureDefinition) -> NatureRule:
        return NatureRule(
            nature_id=nature.nature_id,
            positive_stat=StatKey(nature.positive_stat),
            negative_stat=StatKey(nature.negative_stat),
        )

    @staticmethod
    def _rule_detail_value(details: dict[str, Any], key: str) -> Any:
        value = details.get(key)
        if isinstance(value, dict):
            return value.get("value") or value.get("possible_multiplier")
        return None

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        normalized = value.quantize(Decimal("0.01")) if value != value.to_integral() else value
        return format(normalized.normalize(), "f")

    @staticmethod
    def _decimal_to_number(value: Decimal) -> int | float:
        if value == value.to_integral():
            return int(value)
        return float(value.quantize(Decimal("0.01")))

    def get_timeline(self, battle_id: str) -> list[BattleTimelineTurnOut]:
        """
        获取按回合聚合的战斗事件时间线。

        时间线以 battle_event 为主轴，并尝试挂载对应的子事件详情：
        - damage_event：伤害数值、连击信息、扣血百分比、公式上下文占位；
        - effect_change_event：状态施加、移除、切换清除或保留；
        - 其他事件：保留 payload_json 和通用字段，detail 为空。
        """
        self.require_battle(battle_id)
        events = list(
            self.db.scalars(
                select(BattleEvent)
                .where(BattleEvent.battle_id == battle_id, BattleEvent.is_voided.is_(False))
                .order_by(BattleEvent.turn_number, BattleEvent.action_order, BattleEvent.created_at)
            ).all()
        )
        if not events:
            return []

        event_ids = [event.event_id for event in events]
        damage_by_event_id = {
            item.battle_event_id: item
            for item in self.db.scalars(
                select(DamageEvent).where(DamageEvent.battle_event_id.in_(event_ids))
            ).all()
        }
        effect_changes_by_event_id: dict[str, list[EffectChangeEvent]] = {}
        for item in self.db.scalars(
            select(EffectChangeEvent).where(EffectChangeEvent.battle_event_id.in_(event_ids))
        ).all():
            effect_changes_by_event_id.setdefault(item.battle_event_id, []).append(item)

        resource_by_event_id = {
            item.battle_event_id: item
            for item in self.db.scalars(
                select(ResourceChangeEvent).where(ResourceChangeEvent.battle_event_id.in_(event_ids))
            ).all()
        }

        grouped: dict[int, list[BattleTimelineEventOut]] = {}
        for event in events:
            detail_type: str | None = None
            detail: dict = {}
            if event.event_id in damage_by_event_id:
                detail_type = "damage"
                detail = model_to_dict(damage_by_event_id[event.event_id])
            elif event.event_id in effect_changes_by_event_id:
                detail_type = "effect_change"
                detail = {
                    "items": [
                        model_to_dict(item)
                        for item in effect_changes_by_event_id[event.event_id]
                    ]
                }
            elif event.event_id in resource_by_event_id:
                detail_type = "resource_change"
                detail = model_to_dict(resource_by_event_id[event.event_id])
            grouped.setdefault(event.turn_number, []).append(
                BattleTimelineEventOut(
                    event=event,
                    detail_type=detail_type,
                    detail=detail,
                )
            )

        return [
            BattleTimelineTurnOut(turn_number=turn_number, events=items)
            for turn_number, items in sorted(grouped.items(), key=lambda item: item[0])
        ]

    def create_event(self, battle_id: str, payload: BattleEventCreate) -> BattleEvent:
        """创建通用战斗事件。"""
        self.require_battle(battle_id)
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=payload.turn_number,
            action_order=payload.action_order,
            event_type=payload.event_type,
            actor_side=payload.actor_side,
            actor_elf_id=payload.actor_elf_id,
            target_side=payload.target_side,
            target_elf_id=payload.target_elf_id,
            skill_id=payload.skill_id,
            skill_confirmed=payload.skill_confirmed,
            snapshot_id=payload.snapshot_id,
            source=payload.source,
            recognition_confidence=payload.recognition_confidence,
            manual_override=payload.manual_override,
            corrected_event_id=payload.corrected_event_id,
            is_voided=payload.is_voided,
            payload_json=payload.payload_json,
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.flush()
        effect_operation_results: list[dict] = []
        skill_runtime_result: dict | None = None
        event_payload = loads_json(event.payload_json, {})
        if not isinstance(event_payload, dict):
            event_payload = {"raw_payload": event.payload_json}
        if event.event_type == BattleEventType.SKILL_USE.value:
            event_payload = self._enrich_skill_event_condition_flags(event, event_payload)
            event.payload_json = dumps_json(event_payload)
            skill_runtime_result = self._process_skill_runtime(event)
            charge_phase = (
                skill_runtime_result.get("charge", {}).get("phase")
                if isinstance(skill_runtime_result, dict)
                and isinstance(skill_runtime_result.get("charge"), dict)
                else None
            )
            if charge_phase in {"charge_started", "blocked_different_skill_charged"}:
                effect_operation_results.append(
                    {
                        "status": "skipped",
                        "reason": (
                            "charge_started_waiting_for_release"
                            if charge_phase == "charge_started"
                            else "different_charged_skill_waiting_for_manual_resolution"
                        ),
                        "operation": "skill_effect_operations",
                    }
                )
            else:
                if skill_runtime_result:
                    event_payload["skill_runtime"] = skill_runtime_result
                    event.payload_json = dumps_json(event_payload)
                effect_operation_results = EffectOperationExecutor(self.db).execute_for_skill_event(
                    event
                )
                mark_trigger_results = self._apply_skill_use_mark_triggers(
                    event,
                    skill_runtime_result,
                )
                effect_operation_results.extend(mark_trigger_results)
            burst_effects = self._burst_effects_from_results(
                skill_runtime_result,
                effect_operation_results,
            )
            if self._event_condition_flag(event, "burst_active") and burst_effects:
                burst_event = self._create_burst_trigger_event(event, burst_effects)
                event_payload["burst_trigger_event_id"] = burst_event.event_id
                event_payload["burst_effects"] = burst_effects
        manual_operations = event_payload.get("manual_effect_operations")
        if isinstance(manual_operations, list):
            manual_results = EffectOperationExecutor(self.db).execute_operations_for_event(
                event,
                [item for item in manual_operations if isinstance(item, dict)],
            )
            effect_operation_results.extend(manual_results)
        if skill_runtime_result or effect_operation_results:
            latest_payload = loads_json(event.payload_json, {})
            if isinstance(latest_payload, dict):
                latest_payload.update(event_payload)
                event_payload = latest_payload
            if skill_runtime_result:
                event_payload["skill_runtime"] = skill_runtime_result
            event_payload["effect_operation_results"] = effect_operation_results
            event.payload_json = dumps_json(event_payload)
        # 泛用事件没有专用子表时仍创建快照，方便时间线解释和后续回放。
        if event.snapshot_id is None:
            snapshot = SnapshotService(self.db).create_effect_snapshot(
                battle_id,
                payload.turn_number,
                source_event_id=event.event_id,
                commit=False,
            )
            event.snapshot_id = snapshot.snapshot_id
        self.db.commit()
        self.db.refresh(event)
        return event

    def _enrich_skill_event_condition_flags(
        self,
        event: BattleEvent,
        event_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """补齐技能事件可由当前战斗状态安全判断的条件旗标。"""
        condition_flags = event_payload.get("condition_flags")
        if not isinstance(condition_flags, dict):
            condition_flags = {}
        else:
            condition_flags = {str(key): value is True for key, value in condition_flags.items()}
        if condition_flags.get("burst_active") is not False and self._is_burst_eligible(event):
            condition_flags.setdefault("burst_active", True)
            condition_flags.setdefault("burst_triggered", True)
            event_payload["burst_eligibility"] = {
                "status": "eligible",
                "reason": "first_turn_after_entry",
            }
        if condition_flags:
            event_payload["condition_flags"] = condition_flags
        return event_payload

    def _switched_sides_this_turn(self, *, battle_id: str, turn_number: int) -> set[str]:
        stmt = select(BattleEvent.actor_side).where(
            BattleEvent.battle_id == battle_id,
            BattleEvent.turn_number == turn_number,
            BattleEvent.event_type == BattleEventType.SWITCH_ELF.value,
            BattleEvent.actor_side.is_not(None),
            BattleEvent.is_voided.is_(False),
        )
        return {side for side in self.db.scalars(stmt).all() if side}

    def _is_burst_eligible(self, event: BattleEvent) -> bool:
        """判断当前技能是否处于登场首回合的迸发窗口。"""
        if event.actor_side not in {Side.SELF.value, Side.ENEMY.value} or not event.actor_elf_id:
            return False
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == event.battle_id,
                BattleElfState.side == event.actor_side,
                BattleElfState.elf_id == event.actor_elf_id,
                BattleElfState.is_active_elf.is_(True),
            )
        ).first()
        if state is None:
            return False
        if state.last_switch_turn == event.turn_number:
            return True
        return state.last_switch_turn == 0 and event.turn_number == 1

    @staticmethod
    def _event_condition_flag(event: BattleEvent, key: str) -> bool:
        payload = loads_json(event.payload_json, {})
        if not isinstance(payload, dict):
            return False
        flags = payload.get("condition_flags")
        return isinstance(flags, dict) and flags.get(key) is True

    def _burst_effects_from_results(
        self,
        skill_runtime_result: dict | None,
        effect_operation_results: list[dict],
    ) -> list[dict]:
        """提取本次迸发实际带来的具体附加效果。"""
        burst_effects: list[dict] = []
        if isinstance(skill_runtime_result, dict):
            for item in skill_runtime_result.get("skill_modifier", []):
                if not isinstance(item, dict):
                    continue
                modifier_type = str(item.get("modifier_type") or "")
                if item.get("requires_burst") is True or "burst" in modifier_type:
                    burst_effects.append(
                        {
                            "effect_id": item.get("effect_id"),
                            "effect_name": item.get("effect_name"),
                            "modifier_type": item.get("modifier_type"),
                            "layers": item.get("layers"),
                            "multiplier": item.get("multiplier"),
                            "power_add": item.get("power_add"),
                            "energy_cost_delta": item.get("energy_cost_delta"),
                            "use_count_delta": item.get("use_count_delta"),
                            "source": "skill_modifier",
                        }
                    )
        for item in effect_operation_results:
            if not isinstance(item, dict):
                continue
            if item.get("condition") not in {"burst_active", "burst_triggered"}:
                continue
            burst_effects.append(
                {
                    "effect_id": item.get("effect_id"),
                    "effect_name": item.get("effect_name"),
                    "operation": item.get("operation"),
                    "layers_after": item.get("layers_after"),
                    "source": "effect_operation",
                }
            )
        return burst_effects

    def _create_burst_trigger_event(
        self,
        source_event: BattleEvent,
        burst_effects: list[dict],
    ) -> BattleEvent:
        """记录一次已发生的迸发及其具体附加效果。"""
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=source_event.battle_id,
            turn_number=source_event.turn_number,
            action_order=source_event.action_order,
            event_type=BattleEventType.EFFECT_TRIGGER.value,
            actor_side=source_event.actor_side,
            actor_elf_id=source_event.actor_elf_id,
            target_side=source_event.target_side,
            target_elf_id=source_event.target_elf_id,
            skill_id=source_event.skill_id,
            skill_confirmed=source_event.skill_confirmed,
            source=EventSource.SYSTEM_CALCULATED.value,
            manual_override=False,
            payload_json=dumps_json(
                {
                    "trigger_type": "burst",
                    "source_event_id": source_event.event_id,
                    "source_skill_id": source_event.skill_id,
                    "burst_effects": burst_effects,
                }
            ),
            notes="迸发触发记录",
        )
        self.db.add(event)
        self.db.flush()
        return event

    def _process_skill_runtime(self, event: BattleEvent) -> dict | None:
        """处理技能槽运行时状态：扣能、回显当前槽值，并保留未来钩子入口。"""
        if event.skill_id is None or event.actor_side is None or event.actor_elf_id is None:
            return None
        skill = self.db.get(SkillDefinition, event.skill_id)
        if skill is None or skill.deleted_at is not None:
            return {"status": "skill_definition_missing", "skill_id": event.skill_id}
        slot, slot_created = self._ensure_runtime_skill_slot(event, skill)
        static_energy_cost = max(skill.base_energy_cost or 0, 0)
        base_runtime_energy_cost = (
            max(slot.current_energy_cost, 0)
            if slot is not None and slot.current_energy_cost is not None
            else static_energy_cost
        )
        energy_modifier = self._skill_effect_modifiers_for_event(event, skill, slot)
        dynamic_energy_modifier = self._skill_dynamic_energy_cost_modifier(event, skill)
        dynamic_use_count_modifier = self._skill_dynamic_use_count_modifier(event, skill)
        hit_rule_result = self._resolve_skill_hit_count_for_event(event)
        combined_energy_cost_delta = (
            int(energy_modifier["energy_cost_delta"])
            + int(dynamic_energy_modifier["energy_cost_delta"])
        )
        combined_modifier_items = [
            *energy_modifier["items"],
            *dynamic_energy_modifier["items"],
            *dynamic_use_count_modifier["items"],
        ]
        effective_use_count = max(
            1
            + int(energy_modifier.get("use_count_delta") or 0)
            + int(dynamic_use_count_modifier.get("use_count_delta") or 0),
            1,
        )
        hit_count_modifier_delta = 0
        hit_count_modifier_multiplier = Decimal("1")
        if hit_rule_result["source"] not in {"manual_payload", "auto_effect_prefill"}:
            hit_count_modifier_delta = int(energy_modifier.get("hit_count_delta") or 0)
            hit_count_modifier_multiplier = Decimal(
                str(energy_modifier.get("hit_count_multiplier") or "1")
            )
        effective_hit_count = max(
            int(
                (Decimal(str(int(hit_rule_result["hit_count"]) + hit_count_modifier_delta)))
                * hit_count_modifier_multiplier
            ),
            1,
        )
        charge_state = self._resolve_charge_state_for_skill_event(event, skill)
        effective_energy_cost = max(
            int(base_runtime_energy_cost + combined_energy_cost_delta),
            0,
        ) * effective_use_count
        if charge_state["phase"] in {
            "charge_released",
            "charge_bypassed",
            "blocked_different_skill_charged",
        }:
            effective_energy_cost = 0
        summary: dict = {
            "status": "resolved",
            "skill_id": skill.skill_id,
            "slot_id": slot.slot_id if slot is not None else None,
            "slot_created": slot_created,
            "static_energy_cost": static_energy_cost,
            "base_runtime_energy_cost": base_runtime_energy_cost,
            "effective_energy_cost": effective_energy_cost,
            "effective_use_count": effective_use_count,
            "energy_cost_modifier": combined_modifier_items,
            "skill_modifier": combined_modifier_items,
            "current_power": slot.current_power if slot is not None else None,
            "cooldown_remaining": slot.cooldown_remaining if slot is not None else None,
            "base_hit_count": hit_rule_result["hit_count"],
            "effective_hit_count": effective_hit_count,
            "hit_count_source": hit_rule_result["source"],
            "hit_count_modifier_delta": hit_count_modifier_delta,
            "hit_count_modifier_multiplier": str(hit_count_modifier_multiplier),
            "hit_rule": hit_rule_result.get("hit_rule"),
        }
        consume_result = self._consume_runtime_skill_energy_cost(
            event,
            effective_energy_cost=effective_energy_cost,
        )
        if consume_result:
            summary["energy_consumption"] = consume_result
        consumed_modifiers = self.consume_skill_modifier_effect_uses(
            event,
            energy_modifier["items"],
            reason="skill_use_cost_modifier_consumed",
        )
        if consumed_modifiers:
            summary["consumed_skill_modifier_effects"] = consumed_modifiers
        if slot is not None:
            response_listener_results = self._apply_response_success_runtime_listeners(event)
            if response_listener_results:
                summary["response_success_listener_results"] = response_listener_results
            hook_results = self._apply_executable_skill_runtime_hooks(event, skill, slot)
            if hook_results:
                summary["hook_results"] = hook_results
            listener_results = self._apply_other_skill_use_runtime_listeners(event, skill)
            if listener_results:
                summary["other_skill_use_listener_results"] = listener_results
        if charge_state["phase"] != "not_required":
            summary["charge"] = charge_state
            self._apply_charge_state_resolution(event, skill, charge_state)
        return summary

    def _resolve_skill_hit_count_for_event(self, event: BattleEvent) -> dict[str, Any]:
        """解析技能使用事件的当前连击数，供状态技能按连击数施加效果。"""
        payload = loads_json(event.payload_json, {})
        if not isinstance(payload, dict):
            payload = {}
        context = DamageFormulaContext(
            battle_id=event.battle_id,
            attacker_side=str(event.actor_side or ""),
            attacker_elf_id=str(event.actor_elf_id or ""),
            defender_side=str(
                event.target_side
                or EffectOperationExecutor._opposite_side(event.actor_side)
                or ""
            ),
            defender_elf_id=str(event.target_elf_id or ""),
            skill_id=event.skill_id,
            formula_type="attack",
            snapshot_payload=self._active_effect_snapshot_payload(event.battle_id),
        )
        details = HitRuleResolver(self.db).resolve_hit_rule(context, payload)
        hit_rule = details.get("hit_rule") if isinstance(details, dict) else None
        source = (
            hit_rule.get("source")
            if isinstance(hit_rule, dict) and isinstance(hit_rule.get("source"), str)
            else "context_default"
        )
        return {
            "hit_count": max(int(context.hit_count or 1), 1),
            "source": source,
            "hit_rule": hit_rule,
        }

    def consume_skill_modifier_effect_uses(
        self,
        event: BattleEvent,
        modifier_items: list[dict],
        *,
        reason: str,
    ) -> list[dict]:
        """消耗本次实际参与结算的一次性技能修正状态。"""
        results: list[dict] = []
        consumed_instance_ids: set[str] = set()
        for item in modifier_items:
            if not isinstance(item, dict):
                continue
            remaining_uses = item.get("remaining_uses")
            if remaining_uses is None:
                continue
            try:
                remaining_uses_int = int(remaining_uses)
            except (TypeError, ValueError):
                continue
            if remaining_uses_int <= 0:
                continue
            instance_id = item.get("effect_instance_id")
            if not isinstance(instance_id, str) or not instance_id:
                continue
            if instance_id in consumed_instance_ids:
                continue
            instance = self.db.get(BattleEffectInstance, instance_id)
            if (
                instance is None
                or instance.battle_id != event.battle_id
                or not instance.is_active
            ):
                continue
            definition = self.db.get(EffectDefinition, instance.effect_id)
            if definition is None or definition.deleted_at is not None:
                continue

            layers_before = instance.layers
            uses_before = instance.remaining_uses
            next_uses = max(int(instance.remaining_uses or remaining_uses_int) - 1, 0)
            instance.remaining_uses = next_uses
            instance.last_updated_turn = event.turn_number
            if next_uses <= 0:
                instance.is_active = False
                instance.layers = 0
            self.db.add(
                EffectChangeEvent(
                    event_id=f"effect_change_{uuid4().hex}",
                    battle_id=event.battle_id,
                    battle_event_id=event.event_id,
                    turn_number=event.turn_number,
                    change_type="consume_use" if next_uses > 0 else "clear",
                    effect_instance_id=instance.instance_id,
                    effect_id=definition.effect_id,
                    effect_name=definition.effect_name,
                    category=definition.category,
                    target_side=instance.owner_side,
                    target_elf_id=instance.owner_elf_id,
                    target_skill_slot_id=instance.owner_skill_slot_id,
                    owner_scope=instance.owner_scope,
                    layers_before=layers_before,
                    layers_after=instance.layers,
                    duration_before=uses_before,
                    duration_after=next_uses,
                    source_skill_id=event.skill_id,
                    source_elf_id=event.actor_elf_id,
                    condition_branch=None,
                    reason=reason,
                    source=EventSource.SYSTEM_CALCULATED.value,
                    recognition_confidence=1.0,
                    manual_override=False,
                )
            )
            consumed_instance_ids.add(instance_id)
            results.append(
                {
                    "status": "consumed",
                    "effect_id": definition.effect_id,
                    "effect_instance_id": instance.instance_id,
                    "remaining_uses_before": uses_before,
                    "remaining_uses_after": next_uses,
                    "layers_before": layers_before,
                    "layers_after": instance.layers,
                }
            )
        return results

    def _skill_dynamic_energy_cost_modifier(
        self,
        event: BattleEvent,
        skill: SkillDefinition,
    ) -> dict[str, Any]:
        """解析技能自身按目标状态层数变化的能耗分支。"""
        rule = loads_json(skill.damage_rule_json, {})
        if not isinstance(rule, dict):
            return {"energy_cost_delta": 0, "items": []}
        cost_rule = rule.get("dynamic_energy_cost_rule")
        if not isinstance(cost_rule, dict):
            return {"energy_cost_delta": 0, "items": []}

        if cost_rule.get("missing_hp_percent_step") is not None:
            return self._dynamic_energy_cost_from_missing_hp(event, skill, cost_rule)

        effect_ids = self._dynamic_cost_effect_ids(cost_rule)
        categories = self._dynamic_cost_categories(cost_rule)
        if not effect_ids and not categories:
            return {"energy_cost_delta": 0, "items": []}
        target_side = self._dynamic_cost_target_side(event, cost_rule)
        if target_side is None:
            return {"energy_cost_delta": 0, "items": []}
        battle = self.db.get(Battle, event.battle_id)
        if battle is None or battle.deleted_at is not None:
            return {"energy_cost_delta": 0, "items": []}
        target_elf_id = (
            battle.self_active_elf_id
            if target_side == Side.SELF.value
            else battle.enemy_active_elf_id
        )

        stmt = select(BattleEffectInstance).where(
            BattleEffectInstance.battle_id == event.battle_id,
            BattleEffectInstance.owner_side == target_side,
            BattleEffectInstance.is_active.is_(True),
        )
        if effect_ids:
            stmt = stmt.where(BattleEffectInstance.effect_id.in_(effect_ids))
        if categories:
            stmt = stmt.where(BattleEffectInstance.category.in_(categories))
        instances = self.db.scalars(stmt).all()
        total_layers = 0
        matched: list[dict[str, Any]] = []
        for instance in instances:
            if instance.owner_scope == "elf" and target_elf_id:
                if instance.owner_elf_id != target_elf_id:
                    continue
            layers = max(int(instance.layers or 0), 0)
            if layers <= 0:
                continue
            total_layers += layers
            matched.append(
                {
                    "effect_id": instance.effect_id,
                    "effect_instance_id": instance.instance_id,
                    "owner_scope": instance.owner_scope,
                    "owner_side": instance.owner_side,
                    "owner_elf_id": instance.owner_elf_id,
                    "layers": layers,
                }
            )
        if total_layers <= 0:
            return {"energy_cost_delta": 0, "items": []}

        delta_per_layer = int(cost_rule.get("energy_cost_delta_per_layer") or 0)
        delta = total_layers * delta_per_layer
        return {
            "energy_cost_delta": delta,
            "items": [
                {
                    "modifier_type": "dynamic_energy_cost_from_effect_layers",
                    "source": "skill_definition.damage_rule_json",
                    "skill_id": skill.skill_id,
                    "source_effect_ids": sorted(effect_ids),
                    "source_categories": sorted(categories),
                    "source_target": cost_rule.get("source_target"),
                    "layers": total_layers,
                    "energy_cost_delta": delta,
                    "matched_instances": matched,
                }
            ],
        }

    def _dynamic_energy_cost_from_missing_hp(
        self,
        event: BattleEvent,
        skill: SkillDefinition,
        cost_rule: dict[str, Any],
    ) -> dict[str, Any]:
        """按自身已损生命百分比动态修正本技能能耗。"""
        if event.actor_side is None or event.actor_elf_id is None:
            return {"energy_cost_delta": 0, "items": []}
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == event.battle_id,
                BattleElfState.side == event.actor_side,
                BattleElfState.elf_id == event.actor_elf_id,
            )
        ).first()
        if state is None or state.current_hp_percent is None:
            return {"energy_cost_delta": 0, "items": []}
        step = Decimal(str(cost_rule.get("missing_hp_percent_step") or 0))
        if step <= 0:
            return {"energy_cost_delta": 0, "items": []}
        missing = max(Decimal("100") - Decimal(str(state.current_hp_percent)), Decimal("0"))
        steps = int(missing // step)
        delta_per_step = int(cost_rule.get("energy_cost_delta_per_step") or 0)
        delta = steps * delta_per_step
        return {
            "energy_cost_delta": delta,
            "items": [
                {
                    "modifier_type": "dynamic_energy_cost_from_missing_hp_percent",
                    "source": "skill_definition.damage_rule_json",
                    "skill_id": skill.skill_id,
                    "hp_percent": str(state.current_hp_percent),
                    "missing_hp_percent": str(missing),
                    "step": str(step),
                    "steps": steps,
                    "energy_cost_delta": delta,
                }
            ],
        }

    @staticmethod
    def _dynamic_cost_effect_ids(cost_rule: dict[str, Any]) -> set[str]:
        source_effect_ids = cost_rule.get("source_effect_ids")
        if isinstance(source_effect_ids, str):
            return {source_effect_ids}
        if isinstance(source_effect_ids, list):
            return {str(item) for item in source_effect_ids if item is not None}
        effect_id = cost_rule.get("source_effect_id")
        return {str(effect_id)} if effect_id else set()

    @staticmethod
    def _dynamic_cost_categories(cost_rule: dict[str, Any]) -> set[str]:
        source_categories = cost_rule.get("source_categories")
        if isinstance(source_categories, str):
            return {source_categories}
        if isinstance(source_categories, list):
            return {str(item) for item in source_categories if item is not None}
        category = cost_rule.get("source_category")
        return {str(category)} if category else set()

    @staticmethod
    def _dynamic_cost_target_side(
        event: BattleEvent,
        cost_rule: dict[str, Any],
    ) -> str | None:
        source_target = str(cost_rule.get("source_target") or "enemy_side")
        if source_target in {"enemy_side", "opponent_side", "defender_side", "target_side"}:
            return event.target_side or EffectOperationExecutor._opposite_side(event.actor_side)
        if source_target in {"actor_side", "self_side", "attacker_side"}:
            return event.actor_side
        if source_target in {Side.SELF.value, Side.ENEMY.value}:
            return source_target
        return None

    def _skill_dynamic_use_count_modifier(
        self,
        event: BattleEvent,
        skill: SkillDefinition,
    ) -> dict[str, Any]:
        """解析技能自身的一回合多次使用分支；不同于连击段数。"""
        rule = loads_json(skill.damage_rule_json, {})
        if not isinstance(rule, dict):
            return {"use_count_delta": 0, "items": []}
        use_rule = rule.get("dynamic_use_count_rule")
        if not isinstance(use_rule, dict):
            return {"use_count_delta": 0, "items": []}
        condition = use_rule.get("condition")
        if isinstance(condition, str) and condition:
            payload = loads_json(event.payload_json, {})
            if not isinstance(payload, dict) or not self._payload_condition_is_true(
                payload,
                condition,
            ):
                return {"use_count_delta": 0, "items": []}
        delta = int(use_rule.get("use_count_delta") or use_rule.get("use_count_bonus") or 0)
        if delta == 0:
            return {"use_count_delta": 0, "items": []}
        return {
            "use_count_delta": delta,
            "items": [
                {
                    "modifier_type": "dynamic_use_count",
                    "source": "skill_definition.damage_rule_json",
                    "skill_id": skill.skill_id,
                    "condition": condition,
                    "use_count_delta": delta,
                    "requires_burst": condition in {"burst_active", "burst_triggered"},
                }
            ],
        }

    @staticmethod
    def _payload_condition_is_true(payload: dict[str, Any], condition: str) -> bool:
        """从事件 payload/condition_flags/manual_flags 判断条件是否为真。"""
        manual_flags = payload.get("manual_flags")
        condition_flags = payload.get("condition_flags")
        for value in (
            payload.get(condition),
            manual_flags.get(condition) if isinstance(manual_flags, dict) else None,
            condition_flags.get(condition) if isinstance(condition_flags, dict) else None,
        ):
            if value is True:
                return True
        return False

    def _apply_skill_use_mark_triggers(
        self,
        event: BattleEvent,
        skill_runtime_result: dict | None,
    ) -> list[dict]:
        """执行已确认的技能使用型印记触发。"""
        if event.actor_side is None:
            return []
        skill = self.db.get(SkillDefinition, event.skill_id) if event.skill_id else None
        if skill is None or skill.deleted_at is not None:
            return []
        effective_energy_cost = None
        if isinstance(skill_runtime_result, dict):
            effective_energy_cost = skill_runtime_result.get("effective_energy_cost")
        if effective_energy_cost is None:
            effective_energy_cost = max(skill.base_energy_cost or 0, 0)

        results: list[dict] = []
        active_marks = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == event.battle_id,
                BattleEffectInstance.owner_scope == "side",
                BattleEffectInstance.owner_side == event.actor_side,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()
        for instance in active_marks:
            definition = self.db.get(EffectDefinition, instance.effect_id)
            if definition is None or definition.deleted_at is not None:
                continue
            if definition.special_rule_id == "dragon_bite_mark":
                if int(effective_energy_cost or 0) != 3:
                    results.append(
                        {
                            "status": "skipped",
                            "reason": "dragon_bite_requires_3_energy_skill",
                            "effect_id": instance.effect_id,
                            "effect_instance_id": instance.instance_id,
                            "effective_energy_cost": effective_energy_cost,
                        }
                    )
                    continue
                layers = max(int(instance.layers or 0), 0) * 3
                if layers <= 0:
                    continue
                results.extend(
                    EffectOperationExecutor(self.db).execute_operations_for_event(
                        event,
                        [
                            {
                                "op_type": "apply_effect",
                                "effect_id": "effect_dual_attack_up_layered",
                                "target": "actor_side",
                                "layers": layers,
                                "condition": "always",
                                "timing": "on_skill_use",
                                "notes": (
                                    "龙噬印记：释放 3 能耗技能时获得双攻 +30%"
                                    "（每层 3 个 10% 层）。"
                                ),
                            }
                        ],
                    )
                )
        return results

    def _apply_end_turn_skill_runtime_hooks(
        self,
        *,
        battle: Battle,
        turn_number: int,
    ) -> list[dict]:
        """执行“在场回合末”技能槽持久钩子。"""
        active_pairs = [
            (Side.SELF.value, battle.self_active_elf_id),
            (Side.ENEMY.value, battle.enemy_active_elf_id),
        ]
        results: list[dict] = []
        for side, elf_id in active_pairs:
            if not elf_id:
                continue
            slots = self.db.scalars(
                select(BattleSkillSlot).where(
                    BattleSkillSlot.battle_id == battle.battle_id,
                    BattleSkillSlot.side == side,
                    BattleSkillSlot.elf_id == elf_id,
                )
            ).all()
            for slot in slots:
                skill = self.db.get(SkillDefinition, slot.skill_id)
                if skill is None or skill.deleted_at is not None:
                    continue
                rule = loads_json(skill.damage_rule_json, {})
                manual_review = rule.get("manual_review") if isinstance(rule, dict) else None
                hooks = (
                    manual_review.get("future_hooks")
                    if isinstance(manual_review, dict)
                    else None
                )
                if not isinstance(hooks, list):
                    continue
                for hook in hooks:
                    if (
                        not isinstance(hook, dict)
                        or hook.get("status") != "executable"
                        or hook.get("trigger") != "end_turn_in_field"
                    ):
                        continue
                    if (
                        hook.get("hook_type") == "persistent_skill_cost_modifier"
                        and hook.get("target") == "source_skill"
                    ):
                        before = (
                            slot.current_energy_cost
                            if slot.current_energy_cost is not None
                            else skill.base_energy_cost
                        )
                        delta = int(hook.get("cost_delta") or 0)
                        slot.current_energy_cost = max(int(before or 0) + delta, 0)
                        results.append(
                            {
                                "status": "executed",
                                "hook_type": hook.get("hook_type"),
                                "trigger": "end_turn_in_field",
                                "turn_number": turn_number,
                                "side": side,
                                "elf_id": elf_id,
                                "skill_id": skill.skill_id,
                                "slot_id": slot.slot_id,
                                "field": "current_energy_cost",
                                "before": before,
                                "after": slot.current_energy_cost,
                                "cost_delta": delta,
                            }
                        )
                    elif (
                        hook.get("hook_type") == "persistent_skill_power_modifier"
                        and hook.get("target") == "source_skill"
                    ):
                        before = (
                            slot.current_power
                            if slot.current_power is not None
                            else skill.base_power
                        )
                        delta = int(hook.get("power_add") or 0)
                        multiplier = hook.get("power_multiplier")
                        if multiplier is not None:
                            slot.current_power = max(
                                int(Decimal(str(before or 0)) * Decimal(str(multiplier))),
                                0,
                            )
                        else:
                            slot.current_power = max(int(before or 0) + delta, 0)
                        results.append(
                            {
                                "status": "executed",
                                "hook_type": hook.get("hook_type"),
                                "trigger": "end_turn_in_field",
                                "turn_number": turn_number,
                                "side": side,
                                "elf_id": elf_id,
                                "skill_id": skill.skill_id,
                                "slot_id": slot.slot_id,
                                "field": "current_power",
                                "before": before,
                                "after": slot.current_power,
                                "power_add": delta,
                                "power_multiplier": multiplier,
                            }
                        )
        return results

    def ensure_observed_skill_slot(self, event: BattleEvent) -> dict | None:
        """记录伤害事件中已确认出现的技能槽，不执行扣能或结构化技能效果。"""
        if event.skill_id is None or event.actor_side is None or event.actor_elf_id is None:
            return None
        if not event.skill_confirmed:
            return None
        skill = self.db.get(SkillDefinition, event.skill_id)
        if skill is None or skill.deleted_at is not None:
            return {"status": "skill_definition_missing", "skill_id": event.skill_id}
        slot, slot_created = self._ensure_runtime_skill_slot(event, skill)
        if slot is None:
            return {"status": "slot_not_recorded", "skill_id": skill.skill_id}
        return {
            "status": "recorded",
            "record_source": "damage_event",
            "skill_id": skill.skill_id,
            "slot_id": slot.slot_id,
            "slot_created": slot_created,
            "static_energy_cost": max(skill.base_energy_cost or 0, 0),
            "current_power": slot.current_power,
            "cooldown_remaining": slot.cooldown_remaining,
        }

    def _consume_runtime_skill_energy_cost(
        self,
        event: BattleEvent,
        *,
        effective_energy_cost: int,
    ) -> dict | None:
        """技能使用时按运行时费用扣能，并写入资源变化事件。"""
        if effective_energy_cost <= 0:
            return {"status": "skipped", "reason": "zero_energy_cost"}
        if event.actor_side is None or event.actor_elf_id is None:
            return None
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == event.battle_id,
                BattleElfState.side == event.actor_side,
                BattleElfState.elf_id == event.actor_elf_id,
            )
        ).first()
        if state is None or state.energy is None:
            return {"status": "skipped", "reason": "state_or_energy_missing"}

        before_value = state.energy
        after_value = max(before_value - effective_energy_cost, 0)
        state.energy = after_value
        self.db.add(
            ResourceChangeEvent(
                event_id=f"resource_event_{uuid4().hex}",
                battle_id=event.battle_id,
                battle_event_id=event.event_id,
                resource_type="energy",
                change_type="consume",
                source_side=event.actor_side,
                source_elf_id=event.actor_elf_id,
                target_side=event.actor_side,
                target_elf_id=event.actor_elf_id,
                value_type="value",
                value=float(effective_energy_cost),
                before_value=float(before_value),
                after_value=float(after_value),
                confidence=1.0,
                manual_override=False,
            )
        )
        return {
            "status": "consumed",
            "before_value": before_value,
            "after_value": after_value,
            "value": effective_energy_cost,
        }

    def _ensure_runtime_skill_slot(
        self,
        event: BattleEvent,
        skill: SkillDefinition,
    ) -> tuple[BattleSkillSlot | None, bool]:
        """确保已确认使用的技能有运行时技能槽，敌方未知技能会按发现顺序补槽。"""
        if event.actor_side is None or event.actor_elf_id is None:
            return None, False
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == event.battle_id,
                BattleElfState.side == event.actor_side,
                BattleElfState.elf_id == event.actor_elf_id,
            )
        ).first()
        if state is None:
            return None, False
        slot = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == event.battle_id,
                BattleSkillSlot.side == event.actor_side,
                BattleSkillSlot.elf_id == event.actor_elf_id,
                BattleSkillSlot.skill_id == skill.skill_id,
            )
        ).first()
        if slot is not None:
            self._append_skill_to_state_lists(
                state,
                skill.skill_id,
                confirmed=event.skill_confirmed,
            )
            return slot, False
        if not event.skill_confirmed:
            return None, False

        existing_indexes = list(
            self.db.scalars(
                select(BattleSkillSlot.slot_index).where(
                    BattleSkillSlot.battle_id == event.battle_id,
                    BattleSkillSlot.side == event.actor_side,
                    BattleSkillSlot.elf_id == event.actor_elf_id,
                )
            ).all()
        )
        next_index = max(existing_indexes) + 1 if existing_indexes else 0
        slot = BattleSkillSlot(
            slot_id=f"battle_skill_slot_{uuid4().hex}",
            battle_id=event.battle_id,
            side=event.actor_side,
            elf_id=event.actor_elf_id,
            slot_index=next_index,
            skill_id=skill.skill_id,
            active_effect_instance_ids_json=dumps_json([]),
            manual_override=False,
        )
        self.db.add(slot)
        self.db.flush()
        self._append_skill_to_state_lists(state, skill.skill_id, confirmed=event.skill_confirmed)
        return slot, True

    def _append_skill_to_state_lists(
        self,
        state: BattleElfState,
        skill_id: str,
        *,
        confirmed: bool,
    ) -> None:
        skill_ids = self._append_unique(loads_json(state.skill_ids_json, []), skill_id)
        state.skill_ids_json = dumps_json(skill_ids)
        if confirmed:
            confirmed_skill_ids = self._append_unique(
                loads_json(state.confirmed_skill_ids_json, []),
                skill_id,
            )
            state.confirmed_skill_ids_json = dumps_json(confirmed_skill_ids)

    def _apply_executable_skill_runtime_hooks(
        self,
        event: BattleEvent,
        skill: SkillDefinition,
        slot: BattleSkillSlot,
    ) -> list[dict]:
        """执行显式标记 executable 的简单技能槽钩子；reserved 只回显不执行。"""
        rule = loads_json(skill.damage_rule_json, {})
        if not isinstance(rule, dict):
            return []
        manual_review = rule.get("manual_review")
        hooks = manual_review.get("future_hooks") if isinstance(manual_review, dict) else None
        if not isinstance(hooks, list):
            return []
        payload = loads_json(event.payload_json, {})
        condition_flags = payload.get("condition_flags") if isinstance(payload, dict) else None
        if not isinstance(condition_flags, dict):
            condition_flags = {}

        results: list[dict] = []
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            hook_type = hook.get("hook_type")
            if hook_type == "response_success_skill_cost_listener":
                continue
            hook_is_confirmed_executable = hook_type in {
                "next_skill_charge_requirement_override",
            }
            if hook.get("status") != "executable" and not hook_is_confirmed_executable:
                results.append(
                    {
                        "status": "reserved",
                        "hook_type": hook_type,
                        "reason": "future_hook_not_executable",
                    }
                )
                continue
            if not self._skill_runtime_hook_triggered(hook, condition_flags):
                results.append(
                    {"status": "skipped", "hook_type": hook_type, "reason": "condition_false"}
                )
                continue
            if (
                hook_type == "persistent_skill_cost_modifier"
                and hook.get("target") == "source_skill"
            ):
                before = (
                    slot.current_energy_cost
                    if slot.current_energy_cost is not None
                    else skill.base_energy_cost
                )
                delta = int(hook.get("cost_delta") or 0)
                slot.current_energy_cost = max(int(before or 0) + delta, 0)
                results.append(
                    {
                        "status": "executed",
                        "hook_type": hook_type,
                        "field": "current_energy_cost",
                        "before": before,
                        "after": slot.current_energy_cost,
                    }
                )
            elif (
                hook_type == "persistent_skill_hit_count_modifier"
                and hook.get("target") == "source_skill"
            ):
                delta = int(hook.get("hit_count_delta") or hook.get("hit_count_bonus") or 0)
                if delta == 0:
                    results.append(
                        {"status": "skipped", "hook_type": hook_type, "reason": "zero_delta"}
                    )
                    continue
                effect_id = (
                    "effect_skill_slot_hit_count_up_persistent"
                    if delta > 0
                    else "effect_skill_slot_hit_count_down_persistent"
                )
                operation_results = EffectOperationExecutor(self.db).execute_operations_for_event(
                    event,
                    [
                        {
                            "op_type": "apply_effect",
                            "effect_id": effect_id,
                            "target": "source_skill",
                            "layers": abs(delta),
                            "condition": "always",
                            "timing": "on_skill_use",
                        }
                    ],
                )
                results.append(
                    {
                        "status": "executed",
                        "hook_type": hook_type,
                        "effect_id": effect_id,
                        "hit_count_delta": delta,
                        "operation_results": operation_results,
                    }
                )
            elif (
                hook_type == "persistent_skill_power_modifier"
                and hook.get("target") == "source_skill"
            ):
                before = slot.current_power if slot.current_power is not None else skill.base_power
                delta = int(hook.get("power_add") or 0)
                multiplier = hook.get("power_multiplier")
                if multiplier is not None:
                    slot.current_power = max(
                        int(Decimal(str(before or 0)) * Decimal(str(multiplier))),
                        0,
                    )
                else:
                    slot.current_power = max(int(before or 0) + delta, 0)
                results.append(
                    {
                        "status": "executed",
                        "hook_type": hook_type,
                        "field": "current_power",
                        "before": before,
                        "after": slot.current_power,
                        "power_multiplier": multiplier,
                    }
                )
            elif (
                hook_type == "reset_skill_cost_modifier"
                and hook.get("target") == "source_skill"
            ):
                before = (
                    slot.current_energy_cost
                    if slot.current_energy_cost is not None
                    else skill.base_energy_cost
                )
                slot.current_energy_cost = max(int(skill.base_energy_cost or 0), 0)
                results.append(
                    {
                        "status": "executed",
                        "hook_type": hook_type,
                        "field": "current_energy_cost",
                        "before": before,
                        "after": slot.current_energy_cost,
                    }
                )
            elif hook_type == "next_skill_charge_requirement_override":
                if hook.get("require_charge") is not False:
                    results.append(
                        {
                            "status": "skipped",
                            "hook_type": hook_type,
                            "reason": "unsupported_charge_override",
                        }
                    )
                    continue
                operation_results = EffectOperationExecutor(self.db).execute_operations_for_event(
                    event,
                    [
                        {
                            "op_type": "apply_effect",
                            "effect_id": "effect_next_charge_free",
                            "target": "actor_side",
                            "layers": 1,
                            "condition": "always",
                            "timing": "on_skill_use",
                        }
                    ],
                )
                results.append(
                    {
                        "status": "executed",
                        "hook_type": hook_type,
                        "effect_id": "effect_next_charge_free",
                        "operation_results": operation_results,
                    }
                )
            else:
                results.append(
                    {"status": "skipped", "hook_type": hook_type, "reason": "unsupported_hook"}
                )
        return results

    def _apply_response_success_runtime_listeners(self, event: BattleEvent) -> list[dict]:
        """处理“本精灵应对成功后，指定技能槽费用变化”的监听。"""
        if event.actor_side is None or event.actor_elf_id is None:
            return []
        payload = loads_json(event.payload_json, {})
        condition_flags = payload.get("condition_flags") if isinstance(payload, dict) else None
        if not isinstance(condition_flags, dict):
            condition_flags = {}
        if not any(
            condition_flags.get(key) is True
            for key in (
                "response_attack_success",
                "response_defense_success",
                "response_status_success",
            )
        ):
            return []
        slots = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == event.battle_id,
                BattleSkillSlot.side == event.actor_side,
                BattleSkillSlot.elf_id == event.actor_elf_id,
            )
        ).all()
        results: list[dict] = []
        for slot in slots:
            skill = self.db.get(SkillDefinition, slot.skill_id)
            if skill is None or skill.deleted_at is not None:
                continue
            rule = loads_json(skill.damage_rule_json, {})
            manual_review = rule.get("manual_review") if isinstance(rule, dict) else None
            hooks = manual_review.get("future_hooks") if isinstance(manual_review, dict) else None
            if not isinstance(hooks, list):
                continue
            for hook in hooks:
                if not isinstance(hook, dict) or hook.get("status") != "executable":
                    continue
                if hook.get("hook_type") != "response_success_skill_cost_listener":
                    continue
                if not self._skill_runtime_hook_triggered(hook, condition_flags):
                    continue
                before = (
                    slot.current_energy_cost
                    if slot.current_energy_cost is not None
                    else skill.base_energy_cost
                )
                delta = int(hook.get("cost_delta") or 0)
                slot.current_energy_cost = max(int(before or 0) + delta, 0)
                results.append(
                    {
                        "status": "executed",
                        "hook_type": hook.get("hook_type"),
                        "trigger": hook.get("trigger"),
                        "listener_skill_id": skill.skill_id,
                        "slot_id": slot.slot_id,
                        "field": "current_energy_cost",
                        "before": before,
                        "after": slot.current_energy_cost,
                        "cost_delta": delta,
                    }
                )
        return results

    def _apply_other_skill_use_runtime_listeners(
        self,
        event: BattleEvent,
        used_skill: SkillDefinition,
    ) -> list[dict]:
        """处理“使用其他指定系别技能后，本技能槽获得永久修正”的监听。"""
        if event.actor_side is None or event.actor_elf_id is None:
            return []
        slots = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == event.battle_id,
                BattleSkillSlot.side == event.actor_side,
                BattleSkillSlot.elf_id == event.actor_elf_id,
                BattleSkillSlot.skill_id != used_skill.skill_id,
            )
        ).all()
        results: list[dict] = []
        for slot in slots:
            listener_skill = self.db.get(SkillDefinition, slot.skill_id)
            if listener_skill is None or listener_skill.deleted_at is not None:
                continue
            rule = loads_json(listener_skill.damage_rule_json, {})
            manual_review = rule.get("manual_review") if isinstance(rule, dict) else None
            hooks = manual_review.get("future_hooks") if isinstance(manual_review, dict) else None
            if not isinstance(hooks, list):
                continue
            for hook in hooks:
                if not isinstance(hook, dict):
                    continue
                if hook.get("status") != "executable":
                    continue
                if hook.get("trigger") != "other_element_skill_use":
                    continue
                if hook.get("element_type") is not None and not element_type_matches(
                    hook["element_type"],
                    used_skill.element_type,
                ):
                    continue
                if hook.get("hook_type") == "persistent_skill_power_modifier":
                    before = (
                        slot.current_power
                        if slot.current_power is not None
                        else listener_skill.base_power
                    )
                    multiplier = hook.get("power_multiplier")
                    power_add = int(hook.get("power_add") or 0)
                    if multiplier is not None:
                        multiplier_decimal = Decimal(str(multiplier))
                        slot.current_power = max(
                            int(Decimal(str(before or 0)) * multiplier_decimal),
                            0,
                        )
                    else:
                        multiplier_decimal = Decimal("1")
                        slot.current_power = max(int(before or 0) + power_add, 0)
                    results.append(
                        {
                            "status": "executed",
                            "hook_type": hook.get("hook_type"),
                            "trigger": "other_element_skill_use",
                            "used_skill_id": used_skill.skill_id,
                            "listener_skill_id": listener_skill.skill_id,
                            "slot_id": slot.slot_id,
                            "field": "current_power",
                            "before": before,
                            "after": slot.current_power,
                            "power_multiplier": str(multiplier),
                            "power_add": power_add,
                        }
                    )
        return results

    def apply_damage_taken_runtime_listeners(
        self,
        *,
        battle_event: BattleEvent,
        defender_side: str | None,
        defender_elf_id: str | None,
        damage_value: int | None,
    ) -> list[dict]:
        """处理“本精灵受伤后，本技能槽获得永久修正”的监听。"""
        if (
            defender_side is None
            or defender_elf_id is None
            or not damage_value
            or damage_value <= 0
        ):
            return []
        payload = loads_json(battle_event.payload_json, {})
        if not isinstance(payload, dict):
            payload = {}
        condition_flags = payload.get("condition_flags") if isinstance(payload, dict) else None
        if not isinstance(condition_flags, dict):
            condition_flags = {}
        for key in (
            "response_attack_success",
            "response_defense_success",
            "response_status_success",
        ):
            if payload.get(key) is True:
                condition_flags[key] = True
            elif payload.get(key) is False:
                condition_flags.setdefault(key, False)
        damage_hit_count = max(int(payload.get("hit_count") or 1), 1)
        slots = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == battle_event.battle_id,
                BattleSkillSlot.side == defender_side,
                BattleSkillSlot.elf_id == defender_elf_id,
            )
        ).all()
        results: list[dict] = []
        for slot in slots:
            skill = self.db.get(SkillDefinition, slot.skill_id)
            if skill is None or skill.deleted_at is not None:
                continue
            rule = loads_json(skill.damage_rule_json, {})
            manual_review = rule.get("manual_review") if isinstance(rule, dict) else None
            hooks = manual_review.get("future_hooks") if isinstance(manual_review, dict) else None
            if not isinstance(hooks, list):
                continue
            for hook in hooks:
                if not isinstance(hook, dict) or hook.get("status") != "executable":
                    continue
                trigger = hook.get("trigger")
                if trigger == "damage_taken_resisted":
                    if condition_flags.get("damage_resisted") is not True:
                        continue
                elif trigger != "damage_taken":
                    continue
                if not self._skill_runtime_hook_triggered(hook, condition_flags):
                    continue
                if (
                    hook.get("requires_defense_skill_used") is True
                    and payload.get("defense_skill_id") != skill.skill_id
                ):
                    continue
                if hook.get("hook_type") == "persistent_skill_cost_modifier":
                    before = slot.current_energy_cost if slot.current_energy_cost is not None else (
                        skill.base_energy_cost
                    )
                    delta = int(hook.get("cost_delta") or 0)
                    slot.current_energy_cost = max(int(before or 0) + delta, 0)
                    results.append(
                        {
                            "status": "executed",
                            "hook_type": hook.get("hook_type"),
                            "trigger": "damage_taken",
                            "listener_skill_id": skill.skill_id,
                            "slot_id": slot.slot_id,
                            "field": "current_energy_cost",
                            "before": before,
                            "after": slot.current_energy_cost,
                            "cost_delta": delta,
                        }
                    )
                elif hook.get("hook_type") == "persistent_skill_power_modifier":
                    before = (
                        slot.current_power
                        if slot.current_power is not None
                        else skill.base_power
                    )
                    per_hit = hook.get("per_damage_hit") is True
                    delta = int(hook.get("power_add") or 0)
                    total_delta = delta * damage_hit_count if per_hit else delta
                    slot.current_power = max(int(before or 0) + total_delta, 0)
                    results.append(
                        {
                            "status": "executed",
                            "hook_type": hook.get("hook_type"),
                            "trigger": trigger,
                            "listener_skill_id": skill.skill_id,
                            "slot_id": slot.slot_id,
                            "field": "current_power",
                            "before": before,
                            "after": slot.current_power,
                            "power_add": total_delta,
                            "damage_hit_count": damage_hit_count,
                        }
                    )
                elif hook.get("hook_type") == "apply_effect":
                    layers = int(hook.get("layers") or 0)
                    layers += damage_hit_count * int(hook.get("layers_per_damage_hit") or 0)
                    if layers <= 0:
                        results.append(
                            {
                                "status": "skipped",
                                "hook_type": hook.get("hook_type"),
                                "reason": "zero_layers",
                                "listener_skill_id": skill.skill_id,
                            }
                        )
                        continue
                    operation_results = EffectOperationExecutor(
                        self.db
                    ).execute_operations_for_event(
                        battle_event,
                        [
                            {
                                "op_type": "apply_effect",
                                "effect_id": hook.get("effect_id"),
                                "target": hook.get("target") or "target_side",
                                "layers": layers,
                                "condition": "always",
                                "timing": "after_damage",
                            }
                        ],
                    )
                    results.append(
                        {
                            "status": "executed",
                            "hook_type": hook.get("hook_type"),
                            "trigger": "damage_taken",
                            "listener_skill_id": skill.skill_id,
                            "damage_hit_count": damage_hit_count,
                            "layers": layers,
                            "operation_results": operation_results,
                        }
                    )
        return results

    @staticmethod
    def _skill_runtime_hook_triggered(hook: dict, condition_flags: dict) -> bool:
        trigger = hook.get("trigger") or hook.get("condition") or "after_skill_use"
        if trigger in {None, "after_skill_use"}:
            return True
        if isinstance(trigger, str) and (
            trigger.startswith("response_")
            or trigger in {"burst_active", "burst_triggered"}
        ):
            return condition_flags.get(trigger) is True
        if trigger == "any_response_success":
            return any(
                condition_flags.get(key) is True
                for key in (
                    "response_attack_success",
                    "response_defense_success",
                    "response_status_success",
                )
            )
        return False

    @staticmethod
    def _append_unique(value: object, item: str) -> list[str]:
        items = [str(existing) for existing in value] if isinstance(value, list) else []
        if item not in items:
            items.append(item)
        return items

    def _consume_skill_energy_cost(self, event: BattleEvent) -> None:
        """技能使用时先扣除技能定义里的基础能耗，并写入资源变化事件。"""
        if event.skill_id is None or event.actor_side is None or event.actor_elf_id is None:
            return
        skill = self.db.get(SkillDefinition, event.skill_id)
        if skill is None or skill.deleted_at is not None or skill.base_energy_cost <= 0:
            return
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == event.battle_id,
                BattleElfState.side == event.actor_side,
                BattleElfState.elf_id == event.actor_elf_id,
            )
        ).first()
        if state is None or state.energy is None:
            return

        before_value = state.energy
        after_value = max(before_value - skill.base_energy_cost, 0)
        state.energy = after_value
        self.db.add(
            ResourceChangeEvent(
                event_id=f"resource_event_{uuid4().hex}",
                battle_id=event.battle_id,
                battle_event_id=event.event_id,
                resource_type="energy",
                change_type="consume",
                source_side=event.actor_side,
                source_elf_id=event.actor_elf_id,
                target_side=event.actor_side,
                target_elf_id=event.actor_elf_id,
                value_type="value",
                value=float(skill.base_energy_cost),
                before_value=float(before_value),
                after_value=float(after_value),
                confidence=1.0,
                manual_override=False,
            )
        )

    def void_event(
        self,
        battle_id: str,
        event_id: str,
        payload: BattleEventVoidInput,
    ) -> BattleEvent:
        """作废历史事件，并可追加一条审计事件。"""
        self.require_battle(battle_id)
        target = self._require_event(battle_id, event_id)
        if target.is_voided:
            return target
        target.is_voided = True
        target.notes = self._append_note(target.notes, f"作废原因：{payload.reason or '未填写'}")
        if payload.create_audit_event:
            audit_event = BattleEvent(
                event_id=f"event_{uuid4().hex}",
                battle_id=battle_id,
                turn_number=target.turn_number,
                action_order=target.action_order,
                event_type="event_voided",
                actor_side=target.actor_side,
                actor_elf_id=target.actor_elf_id,
                target_side=target.target_side,
                target_elf_id=target.target_elf_id,
                source=EventSource.MANUAL_INPUT.value,
                manual_override=True,
                corrected_event_id=target.event_id,
                payload_json=dumps_json(
                    {"voided_event_id": target.event_id, "reason": payload.reason}
                ),
                notes=payload.reason,
            )
            self.db.add(audit_event)
            self.db.flush()
            snapshot = SnapshotService(self.db).create_effect_snapshot(
                battle_id,
                audit_event.turn_number,
                source_event_id=audit_event.event_id,
                commit=False,
            )
            audit_event.snapshot_id = snapshot.snapshot_id
        self.db.commit()
        self.db.refresh(target)
        return target

    def correct_event(
        self,
        battle_id: str,
        event_id: str,
        payload: BattleEventCorrectInput,
    ) -> BattleEvent:
        """创建一条修正事件，并按需作废原事件。"""
        self.require_battle(battle_id)
        original = self._require_event(battle_id, event_id)
        if payload.void_original:
            original.is_voided = True
            original.notes = self._append_note(
                original.notes,
                f"被修正：{payload.reason or '未填写'}",
            )
        replacement = payload.replacement_event
        replacement.corrected_event_id = event_id
        replacement.manual_override = True
        if payload.reason and replacement.notes:
            replacement.notes = f"{replacement.notes}；修正原因：{payload.reason}"
        elif payload.reason:
            replacement.notes = f"修正原因：{payload.reason}"
        return self.create_event(battle_id, replacement)

    def replay_from_event(self, battle_id: str, event_id: str) -> BattleReplayResult:
        """从事件流重建战斗派生状态。"""
        return BattleReplayResult(
            **EventReplayService(self.db).replay_from_event(battle_id, event_id)
        )

    def require_battle(self, battle_id: str) -> Battle:
        """读取战斗并统一校验软删除。"""
        battle = self.db.get(Battle, battle_id)
        if battle is None or battle.deleted_at is not None:
            raise LookupError(f"战斗不存在：{battle_id}")
        return battle

    def _require_event(self, battle_id: str, event_id: str) -> BattleEvent:
        """读取某场战斗内的事件。"""
        event = self.db.get(BattleEvent, event_id)
        if event is None or event.battle_id != battle_id:
            raise LookupError(f"事件不存在：{event_id}")
        return event

    @staticmethod
    def _append_note(old_note: str | None, extra_note: str) -> str:
        """追加备注，避免覆盖历史人工说明。"""
        if old_note:
            return f"{old_note}；{extra_note}"
        return extra_note

    @staticmethod
    def _settlement_status(settlement_events: list[dict]) -> str:
        """根据自动结算结果汇总本次结束回合状态。"""
        if not settlement_events:
            return "settled"
        statuses = {str(item.get("status")) for item in settlement_events}
        if statuses <= {"settled", "checked"}:
            return "settled"
        if "settled" in statuses or "checked" in statuses:
            return "partial"
        return "partial"

    def _clear_runtime_data(self, battle_id: str) -> None:
        """重录阵容前清理第一阶段运行时数据。"""
        self.db.execute(delete(BattleSkillSlot).where(BattleSkillSlot.battle_id == battle_id))
        self.db.execute(
            delete(EnemyPanelEstimateEvidence).where(
                EnemyPanelEstimateEvidence.battle_id == battle_id
            )
        )
        self.db.execute(delete(EnemyPanelEstimate).where(EnemyPanelEstimate.battle_id == battle_id))
        self.db.execute(delete(BattleElfState).where(BattleElfState.battle_id == battle_id))

    def _create_self_elf_state(self, battle_id: str, item, elf: ElfDefinition) -> BattleElfState:
        """根据己方配置创建 BattleElfState 和技能槽。"""
        if item.build_id is None:
            raise ValueError(f"己方精灵必须指定 build_id：{item.elf_id}")
        build = self.db.get(PlayerElfBuild, item.build_id)
        if build is None or build.deleted_at is not None:
            raise ValueError(f"己方配置不存在：{item.build_id}")
        if build.elf_id != item.elf_id:
            raise ValueError("build_id 对应精灵与 lineup.elf_id 不一致")

        final_stats = loads_json(build.final_stats_json, {})
        build_skill_ids = self._load_build_skill_ids(build.build_id)
        skill_ids = self._with_available_default_skill_ids(build_skill_ids)
        self._create_battle_skill_slots(battle_id, item.side, item.elf_id, build_skill_ids)

        return BattleElfState(
            state_id=f"battle_elf_state_{uuid4().hex}",
            battle_id=battle_id,
            side=item.side,
            elf_id=item.elf_id,
            elf_name=elf.elf_name,
            avatar=elf.avatar,
            nature_id=build.nature_id,
            individual_talent_distribution_json=build.individual_talent_distribution_json,
            panel_stats_json=build.final_stats_json or dumps_json({}),
            current_hp_value=final_stats.get("hp") if isinstance(final_stats, dict) else None,
            current_hp_percent=100.0,
            energy=DEFAULT_INITIAL_ENERGY,
            skill_ids_json=dumps_json(skill_ids),
            confirmed_skill_ids_json=dumps_json(skill_ids),
            active_effect_instance_ids_json=dumps_json([]),
            is_active_elf=item.is_active_elf,
            is_defeated=False,
            last_switch_turn=0 if item.is_active_elf else None,
            manual_override=True,
        )

    def _create_enemy_elf_state(self, battle_id: str, item, elf: ElfDefinition) -> BattleElfState:
        """根据敌方精灵 ID 创建未知配置运行时状态。"""
        possible_skill_ids = self._with_available_default_skill_ids(list(
            self.db.scalars(
                select(ElfLearnableSkill.skill_id)
                .where(ElfLearnableSkill.elf_id == item.elf_id)
                .order_by(ElfLearnableSkill.skill_id)
            ).all()
        ))
        return BattleElfState(
            state_id=f"battle_elf_state_{uuid4().hex}",
            battle_id=battle_id,
            side=item.side,
            elf_id=item.elf_id,
            elf_name=elf.elf_name,
            avatar=elf.avatar,
            nature_id=None,
            individual_talent_distribution_json=None,
            panel_stats_json=dumps_json(
                {
                    "hp": None,
                    "physical_attack": None,
                    "physical_defense": None,
                    "magic_attack": None,
                    "magic_defense": None,
                    "speed": None,
                }
            ),
            current_hp_value=None,
            current_hp_percent=100.0,
            energy=DEFAULT_INITIAL_ENERGY,
            skill_ids_json=dumps_json(possible_skill_ids),
            confirmed_skill_ids_json=dumps_json([]),
            active_effect_instance_ids_json=dumps_json([]),
            is_active_elf=item.is_active_elf,
            is_defeated=False,
            last_switch_turn=0 if item.is_active_elf else None,
            manual_override=True,
        )

    def _create_battle_skill_slots(
        self,
        battle_id: str,
        side: str,
        elf_id: str,
        skill_ids: list[str],
    ) -> None:
        """为己方确定技能创建战斗技能槽。"""
        for slot_index, skill_id in enumerate(skill_ids):
            self.db.add(
                BattleSkillSlot(
                    slot_id=f"battle_skill_slot_{uuid4().hex}",
                    battle_id=battle_id,
                    side=side,
                    elf_id=elf_id,
                    slot_index=slot_index,
                    skill_id=skill_id,
                    active_effect_instance_ids_json=dumps_json([]),
                    manual_override=True,
                )
            )

    def _switch_rule_conflicts(
        self,
        *,
        battle_id: str,
        side: str,
        leaving_elf_id: str | None,
    ) -> list[dict[str, Any]]:
        """检测换宠锁定，仅返回规则冲突提示，不阻止切换。"""
        conflicts: list[dict[str, Any]] = []
        instances = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()
        for instance in instances:
            if instance.owner_scope == "side" and instance.owner_side != side:
                continue
            if instance.owner_scope == "elf" and (
                instance.owner_side != side or instance.owner_elf_id != leaving_elf_id
            ):
                continue
            if instance.owner_scope not in {"field", "side", "elf"}:
                continue
            definition = self.db.get(EffectDefinition, instance.effect_id)
            if definition is None or definition.deleted_at is not None:
                continue
            action_rule = loads_json(definition.action_modifier_json, {})
            if not isinstance(action_rule, dict):
                action_rule = {}
            switch_lock = action_rule.get("switch_lock") or action_rule.get("lock_switch")
            if not switch_lock and definition.special_rule_id not in {"switch_lock", "lock_switch"}:
                continue
            conflicts.append(
                {
                    "conflict_type": "switch_lock",
                    "severity": "warning",
                    "message": "当前存在换宠锁定状态；本系统只提示冲突，不拦截手动切换。",
                    "effect_id": definition.effect_id,
                    "effect_name": definition.effect_name,
                    "effect_instance_id": instance.instance_id,
                    "owner_scope": instance.owner_scope,
                    "owner_side": instance.owner_side,
                    "owner_elf_id": instance.owner_elf_id,
                }
            )
        return conflicts

    def _set_active_elf(self, battle_id: str, side: str, elf_id: str, turn_number: int) -> None:
        """设置某阵营当前上场精灵，并取消同阵营其他精灵的上场标记。"""
        states = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle_id,
                BattleElfState.side == side,
            )
        ).all()
        if not any(state.elf_id == elf_id for state in states):
            raise ValueError(f"该战斗中不存在 {side} 精灵：{elf_id}")
        for state in states:
            state.is_active_elf = state.elf_id == elf_id
            if state.is_active_elf:
                state.last_switch_turn = turn_number

    def _load_build_skill_ids(self, build_id: str) -> list[str]:
        """读取己方配置技能槽。"""
        return list(
            self.db.scalars(
                select(PlayerElfBuildSkill.skill_id)
                .where(PlayerElfBuildSkill.build_id == build_id)
                .order_by(PlayerElfBuildSkill.slot_index)
            ).all()
        )

    def _with_available_default_skill_ids(self, skill_ids: list[str]) -> list[str]:
        """只在核心默认技能已入库时，把它加入运行时可用技能列表。"""
        skill = self.db.get(SkillDefinition, DEFAULT_COMMON_SKILL_ID)
        if skill is None or skill.deleted_at is not None:
            return skill_ids
        return append_default_common_skill_ids(skill_ids)

    def _require_elf(self, elf_id: str) -> ElfDefinition:
        """读取精灵定义。"""
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None or elf.deleted_at is not None:
            raise ValueError(f"精灵不存在：{elf_id}")
        return elf

    @staticmethod
    def _validate_lineup(payload: LineupInput) -> None:
        """校验阵容输入，确保每方最多一个首发。"""
        active_by_side = {Side.SELF.value: 0, Side.ENEMY.value: 0}
        count_by_side = {Side.SELF.value: 0, Side.ENEMY.value: 0}
        seen: set[tuple[str, str]] = set()
        for item in payload.elves:
            if item.side not in count_by_side:
                raise ValueError(f"未知阵营：{item.side}")
            count_by_side[item.side] += 1
            key = (item.side, item.elf_id)
            if key in seen:
                raise ValueError(f"阵容中重复出现精灵：{item.side}/{item.elf_id}")
            seen.add(key)
            if item.is_active_elf:
                active_by_side[item.side] = active_by_side.get(item.side, 0) + 1
        if count_by_side[Side.SELF.value] > 6 or count_by_side[Side.ENEMY.value] > 6:
            raise ValueError("每个阵营最多只能录入 6 只精灵")
        if active_by_side[Side.SELF.value] > 1 or active_by_side[Side.ENEMY.value] > 1:
            raise ValueError("每个阵营最多只能设置一个首发精灵")
