"""
伤害事件服务。

第一阶段只负责事实记录、快照绑定和公式占位返回。伤害公式尚未确认，
因此不会根据伤害事件排除任何候选配置。
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.formula_context import DamageFormulaContext, PanelStats
from app.calculation.rule_resolver import RuleResolver
from app.core.enums import BattleEventType, DamageDisplayType, EventSource
from app.inference.inference_engine import InferenceEngine
from app.models.battle import Battle, BattleElfState
from app.models.event import BattleEvent, DamageEvent, ResourceChangeEvent
from app.schemas.event import DamageEventCreate, DamageEventCreateResult
from app.services.battle_service import BattleService
from app.services.snapshot_service import SnapshotService
from app.services.turn_settlement_service import TurnSettlementService
from app.utils.json import dumps_json, loads_json


class DamageEventService:
    """伤害事件业务服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_damage_event(
        self,
        battle_id: str,
        payload: DamageEventCreate,
    ) -> DamageEventCreateResult:
        """
        创建伤害事件、状态快照并调用推算占位引擎。

        处理顺序：
        1. 创建 BattleEvent；
        2. 创建事件发生瞬间的 BattleEffectSnapshot；
        3. 创建 DamageEvent；
        4. 构造 DamageFormulaContext；
        5. 调用 InferenceEngine，返回 formula_unavailable；
        6. 可选更新防御方生命百分比。
        """
        battle = BattleService(self.db).require_battle(battle_id)
        turn_number = payload.turn_number if payload.turn_number is not None else battle.turn_number
        total_damage = self._resolve_total_damage(payload)
        hp_percent_delta = self._resolve_hp_percent_delta(payload)
        rule_payload = payload.model_dump(mode="json")
        if self._should_resolve_rules(rule_payload):
            rule_payload["resolve_rules"] = True

        battle_event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=turn_number,
            event_type=self._event_type_for(payload.damage_display_type),
            actor_side=payload.attacker_side,
            actor_elf_id=payload.attacker_elf_id,
            target_side=payload.defender_side,
            target_elf_id=payload.defender_elf_id,
            skill_id=payload.skill_id,
            skill_confirmed=payload.skill_confirmed,
            source=EventSource.MANUAL_INPUT.value,
            manual_override=True,
            payload_json=dumps_json(payload.model_dump(mode="json")),
            notes=payload.notes,
        )
        self.db.add(battle_event)
        self.db.flush()

        snapshot = SnapshotService(self.db).create_effect_snapshot(
            battle_id=battle_id,
            turn_number=turn_number,
            source_event_id=battle_event.event_id,
            commit=False,
        )
        battle_event.snapshot_id = snapshot.snapshot_id

        damage_event = DamageEvent(
            event_id=f"damage_event_{uuid4().hex}",
            battle_id=battle_id,
            battle_event_id=battle_event.event_id,
            attacker_side=payload.attacker_side,
            attacker_elf_id=payload.attacker_elf_id,
            defender_side=payload.defender_side,
            defender_elf_id=payload.defender_elf_id,
            skill_id=payload.skill_id,
            damage_display_type=payload.damage_display_type.value,
            damage_value=total_damage,
            final_total_damage_value=payload.final_total_damage_value,
            per_hit_damage_value=payload.per_hit_damage_value,
            hit_count=payload.hit_count,
            computed_total_damage_value=self._computed_combo_total(payload),
            combo_count_source=payload.combo_count_source,
            combo_confidence=payload.combo_confidence,
            hp_percent_before=payload.hp_percent_before,
            hp_percent_after=payload.hp_percent_after,
            hp_percent_delta=hp_percent_delta,
            enemy_hp_percent_damage=payload.enemy_hp_percent_damage or hp_percent_delta,
            calculation_confidence=0.0,
            manual_override=True,
        )
        self.db.add(damage_event)
        self.db.flush()

        attacker_state = self._get_elf_state(
            battle_id=battle_id,
            side=payload.attacker_side,
            elf_id=payload.attacker_elf_id,
        )
        defender_state = self._get_elf_state(
            battle_id=battle_id,
            side=payload.defender_side,
            elf_id=payload.defender_elf_id,
        )
        defender_panel_stats = self._panel_stats_from_state(defender_state)

        context = DamageFormulaContext(
            battle_id=battle_id,
            damage_event_id=damage_event.event_id,
            battle_event_id=battle_event.event_id,
            snapshot_id=snapshot.snapshot_id,
            attacker_side=payload.attacker_side,
            attacker_elf_id=payload.attacker_elf_id,
            defender_side=payload.defender_side,
            defender_elf_id=payload.defender_elf_id,
            skill_id=payload.skill_id,
            defense_skill_id=payload.defense_skill_id,
            response_attack_success=payload.response_attack_success,
            response_defense_success=payload.response_defense_success,
            response_status_success=payload.response_status_success,
            attacker_panel_stats=self._panel_stats_from_state(attacker_state),
            defender_panel_stats=defender_panel_stats,
            defender_max_hp=defender_panel_stats.hp if defender_panel_stats is not None else None,
            damage_display_type=payload.damage_display_type.value,
            observed_damage_value=total_damage,
            observed_hp_percent_delta=hp_percent_delta,
            snapshot_payload=loads_json(snapshot.full_snapshot_json, []),
            notes=payload.notes,
        )
        context = RuleResolver(self.db).resolve_damage_context(context, rule_payload)
        damage_event.formula_context_json = dumps_json(context)
        inference_result = InferenceEngine(self.db).process_damage_event(
            damage_event=damage_event,
            context=context,
        )
        self._create_resource_change_for_damage(
            battle_id=battle_id,
            battle_event_id=battle_event.event_id,
            payload=payload,
            total_damage=total_damage,
            hp_percent_delta=hp_percent_delta,
        )
        self._update_defender_hp_state(battle, payload, total_damage)
        post_settlement_events = TurnSettlementService(self.db).settle_post_attack(
            battle=battle,
            turn_number=turn_number,
            trigger_battle_event_id=battle_event.event_id,
            attacker_side=payload.attacker_side,
            attacker_elf_id=payload.attacker_elf_id,
            defender_side=payload.defender_side,
            defender_elf_id=payload.defender_elf_id,
            trigger_skill_id=payload.skill_id,
        )

        self.db.commit()
        self.db.refresh(battle_event)
        self.db.refresh(damage_event)
        return DamageEventCreateResult(
            battle_event=battle_event,
            damage_event=damage_event,
            snapshot_id=snapshot.snapshot_id,
            inference_result=inference_result,
            post_settlement_events=post_settlement_events,
        )

    @staticmethod
    def _resolve_total_damage(payload: DamageEventCreate) -> int | None:
        """根据伤害显示类型得出总伤害。"""
        if payload.damage_display_type == DamageDisplayType.SINGLE_DAMAGE:
            return payload.damage_value
        if payload.damage_display_type == DamageDisplayType.VISUAL_TOTAL_DAMAGE:
            return payload.final_total_damage_value
        if payload.damage_display_type == DamageDisplayType.COMBO_REPEATED_DAMAGE:
            return None
        return payload.damage_value

    @staticmethod
    def _computed_combo_total(payload: DamageEventCreate) -> int | None:
        """连击伤害由单段伤害 × 次数计算得出。"""
        if payload.damage_display_type != DamageDisplayType.COMBO_REPEATED_DAMAGE:
            return None
        if payload.per_hit_damage_value is None or payload.hit_count is None:
            return None
        return payload.per_hit_damage_value * payload.hit_count

    @staticmethod
    def _resolve_hp_percent_delta(payload: DamageEventCreate) -> float | None:
        """根据前后生命百分比计算扣血百分比。"""
        if payload.hp_percent_before is None or payload.hp_percent_after is None:
            return payload.enemy_hp_percent_damage
        return round(payload.hp_percent_before - payload.hp_percent_after, 4)

    @staticmethod
    def _event_type_for(display_type: DamageDisplayType) -> str:
        """根据显示类型选择通用事件类型。"""
        if display_type == DamageDisplayType.COMBO_REPEATED_DAMAGE:
            return BattleEventType.COMBO_DAMAGE.value
        return BattleEventType.DAMAGE.value

    @staticmethod
    def _should_resolve_rules(payload: dict) -> bool:
        """有技能或应对/防御上下文时启用规则解析，但不改变候选硬排除策略。"""
        return any(
            payload.get(key) is not None
            for key in (
                "skill_id",
                "defense_skill_id",
                "response_attack_success",
                "response_defense_success",
                "response_status_success",
            )
        )

    def _get_elf_state(
        self,
        *,
        battle_id: str,
        side: str | None,
        elf_id: str | None,
    ) -> BattleElfState | None:
        """读取本场战斗中指定精灵的运行时状态。"""
        if side is None or elf_id is None:
            return None
        return self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle_id,
                BattleElfState.side == side,
                BattleElfState.elf_id == elf_id,
            )
        ).first()

    @staticmethod
    def _panel_stats_from_state(state: BattleElfState | None) -> PanelStats | None:
        """从运行时精灵状态解析伤害公式需要的六维面板。"""
        if state is None:
            return None
        stats = loads_json(state.panel_stats_json, {})
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
        return PanelStats(
            hp=int(stats["hp"]),
            physical_attack=int(stats["physical_attack"]),
            physical_defense=int(stats["physical_defense"]),
            magic_attack=int(stats["magic_attack"]),
            magic_defense=int(stats["magic_defense"]),
            speed=int(stats["speed"]),
        )

    def _create_resource_change_for_damage(
        self,
        *,
        battle_id: str,
        battle_event_id: str,
        payload: DamageEventCreate,
        total_damage: int | None,
        hp_percent_delta: float | None,
    ) -> None:
        """
        为伤害事件补充 ResourceChangeEvent。

        文档要求生命 / 能量变化需要进入事件日志。伤害详情仍由 DamageEvent 保存，
        这里额外记录一次 hp 资源变化，方便时间线、回放和后续纠错统一处理。
        """
        if payload.defender_side is None or payload.defender_elf_id is None:
            return
        if hp_percent_delta is not None:
            value_type = "percent"
            value = hp_percent_delta
            before_value = payload.hp_percent_before
            after_value = payload.hp_percent_after
        elif total_damage is not None:
            value_type = "value"
            value = float(total_damage)
            before_value = None
            after_value = None
        else:
            return

        self.db.add(
            ResourceChangeEvent(
                event_id=f"resource_event_{uuid4().hex}",
                battle_id=battle_id,
                battle_event_id=battle_event_id,
                resource_type="hp",
                change_type="damage",
                source_side=payload.attacker_side,
                source_elf_id=payload.attacker_elf_id,
                target_side=payload.defender_side,
                target_elf_id=payload.defender_elf_id,
                value_type=value_type,
                value=float(value),
                before_value=before_value,
                after_value=after_value,
                confidence=1.0,
                manual_override=True,
            )
        )

    def _update_defender_hp_state(
        self,
        battle: Battle,
        payload: DamageEventCreate,
        total_damage: int | None,
    ) -> None:
        """
        基于手动输入更新防御方生命状态。

        这里只更新观测事实：如果用户传了 hp_percent_after，则写入当前百分比；
        如果当前生命值已知且传入了总伤害，则扣减当前生命值。
        """
        if payload.defender_side is None or payload.defender_elf_id is None:
            return
        state = self.db.scalars(
            select(BattleElfState).where(
                BattleElfState.battle_id == battle.battle_id,
                BattleElfState.side == payload.defender_side,
                BattleElfState.elf_id == payload.defender_elf_id,
            )
        ).first()
        if state is None:
            return
        if payload.hp_percent_after is not None:
            state.current_hp_percent = payload.hp_percent_after
        if total_damage is not None and state.current_hp_value is not None:
            state.current_hp_value = max(state.current_hp_value - total_damage, 0)
        if state.current_hp_value == 0 or state.current_hp_percent == 0:
            state.is_defeated = True
