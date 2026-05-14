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
from app.models.event import BattleEvent
from app.models.static import ElfDefinition, ElfLearnableSkill, PlayerElfBuild, PlayerElfBuildSkill
from app.schemas.battle import (
    BattleCreate,
    BattleStateOut,
    LineupInput,
    LineupOut,
    SwitchElfInput,
)
from app.schemas.event import BattleEventCreate
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
        if battle.phase not in {BattlePhase.PREPARATION.value, BattlePhase.BATTLE.value}:
            raise ValueError("只有 preparation/battle 阶段允许重新录入阵容")

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

    def create_event(self, battle_id: str, payload: BattleEventCreate) -> BattleEvent:
        """创建通用战斗事件。"""
        self.require_battle(battle_id)
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",
            battle_id=battle_id,
            turn_number=payload.turn_number,
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
            payload_json=payload.payload_json,
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def require_battle(self, battle_id: str) -> Battle:
        """读取战斗并统一校验软删除。"""
        battle = self.db.get(Battle, battle_id)
        if battle is None or battle.deleted_at is not None:
            raise LookupError(f"战斗不存在：{battle_id}")
        return battle

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
        seen: set[tuple[str, str]] = set()
        for item in payload.elves:
            key = (item.side, item.elf_id)
            if key in seen:
                raise ValueError(f"阵容中重复出现精灵：{item.side}/{item.elf_id}")
            seen.add(key)
            if item.is_active_elf:
                active_by_side[item.side] = active_by_side.get(item.side, 0) + 1
        if active_by_side[Side.SELF.value] > 1 or active_by_side[Side.ENEMY.value] > 1:
            raise ValueError("每个阵营最多只能设置一个首发精灵")
