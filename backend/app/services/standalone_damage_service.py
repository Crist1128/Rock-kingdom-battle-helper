"""独立伤害计算器服务。

该服务只读取静态数据和可选的最近战斗快照信息，不创建战斗事件、不写入推算证据。
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext, PanelStats
from app.calculation.rule_resolver import RuleResolver
from app.calculation.stat_calculator import (
    BaseTalentBlock,
    IndividualTalentDistribution,
    NatureRule,
    StatCalculator,
)
from app.core.enums import StatKey
from app.models.battle import Battle, BattleElfState, BattleSkillSlot
from app.models.static import (
    ElfDefinition,
    NatureDefinition,
    SkillDefinition,
    TypeEffectivenessRule,
)
from app.schemas.damage_calculator import (
    DamageCalculatorBatchDefenderCandidateOut,
    DamageCalculatorBattleOptionOut,
    DamageCalculatorBootstrapOut,
    DamageCalculatorCalculateInput,
    DamageCalculatorDefenderCandidateOut,
    DamageCalculatorInferDefenderBatchInput,
    DamageCalculatorInferDefenderBatchOut,
    DamageCalculatorInferDefenderInput,
    DamageCalculatorInferDefenderOut,
    DamageCalculatorInferDefenderSampleInput,
    DamageCalculatorInferDefenderSampleResultOut,
    DamageCalculatorLatestBattleOut,
    DamageCalculatorObservedComparisonOut,
    DamageCalculatorPanelOut,
    DamageCalculatorParticipantInput,
    DamageCalculatorParticipantOut,
    DamageCalculatorResultOut,
    DamageCalculatorTalentInput,
    DamageCalculatorTypeEffectivenessOut,
)
from app.utils.json import loads_json


class StandaloneDamageService:
    """独立伤害计算器业务服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def bootstrap(self) -> DamageCalculatorBootstrapOut:
        """读取最近一场未软删除战斗的阵容摘要，用于前端快捷填充。"""
        type_rules = self._type_effectiveness_rules()
        battle = self.db.scalars(
            select(Battle)
            .where(Battle.deleted_at.is_(None))
            .order_by(Battle.updated_at.desc(), Battle.created_at.desc())
            .limit(1)
        ).first()
        if battle is None:
            return DamageCalculatorBootstrapOut(
                latest_battle=None,
                type_effectiveness_rules=type_rules,
            )

        states = list(
            self.db.scalars(
                select(BattleElfState)
                .where(BattleElfState.battle_id == battle.battle_id)
                .order_by(BattleElfState.side, BattleElfState.created_at)
            ).all()
        )
        slots = list(
            self.db.scalars(
                select(BattleSkillSlot).where(BattleSkillSlot.battle_id == battle.battle_id)
            ).all()
        )
        skills_by_state = self._skill_ids_by_state(states, slots)
        self_lineup: list[DamageCalculatorBattleOptionOut] = []
        enemy_lineup: list[DamageCalculatorBattleOptionOut] = []
        for state in states:
            option = self._battle_option_from_state(
                state,
                skills_by_state.get((state.side, state.elf_id), []),
            )
            if state.side == "self":
                self_lineup.append(option)
            elif state.side == "enemy":
                enemy_lineup.append(option)

        return DamageCalculatorBootstrapOut(
            latest_battle=DamageCalculatorLatestBattleOut(
                battle_id=battle.battle_id,
                battle_name=battle.battle_name,
                phase=battle.phase,
                turn_number=battle.turn_number,
                self_active_elf_id=battle.self_active_elf_id,
                enemy_active_elf_id=battle.enemy_active_elf_id,
                self_lineup=self_lineup,
                enemy_lineup=enemy_lineup,
            ),
            type_effectiveness_rules=type_rules,
        )

    def _type_effectiveness_rules(self) -> list[DamageCalculatorTypeEffectivenessOut]:
        """读取属性克制规则，供前端做倍率预填；真正计算仍以后端 RuleResolver 为准。"""
        rows = self.db.scalars(
            select(TypeEffectivenessRule)
            .where(TypeEffectivenessRule.deleted_at.is_(None))
            .order_by(
                TypeEffectivenessRule.attack_element_type,
                TypeEffectivenessRule.defense_element_type,
            )
        ).all()
        return [
            DamageCalculatorTypeEffectivenessOut(
                attack_element_type=row.attack_element_type,
                defense_element_type=row.defense_element_type,
                multiplier=row.multiplier,
            )
            for row in rows
        ]

    def calculate(self, payload: DamageCalculatorCalculateInput) -> DamageCalculatorResultOut:
        """按用户输入进行一次独立伤害计算。"""
        skill = self._require_skill(payload.skill_id)
        attacker = self._build_participant(payload.attacker)
        defender = self._build_participant(payload.defender)
        attacker_panel = PanelStats(**attacker.panel_stats.model_dump())
        defender_panel = PanelStats(**defender.panel_stats.model_dump())
        context = DamageFormulaContext(
            battle_id="standalone_damage_calculator",
            formula_type=payload.formula_type,
            attacker_side="self",
            attacker_elf_id=attacker.elf_id,
            defender_side="enemy",
            defender_elf_id=defender.elf_id,
            skill_id=skill.skill_id,
            skill_element_type=skill.element_type,
            skill_category=skill.skill_category,
            base_power=skill.base_power,
            attacker_panel_stats=attacker_panel,
            defender_panel_stats=defender_panel,
            defender_max_hp=defender_panel.hp,
            defender_hp_percent=payload.modifiers.defender_hp_percent,
            attacker_element_types=attacker.element_types,
            defender_element_types=defender.element_types,
            response_attack_success=payload.modifiers.response_attack_success,
            response_defense_success=payload.modifiers.response_defense_success,
            response_status_success=payload.modifiers.response_status_success,
            notes=payload.notes,
        )
        resolver_payload = self._resolver_payload(payload)
        self._apply_manual_modifiers(context, payload)
        resolved_context = RuleResolver(self.db).resolve_damage_context(context, resolver_payload)
        result = DamageCalculator().calculate(resolved_context)
        damage_percent = self._damage_percent(result.damage_value, defender_panel.hp)
        observed_comparison = self._observed_comparison(
            payload.observed_damage_value,
            result.damage_value,
        )

        return DamageCalculatorResultOut(
            status=result.status,
            formula_type=result.formula_type,
            attacker=attacker,
            defender=defender,
            skill_id=skill.skill_id,
            skill_name=skill.skill_name,
            damage_value=result.damage_value,
            damage_percent=damage_percent,
            confidence=result.confidence,
            missing_parts=result.missing_parts,
            unknown_factors=result.unknown_factors,
            explanation=result.explanation,
            multipliers=self._multipliers_from_result(result.explanation, resolved_context),
            observed_comparison=observed_comparison,
        )

    def infer_defender(
        self,
        payload: DamageCalculatorInferDefenderInput,
    ) -> DamageCalculatorInferDefenderOut:
        """枚举防御方性格和关键资质，返回与真实伤害最接近的软候选。"""
        skill = self._require_skill(payload.skill_id)
        if skill.skill_category not in {"physical", "magic"}:
            raise ValueError("当前反推只支持物理/魔法攻击技能")
        defender_elf = self._require_elf(payload.defender_elf_id)
        attacker = self._build_participant(payload.attacker)
        attacker_panel = PanelStats(**attacker.panel_stats.model_dump())
        natures = list(
            self.db.scalars(
                select(NatureDefinition)
                .where(NatureDefinition.deleted_at.is_(None))
                .order_by(NatureDefinition.nature_name)
            ).all()
        )
        if not natures:
            raise ValueError("缺少性格定义，无法反推防御方配置")

        relevant_defense_stat = (
            "physical_defense" if skill.skill_category == "physical" else "magic_defense"
        )
        candidates: list[DamageCalculatorDefenderCandidateOut] = []
        searched_count = 0
        for nature in natures:
            for template_name, talents in self._candidate_talent_options(
                relevant_defense_stats=[relevant_defense_stat],
                candidate_mode=payload.candidate_mode,
            ):
                searched_count += 1
                hp_talent = int(talents.hp)
                defense_talent = int(getattr(talents, relevant_defense_stat))
                defender_panel = self._calculate_panel(defender_elf, nature, talents)
                result = self._calculate_with_panels(
                    skill=skill,
                    attacker=attacker,
                    attacker_panel=attacker_panel,
                    defender_elf=defender_elf,
                    defender_nature=nature,
                    defender_panel=defender_panel,
                    modifiers=payload.modifiers,
                    notes=payload.notes,
                )
                delta = (
                    result.damage_value - payload.observed_damage_value
                    if result.damage_value is not None
                    else None
                )
                candidates.append(
                    DamageCalculatorDefenderCandidateOut(
                        rank=0,
                        template_name=template_name,
                        nature_id=nature.nature_id,
                        nature_name=nature.nature_name,
                        individual_talent_distribution=DamageCalculatorTalentInput(
                            **talents.model_dump()
                        ),
                        relevant_defense_stat=relevant_defense_stat,
                        hp_talent=hp_talent,
                        defense_talent=defense_talent,
                        panel_stats=DamageCalculatorPanelOut(**defender_panel.model_dump()),
                        predicted_damage_value=result.damage_value,
                        predicted_damage_percent=self._damage_percent(
                            result.damage_value,
                            defender_panel.hp,
                        ),
                        delta_value=delta,
                        absolute_delta=abs(delta) if delta is not None else None,
                        score=self._candidate_score(delta, payload.observed_damage_value),
                        matched_within_tolerance=(abs(delta) <= 0 if delta is not None else False),
                        unknown_factors=result.unknown_factors,
                        missing_parts=result.missing_parts,
                    )
                )

        sorted_candidates = sorted(
            candidates,
            key=lambda item: (
                item.absolute_delta if item.absolute_delta is not None else 10**9,
                -item.score,
                item.nature_name,
                item.hp_talent,
                item.defense_talent,
            ),
        )[: payload.top_n]
        for index, candidate in enumerate(sorted_candidates, start=1):
            candidate.rank = index

        return DamageCalculatorInferDefenderOut(
            status="ranked",
            observed_damage_value=payload.observed_damage_value,
            skill_id=skill.skill_id,
            skill_name=skill.skill_name,
            searched_candidate_count=searched_count,
            returned_candidate_count=len(sorted_candidates),
            candidates=sorted_candidates,
            assumptions=[
                "仅枚举本次伤害直接相关的 HP 资质与对应防御资质，其它资质按 0 展示。",
                "候选只做软排序，不写入 EnemyPanelEstimate，也不用于硬排除。",
                "结果复用当前项目伤害公式；若公式或状态上下文仍有 unknown factors，应降低置信度。",
            ],
        )

    def infer_defender_batch(
        self,
        payload: DamageCalculatorInferDefenderBatchInput,
    ) -> DamageCalculatorInferDefenderBatchOut:
        """对同一防御方配置累计多条真实伤害偏差，返回综合软候选。"""
        defender_elf = self._require_elf(payload.defender_elf_id)
        samples = [self._prepare_infer_sample(item) for item in payload.samples]
        relevant_stats = sorted(
            {
                "physical_defense"
                if sample["skill"].skill_category == "physical"
                else "magic_defense"
                for sample in samples
            }
        )
        natures = list(
            self.db.scalars(
                select(NatureDefinition)
                .where(NatureDefinition.deleted_at.is_(None))
                .order_by(NatureDefinition.nature_name)
            ).all()
        )
        if not natures:
            raise ValueError("缺少性格定义，无法反推防御方配置")

        candidates: list[DamageCalculatorBatchDefenderCandidateOut] = []
        searched_count = 0
        for nature in natures:
            for template_name, talents in self._candidate_talent_options(
                relevant_defense_stats=relevant_stats,
                candidate_mode=payload.candidate_mode,
            ):
                searched_count += 1
                defender_panel = self._calculate_panel(defender_elf, nature, talents)
                sample_results: list[DamageCalculatorInferDefenderSampleResultOut] = []
                total_abs_delta = 0
                matched_count = 0
                unavailable_penalty = 10**6
                for sample_index, sample in enumerate(samples):
                    result = self._calculate_with_panels(
                        skill=sample["skill"],
                        attacker=sample["attacker"],
                        attacker_panel=sample["attacker_panel"],
                        defender_elf=defender_elf,
                        defender_nature=nature,
                        defender_panel=defender_panel,
                        modifiers=sample["payload"].modifiers,
                        notes=sample["payload"].notes,
                    )
                    observed = sample["payload"].observed_damage_value
                    delta = (
                        result.damage_value - observed
                        if result.damage_value is not None
                        else None
                    )
                    abs_delta = abs(delta) if delta is not None else unavailable_penalty
                    total_abs_delta += abs_delta
                    matched = delta is not None and abs_delta <= payload.tolerance
                    if matched:
                        matched_count += 1
                    sample_results.append(
                        DamageCalculatorInferDefenderSampleResultOut(
                            sample_index=sample_index,
                            sample_label=sample["payload"].label,
                            skill_id=sample["skill"].skill_id,
                            skill_name=sample["skill"].skill_name,
                            observed_damage_value=observed,
                            predicted_damage_value=result.damage_value,
                            delta_value=delta,
                            absolute_delta=abs_delta if delta is not None else None,
                            matched_within_tolerance=matched,
                            unknown_factors=result.unknown_factors,
                            missing_parts=result.missing_parts,
                        )
                    )
                average_delta = round(total_abs_delta / len(samples), 2)
                candidates.append(
                    DamageCalculatorBatchDefenderCandidateOut(
                        rank=0,
                        template_name=template_name,
                        nature_id=nature.nature_id,
                        nature_name=nature.nature_name,
                        individual_talent_distribution=DamageCalculatorTalentInput(
                            **talents.model_dump()
                        ),
                        relevant_defense_stats=relevant_stats,
                        hp_talent=int(talents.hp),
                        physical_defense_talent=int(talents.physical_defense),
                        magic_defense_talent=int(talents.magic_defense),
                        panel_stats=DamageCalculatorPanelOut(**defender_panel.model_dump()),
                        total_absolute_delta=total_abs_delta,
                        average_absolute_delta=average_delta,
                        matched_sample_count=matched_count,
                        sample_count=len(samples),
                        score=self._batch_candidate_score(total_abs_delta, samples),
                        sample_results=sample_results,
                    )
                )

        sorted_candidates = sorted(
            candidates,
            key=lambda item: (
                item.total_absolute_delta,
                -item.matched_sample_count,
                -item.score,
                item.nature_name,
                item.template_name or "",
                item.hp_talent,
                item.physical_defense_talent,
                item.magic_defense_talent,
            ),
        )[: payload.top_n]
        for index, candidate in enumerate(sorted_candidates, start=1):
            candidate.rank = index

        return DamageCalculatorInferDefenderBatchOut(
            status="ranked",
            defender_elf_id=defender_elf.elf_id,
            searched_candidate_count=searched_count,
            returned_candidate_count=len(sorted_candidates),
            tolerance=payload.tolerance,
            candidate_mode=payload.candidate_mode,
            candidates=sorted_candidates,
            assumptions=[
                "多条样本会在同一个防御方性格/资质配置上累计绝对偏差。",
                "focused 模式只枚举 HP 和本批样本涉及的物防/魔防资质。",
                "default_templates 模式会按常见三维资质模板补齐非本次伤害项，仅做参考。",
                "批量反推仍然是独立只读软排序，不写入 EnemyPanelEstimate。",
            ],
        )

    def _build_participant(
        self,
        payload: DamageCalculatorParticipantInput,
    ) -> DamageCalculatorParticipantOut:
        elf = self._require_elf(payload.elf_id)
        nature: NatureDefinition | None = None
        panel_source = "manual_panel"
        if payload.panel_stats is not None:
            panel = PanelStats(**payload.panel_stats.model_dump())
        else:
            if not payload.nature_id:
                raise ValueError("未手动提供面板时必须选择性格")
            nature = self._require_nature(payload.nature_id)
            talents = payload.individual_talent_distribution or IndividualTalentDistribution()
            panel = self._calculate_panel(elf, nature, talents)
            panel_source = "calculated_from_elf_nature_talents"

        if nature is None and payload.nature_id:
            nature = self.db.get(NatureDefinition, payload.nature_id)
            if nature is not None and nature.deleted_at is not None:
                nature = None

        return DamageCalculatorParticipantOut(
            elf_id=elf.elf_id,
            elf_name=elf.elf_name,
            element_types=self._element_types(elf),
            nature_id=nature.nature_id if nature else payload.nature_id,
            nature_name=nature.nature_name if nature else None,
            panel_stats=DamageCalculatorPanelOut(**panel.model_dump()),
            panel_source=panel_source,
        )

    def _calculate_panel(
        self,
        elf: ElfDefinition,
        nature: NatureDefinition,
        talents: IndividualTalentDistribution | Any,
    ) -> PanelStats:
        if not isinstance(talents, IndividualTalentDistribution):
            talents = IndividualTalentDistribution(**talents.model_dump())
        calculated = StatCalculator.calculate_panel_stats(
            BaseTalentBlock(
                hp=elf.base_hp_talent,
                physical_attack=elf.base_physical_attack_talent,
                physical_defense=elf.base_physical_defense_talent,
                magic_attack=elf.base_magic_attack_talent,
                magic_defense=elf.base_magic_defense_talent,
                speed=elf.base_speed_talent,
            ),
            talents,
            NatureRule(
                nature_id=nature.nature_id,
                positive_stat=StatKey(nature.positive_stat),
                negative_stat=StatKey(nature.negative_stat),
                positive_multiplier=Decimal(str(nature.positive_multiplier)),
                negative_multiplier=Decimal(str(nature.negative_multiplier)),
                neutral_multiplier=Decimal(str(nature.neutral_multiplier)),
            ),
        )
        return PanelStats(**calculated.model_dump())

    def _calculate_with_panels(
        self,
        *,
        skill: SkillDefinition,
        attacker: DamageCalculatorParticipantOut,
        attacker_panel: PanelStats,
        defender_elf: ElfDefinition,
        defender_nature: NatureDefinition,
        defender_panel: PanelStats,
        modifiers: Any,
        notes: str | None,
    ) -> Any:
        context = DamageFormulaContext(
            battle_id="standalone_damage_calculator",
            formula_type="attack",
            attacker_side="self",
            attacker_elf_id=attacker.elf_id,
            defender_side="enemy",
            defender_elf_id=defender_elf.elf_id,
            skill_id=skill.skill_id,
            skill_element_type=skill.element_type,
            skill_category=skill.skill_category,
            base_power=skill.base_power,
            attacker_panel_stats=attacker_panel,
            defender_panel_stats=defender_panel,
            defender_max_hp=defender_panel.hp,
            defender_hp_percent=modifiers.defender_hp_percent,
            attacker_element_types=attacker.element_types,
            defender_element_types=self._element_types(defender_elf),
            response_attack_success=modifiers.response_attack_success,
            response_defense_success=modifiers.response_defense_success,
            response_status_success=modifiers.response_status_success,
            notes=notes,
        )
        self._apply_modifier_values(context, modifiers)
        resolver_payload = self._resolver_payload_from_modifiers(modifiers)
        resolved_context = RuleResolver(self.db).resolve_damage_context(context, resolver_payload)
        result = DamageCalculator().calculate(resolved_context)
        result.explanation.setdefault(
            "defender_candidate",
            {
                "nature_id": defender_nature.nature_id,
                "nature_name": defender_nature.nature_name,
            },
        )
        return result

    def _prepare_infer_sample(
        self,
        payload: DamageCalculatorInferDefenderSampleInput,
    ) -> dict[str, Any]:
        skill = self._require_skill(payload.skill_id)
        if skill.skill_category not in {"physical", "magic"}:
            raise ValueError("当前批量反推只支持物理/魔法攻击技能")
        attacker = self._build_participant(payload.attacker)
        return {
            "payload": payload,
            "skill": skill,
            "attacker": attacker,
            "attacker_panel": PanelStats(**attacker.panel_stats.model_dump()),
        }

    @classmethod
    def _candidate_talent_options(
        cls,
        *,
        relevant_defense_stats: list[str],
        candidate_mode: str,
    ) -> list[tuple[str | None, IndividualTalentDistribution]]:
        if candidate_mode == "default_templates":
            return cls._default_template_talent_options(relevant_defense_stats)
        return cls._focused_talent_options(relevant_defense_stats)

    @classmethod
    def _focused_talent_options(
        cls,
        relevant_defense_stats: list[str],
    ) -> list[tuple[str | None, IndividualTalentDistribution]]:
        values: list[tuple[str | None, IndividualTalentDistribution]] = []
        physical_range = range(0, 11) if "physical_defense" in relevant_defense_stats else (0,)
        magic_range = range(0, 11) if "magic_defense" in relevant_defense_stats else (0,)
        for hp_talent in range(0, 11):
            for physical_defense in physical_range:
                for magic_defense in magic_range:
                    values.append(
                        (
                            None,
                            cls._talents_from_values(
                                hp=hp_talent,
                                physical_defense=physical_defense,
                                magic_defense=magic_defense,
                            ),
                        )
                    )
        return values

    @classmethod
    def _default_template_talent_options(
        cls,
        relevant_defense_stats: list[str],
    ) -> list[tuple[str | None, IndividualTalentDistribution]]:
        templates: list[tuple[str, tuple[str, ...]]] = [
            ("生命+速度+物攻", ("hp", "speed", "physical_attack")),
            ("生命+速度+魔攻", ("hp", "speed", "magic_attack")),
            ("生命+物攻+物防", ("hp", "physical_attack", "physical_defense")),
            ("生命+魔攻+魔防", ("hp", "magic_attack", "magic_defense")),
            ("生命+双防", ("hp", "physical_defense", "magic_defense")),
            ("生命+速度+物防", ("hp", "speed", "physical_defense")),
            ("生命+速度+魔防", ("hp", "speed", "magic_defense")),
        ]
        options: list[tuple[str | None, IndividualTalentDistribution]] = []
        seen: set[tuple[str, tuple[int, int, int, int, int, int]]] = set()
        for template_name, template_stats in templates:
            physical_range = (
                range(0, 11)
                if "physical_defense" in relevant_defense_stats
                else (10 if "physical_defense" in template_stats else 0,)
            )
            magic_range = (
                range(0, 11)
                if "magic_defense" in relevant_defense_stats
                else (10 if "magic_defense" in template_stats else 0,)
            )
            for hp_talent in range(0, 11):
                for physical_defense in physical_range:
                    for magic_defense in magic_range:
                        talents = cls._talents_from_values(
                            hp=hp_talent,
                            physical_attack=10 if "physical_attack" in template_stats else 0,
                            physical_defense=physical_defense,
                            magic_attack=10 if "magic_attack" in template_stats else 0,
                            magic_defense=magic_defense,
                            speed=10 if "speed" in template_stats else 0,
                        )
                        key = (
                            template_name,
                            (
                                talents.hp,
                                talents.physical_attack,
                                talents.physical_defense,
                                talents.magic_attack,
                                talents.magic_defense,
                                talents.speed,
                            ),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        options.append((template_name, talents))
        return options

    @staticmethod
    def _talents_from_values(
        *,
        hp: int,
        physical_attack: int = 0,
        physical_defense: int = 0,
        magic_attack: int = 0,
        magic_defense: int = 0,
        speed: int = 0,
    ) -> IndividualTalentDistribution:
        return IndividualTalentDistribution(
            hp=hp,
            physical_attack=physical_attack,
            physical_defense=physical_defense,
            magic_attack=magic_attack,
            magic_defense=magic_defense,
            speed=speed,
        )

    @staticmethod
    def _defender_candidate_talents(
        relevant_defense_stat: str,
        hp_talent: int,
        defense_talent: int,
    ) -> IndividualTalentDistribution:
        values = {
            "hp": hp_talent,
            "physical_attack": 0,
            "physical_defense": 0,
            "magic_attack": 0,
            "magic_defense": 0,
            "speed": 0,
        }
        values[relevant_defense_stat] = defense_talent
        return IndividualTalentDistribution(**values)

    def _battle_option_from_state(
        self,
        state: BattleElfState,
        skill_ids: list[str],
    ) -> DamageCalculatorBattleOptionOut:
        panel = self._panel_from_json(state.panel_stats_json)
        nature = self.db.get(NatureDefinition, state.nature_id) if state.nature_id else None
        individual = loads_json(state.individual_talent_distribution_json, None)
        return DamageCalculatorBattleOptionOut(
            side=state.side,
            elf_id=state.runtime_form_elf_id or state.elf_id,
            elf_name=state.runtime_form_elf_name or state.elf_name,
            avatar=state.runtime_form_avatar or state.avatar,
            is_active_elf=state.is_active_elf,
            current_hp_percent=state.current_hp_percent,
            nature_id=nature.nature_id if nature and nature.deleted_at is None else state.nature_id,
            nature_name=nature.nature_name if nature and nature.deleted_at is None else None,
            individual_talent_distribution=individual if isinstance(individual, dict) else None,
            panel_stats=DamageCalculatorPanelOut(**panel.model_dump()) if panel else None,
            panel_source="battle_state_panel" if panel else None,
            skill_ids=skill_ids,
        )

    @staticmethod
    def _skill_ids_by_state(
        states: list[BattleElfState],
        slots: list[BattleSkillSlot],
    ) -> dict[tuple[str, str], list[str]]:
        result: dict[tuple[str, str], list[str]] = {}
        for state in states:
            key = (state.side, state.elf_id)
            ids: list[str] = []
            for raw in (
                loads_json(state.skill_ids_json, []),
                loads_json(state.confirmed_skill_ids_json, []),
            ):
                if isinstance(raw, list):
                    ids.extend(str(item) for item in raw if item)
            ids.extend(
                slot.skill_id
                for slot in slots
                if slot.side == state.side and slot.elf_id == state.elf_id
            )
            result[key] = list(dict.fromkeys(ids))
        return result

    @staticmethod
    def _panel_from_json(raw_json: str | None) -> PanelStats | None:
        raw = loads_json(raw_json, {})
        if not isinstance(raw, dict):
            return None
        try:
            return PanelStats(
                hp=int(raw["hp"]),
                physical_attack=int(raw["physical_attack"]),
                physical_defense=int(raw["physical_defense"]),
                magic_attack=int(raw["magic_attack"]),
                magic_defense=int(raw["magic_defense"]),
                speed=int(raw["speed"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _resolver_payload(self, payload: DamageCalculatorCalculateInput) -> dict[str, Any]:
        return self._resolver_payload_from_modifiers(payload.modifiers)

    def _resolver_payload_from_modifiers(self, modifiers: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "resolve_rules": True,
            "condition_flags": modifiers.condition_flags,
        }
        manual_fields = (
            "weather_multiplier",
            "power_multiplier",
            "flat_power_bonus",
            "stat_stage_multiplier",
            "stab_multiplier",
            "type_multiplier",
            "unstable_multiplier",
            "response_attack_success",
            "response_defense_success",
            "response_status_success",
        )
        for field in manual_fields:
            value = getattr(modifiers, field)
            if value is not None:
                data[field] = value
        if modifiers.damage_reductions:
            data["damage_reductions"] = modifiers.damage_reductions
        if modifiers.hit_count is not None:
            data["hit_count"] = modifiers.hit_count
            data["combo_count_source"] = "manual_standalone_calculator"
        return data

    @staticmethod
    def _apply_manual_modifiers(
        context: DamageFormulaContext,
        payload: DamageCalculatorCalculateInput,
    ) -> None:
        StandaloneDamageService._apply_modifier_values(context, payload.modifiers)

    @staticmethod
    def _apply_modifier_values(
        context: DamageFormulaContext,
        modifiers: Any,
    ) -> None:
        for field in (
            "weather_multiplier",
            "power_multiplier",
            "flat_power_bonus",
            "stat_stage_multiplier",
            "stab_multiplier",
            "type_multiplier",
            "unstable_multiplier",
        ):
            value = getattr(modifiers, field)
            if value is not None:
                setattr(context, field, Decimal(str(value)))
        if modifiers.damage_reductions:
            context.damage_reductions = [Decimal(str(item)) for item in modifiers.damage_reductions]
        if modifiers.hit_count is not None:
            context.hit_count = modifiers.hit_count

    @staticmethod
    def _candidate_score(delta: int | None, observed_damage_value: int) -> float:
        if delta is None:
            return 0.0
        return round(max(0.0, 1 - abs(delta) / max(observed_damage_value, 1)), 4)

    @staticmethod
    def _batch_candidate_score(
        total_abs_delta: int,
        samples: list[dict[str, Any]],
    ) -> float:
        observed_total = sum(
            int(sample["payload"].observed_damage_value)
            for sample in samples
        )
        return round(max(0.0, 1 - total_abs_delta / max(observed_total, 1)), 4)

    @staticmethod
    def _multipliers_from_result(
        explanation: dict[str, Any],
        context: DamageFormulaContext,
    ) -> dict[str, Any]:
        details = explanation.get("rule_resolution_details")
        if not isinstance(details, dict):
            details = context.rule_resolution_details
        return {
            "display_power": explanation.get("display_power"),
            "single_damage": explanation.get("single_damage"),
            "hit_count": explanation.get("hit_count"),
            "total_damage": explanation.get("total_damage"),
            "stab_multiplier": StandaloneDamageService._rule_detail_value(
                details,
                "stab_multiplier",
            ),
            "type_multiplier": StandaloneDamageService._rule_detail_value(
                details,
                "type_multiplier",
            ),
            "weather_multiplier": StandaloneDamageService._rule_detail_value(
                details,
                "weather_multiplier",
            ),
            "stat_stage_multiplier": StandaloneDamageService._rule_detail_value(
                details,
                "stat_stage_multiplier",
            ),
            "power_multiplier": str(context.power_multiplier),
            "damage_reductions": [str(item) for item in context.damage_reductions],
        }

    @staticmethod
    def _rule_detail_value(details: dict[str, Any], key: str) -> Any:
        value = details.get(key)
        if isinstance(value, dict):
            return value.get("value") or value.get("possible_multiplier")
        return None

    @staticmethod
    def _damage_percent(damage_value: int | None, max_hp: int) -> float | None:
        if damage_value is None or max_hp <= 0:
            return None
        return round(damage_value / max_hp * 100, 2)

    @staticmethod
    def _observed_comparison(
        observed: int | None,
        predicted: int | None,
    ) -> DamageCalculatorObservedComparisonOut | None:
        if observed is None:
            return None
        delta = observed - predicted if predicted is not None else None
        percent = (
            round(delta / predicted * 100, 2)
            if delta is not None and predicted not in {None, 0}
            else None
        )
        return DamageCalculatorObservedComparisonOut(
            observed_damage_value=observed,
            predicted_damage_value=predicted,
            delta_value=delta,
            delta_percent_of_prediction=percent,
            message="P1 仅展示真实伤害与理论伤害偏差；完整敌方配置枚举反推留到 P2。",
        )

    def _require_elf(self, elf_id: str) -> ElfDefinition:
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None or elf.deleted_at is not None:
            raise LookupError(f"Elf not found: {elf_id}")
        return elf

    def _require_skill(self, skill_id: str) -> SkillDefinition:
        skill = self.db.get(SkillDefinition, skill_id)
        if skill is None or skill.deleted_at is not None:
            raise LookupError(f"Skill not found: {skill_id}")
        return skill

    def _require_nature(self, nature_id: str) -> NatureDefinition:
        nature = self.db.get(NatureDefinition, nature_id)
        if nature is None or nature.deleted_at is not None:
            raise LookupError(f"Nature not found: {nature_id}")
        return nature

    @staticmethod
    def _element_types(elf: ElfDefinition) -> list[str]:
        raw = loads_json(elf.element_types_json, [])
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if item is not None]
