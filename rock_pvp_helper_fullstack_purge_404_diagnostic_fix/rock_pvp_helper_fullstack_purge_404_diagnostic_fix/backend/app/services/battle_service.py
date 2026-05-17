"""
战斗服务模块。

本模块提供战斗生命周期和手动输入 MVP 的核心业务流程：
创建战斗、录入阵容、生成敌方候选、切换精灵、记录通用事件和查询状态。
"""

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.enums import BattleEventType, BattlePhase, EventSource, Side
from app.models.battle import Battle, BattleElfState, BattleSkillSlot
from app.models.candidate import BuildCandidate
from app.models.effect import BattleEffectInstance
from app.models.event import BattleEvent, DamageEvent, EffectChangeEvent, ResourceChangeEvent
from app.models.static import ElfDefinition, ElfLearnableSkill, PlayerElfBuild, PlayerElfBuildSkill
from app.schemas.battle import (
    BattleCreate,
    BattleStateOut,
    LineupInput,
    LineupOut,
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
from app.services.candidate_service import CandidateService
from app.services.effect_service import BattleEffectService
from app.services.snapshot_service import SnapshotService
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

        首页的“移除最近战斗”采用 archive 语义：保留事件、候选和快照，
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

    def setup_lineup(self, battle_id: str, payload: LineupInput) -> LineupOut:
        """
        录入双方阵容并生成敌方候选配置。

        处理步骤：
        1. 清理该战斗旧的精灵状态、技能槽和候选配置；
        2. 己方从 PlayerElfBuild 复制确定面板属性与技能槽；
        3. 敌方只根据 elf_id 创建未知面板运行时状态；
        4. 为每只敌方精灵生成 BuildCandidate；
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
        generated_candidate_count = 0
        self_active_elf_id: str | None = None
        enemy_active_elf_id: str | None = None

        for item in payload.elves:
            elf = self._require_elf(item.elf_id)
            if item.side == Side.SELF.value:
                state = self._create_self_elf_state(battle_id, item, elf)
            elif item.side == Side.ENEMY.value:
                state = self._create_enemy_elf_state(battle_id, item, elf)
                generated_candidate_count += CandidateService(self.db).generate_for_enemy_elf(
                    battle_id,
                    item.elf_id,
                    replace_existing=True,
                    commit=False,
                )
            else:
                raise ValueError(f"未知阵营：{item.side}")

            self.db.add(state)
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
            generated_candidate_count=generated_candidate_count,
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
            payload_json=dumps_json({"from_elf_id": old_elf_id, "to_elf_id": payload.elf_id}),
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.flush()

        if old_elf_id is not None:
            BattleEffectService(self.db).switch_clear_effects(
                battle_id=battle_id,
                side=payload.side,
                leaving_elf_id=old_elf_id,
                turn_number=turn_number,
                battle_event_id=event.event_id,
            )

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
        return BattleStateOut(
            battle=battle,
            elves=[model_to_dict(item) for item in elves],
            active_effects=[model_to_dict(item) for item in effects],
            latest_snapshot_id=battle.current_snapshot_id,
        )

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
                payload_json=dumps_json({"voided_event_id": target.event_id, "reason": payload.reason}),
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
            original.notes = self._append_note(original.notes, f"被修正：{payload.reason or '未填写'}")
        replacement = payload.replacement_event
        replacement.corrected_event_id = event_id
        replacement.manual_override = True
        if payload.reason and replacement.notes:
            replacement.notes = f"{replacement.notes}；修正原因：{payload.reason}"
        elif payload.reason:
            replacement.notes = f"修正原因：{payload.reason}"
        return self.create_event(battle_id, replacement)

    def replay_from_event(self, battle_id: str, event_id: str) -> BattleReplayResult:
        """从某事件开始重放的占位实现，不修改数据库状态。"""
        self.require_battle(battle_id)
        self._require_event(battle_id, event_id)
        return BattleReplayResult(
            battle_id=battle_id,
            from_event_id=event_id,
            message="EventReplayService 尚未实现；当前接口只确认事件存在，不执行重放重算。",
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

    def _clear_runtime_data(self, battle_id: str) -> None:
        """重录阵容前清理第一阶段运行时数据。"""
        self.db.execute(delete(BattleSkillSlot).where(BattleSkillSlot.battle_id == battle_id))
        self.db.execute(delete(BattleElfState).where(BattleElfState.battle_id == battle_id))
        self.db.execute(delete(BuildCandidate).where(BuildCandidate.battle_id == battle_id))

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
        skill_ids = self._load_build_skill_ids(build.build_id)
        self._create_battle_skill_slots(battle_id, item.side, item.elf_id, skill_ids)

        return BattleElfState(
            state_id=f"battle_elf_state_{uuid4().hex}",
            battle_id=battle_id,
            side=item.side,
            elf_id=item.elf_id,
            elf_name=elf.elf_name,
            avatar=elf.avatar,
            panel_stats_json=build.final_stats_json or dumps_json({}),
            current_hp_value=final_stats.get("hp") if isinstance(final_stats, dict) else None,
            current_hp_percent=100.0,
            energy=0,
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
        possible_skill_ids = list(
            self.db.scalars(
                select(ElfLearnableSkill.skill_id)
                .where(ElfLearnableSkill.elf_id == item.elf_id)
                .order_by(ElfLearnableSkill.skill_id)
            ).all()
        )
        return BattleElfState(
            state_id=f"battle_elf_state_{uuid4().hex}",
            battle_id=battle_id,
            side=item.side,
            elf_id=item.elf_id,
            elf_name=elf.elf_name,
            avatar=elf.avatar,
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
            energy=0,
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
