"""独立伤害计算器服务。

该服务只读取静态数据和可选的最近战斗快照信息，不创建战斗事件、不写入推算证据。
"""

from decimal import ROUND_FLOOR, Decimal
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
    DamageCalculatorAttackerCandidateOut,
    DamageCalculatorBattleOptionOut,
    DamageCalculatorBootstrapOut,
    DamageCalculatorCalculateInput,
    DamageCalculatorDefenderCandidateOut,
    DamageCalculatorInferAttackerInput,
    DamageCalculatorInferAttackerOut,
    DamageCalculatorInferDefenderInput,
    DamageCalculatorInferDefenderOut,
    DamageCalculatorLatestBattleOut,
    DamageCalculatorObservedComparisonOut,
    DamageCalculatorPanelOut,
    DamageCalculatorParticipantInput,
    DamageCalculatorParticipantOut,
    DamageCalculatorResultOut,
    DamageCalculatorTalentInput,
    DamageCalculatorTypeEffectivenessOut,
    StarfallComboCalculateInput,
    StarfallComboResultOut,
)
from app.services.estimate_service import EstimateService
from app.utils.json import loads_json


class StandaloneDamageService:
    """独立伤害计算器业务服务。"""

    TALENT_VALUES = (10,)
    TALENT_STAT_KEYS = (
        "hp",
        "physical_attack",
        "physical_defense",
        "magic_attack",
        "magic_defense",
        "speed",
    )

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
            base_power=self._effective_base_power(skill, payload.modifiers),
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

    def calculate_starfall_combo(
        self,
        payload: StarfallComboCalculateInput,
    ) -> StarfallComboResultOut:
        """计算只读触发技能伤害与星陨印记伤害。"""
        skill = self._require_skill(payload.trigger_skill_id)
        skill_payload = DamageCalculatorCalculateInput(
            attacker=payload.attacker,
            defender=payload.defender,
            skill_id=payload.trigger_skill_id,
            formula_type="attack",
            modifiers=payload.modifiers,
            notes=payload.notes,
        )
        skill_result = self.calculate(skill_payload)
        defender_hp = skill_result.defender.panel_stats.hp

        starfall_result = self._calculate_starfall_part(
            payload=payload,
            skill=skill,
            attacker=skill_result.attacker,
            defender=skill_result.defender,
        )

        skill_damage = skill_result.damage_value
        starfall_damage = (
            0
            if starfall_result.status == "not_triggered"
            else starfall_result.damage_value
        )
        total_damage = (
            skill_damage + starfall_damage
            if skill_damage is not None and starfall_damage is not None
            else None
        )
        missing_parts = list(
            dict.fromkeys(skill_result.missing_parts + starfall_result.missing_parts)
        )
        unknown_factors = list(
            dict.fromkeys(skill_result.unknown_factors + starfall_result.unknown_factors)
        )
        status = (
            "calculated"
            if total_damage is not None and not missing_parts
            else "partial"
        )
        remaining_hp = max(defender_hp - total_damage, 0) if total_damage is not None else None
        observed_comparison = self._observed_comparison(
            payload.observed_damage_value,
            total_damage,
        )

        return StarfallComboResultOut(
            status=status,
            attacker=skill_result.attacker,
            defender=skill_result.defender,
            trigger_skill_id=skill.skill_id,
            trigger_skill_name=skill.skill_name,
            starfall_layers=payload.starfall_layers,
            skill_damage_value=skill_damage,
            starfall_damage_value=starfall_damage,
            total_damage_value=total_damage,
            damage_percent=self._damage_percent(total_damage, defender_hp),
            remaining_hp=remaining_hp,
            is_kill=total_damage >= defender_hp if total_damage is not None else None,
            confidence=min(skill_result.confidence, starfall_result.confidence),
            missing_parts=missing_parts,
            unknown_factors=unknown_factors,
            skill_result=skill_result,
            starfall_result=starfall_result,
            observed_comparison=observed_comparison,
        )

    def _calculate_starfall_part(
        self,
        *,
        payload: StarfallComboCalculateInput,
        skill: SkillDefinition,
        attacker: DamageCalculatorParticipantOut,
        defender: DamageCalculatorParticipantOut,
    ) -> DamageCalculatorResultOut:
        """计算星陨印记段伤害；未触发时返回 0 伤害。"""
        if payload.starfall_layers <= 0:
            return DamageCalculatorResultOut(
                status="not_triggered",
                formula_type="starfall",
                attacker=attacker,
                defender=defender,
                skill_id=skill.skill_id,
                skill_name=skill.skill_name,
                damage_value=0,
                damage_percent=0,
                confidence=1.0,
                explanation={
                    "trigger_condition": "starfall_layers_positive",
                    "starfall_layers": payload.starfall_layers,
                    "reason": "starfall_layers_zero",
                },
            )

        attacker_panel = PanelStats(**attacker.panel_stats.model_dump())
        defender_panel = PanelStats(**defender.panel_stats.model_dump())
        context = DamageFormulaContext(
            battle_id="standalone_starfall_calculator",
            formula_type="starfall",
            attacker_side="self",
            attacker_elf_id=attacker.elf_id,
            defender_side="enemy",
            defender_elf_id=defender.elf_id,
            skill_id=skill.skill_id,
            skill_element_type=skill.element_type,
            skill_category=skill.skill_category,
            trigger_skill_id=skill.skill_id,
            trigger_skill_element_type=skill.element_type,
            trigger_skill_category=skill.skill_category,
            attacker_panel_stats=attacker_panel,
            defender_panel_stats=defender_panel,
            defender_max_hp=defender_panel.hp,
            attacker_element_types=attacker.element_types,
            defender_element_types=defender.element_types,
            effect_id="effect_starfall_mark",
            effect_layers=payload.starfall_layers,
            starfall_element_type="illusion",
            notes=payload.notes,
        )
        if payload.modifiers.damage_reductions:
            context.damage_reductions = [
                Decimal(str(item)) for item in payload.modifiers.damage_reductions
            ]
        resolver_payload: dict[str, Any] = {"resolve_rules": True}
        if payload.modifiers.damage_reductions:
            resolver_payload["damage_reductions"] = payload.modifiers.damage_reductions
        if payload.starfall_type_multiplier is not None:
            context.type_multiplier = Decimal(str(payload.starfall_type_multiplier))
            resolver_payload["type_multiplier"] = payload.starfall_type_multiplier

        resolved_context = RuleResolver(self.db).resolve_damage_context(context, resolver_payload)
        result = DamageCalculator().calculate(resolved_context)
        starfall_damage = 0 if result.status == "not_triggered" else result.damage_value
        return DamageCalculatorResultOut(
            status=result.status,
            formula_type=result.formula_type,
            attacker=attacker,
            defender=defender,
            skill_id=skill.skill_id,
            skill_name=skill.skill_name,
            damage_value=starfall_damage,
            damage_percent=self._damage_percent(starfall_damage, defender_panel.hp),
            confidence=result.confidence,
            missing_parts=result.missing_parts,
            unknown_factors=result.unknown_factors,
            explanation=result.explanation,
            multipliers=self._multipliers_from_result(result.explanation, resolved_context),
        )

    def infer_defender(
        self,
        payload: DamageCalculatorInferDefenderInput,
    ) -> DamageCalculatorInferDefenderOut:
        """枚举防御方性格和关键资质，按扣血百分比/真实伤害返回软候选。"""
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
        nature_by_id = {nature.nature_id: nature for nature in natures}
        default_config_rule = EstimateService(self.db)._default_config_rule_for_elf(defender_elf)

        observed_hp_percent_delta = self._observed_hp_percent_delta(payload)
        modifiers = self._infer_modifiers(payload)
        resolved_context_template = self._resolved_infer_context_template(
            skill=skill,
            attacker=attacker,
            attacker_panel=attacker_panel,
            defender_elf=defender_elf,
            modifiers=modifiers,
            notes=payload.notes,
        )
        calculator = DamageCalculator()
        relevant_defense_stat = (
            "physical_defense" if skill.skill_category == "physical" else "magic_defense"
        )
        candidates: list[DamageCalculatorDefenderCandidateOut] = []
        calculation_cache: dict[
            tuple[str, int, int],
            tuple[Any, float | None, Decimal | None],
        ] = {}
        searched_count = 0
        for nature in natures:
            for template_name, talents in self._candidate_talent_options(
                relevant_defense_stats=[relevant_defense_stat],
            ):
                searched_count += 1
                hp_talent = int(talents.hp)
                defense_talent = int(getattr(talents, relevant_defense_stat))
                defender_panel = self._calculate_panel(defender_elf, nature, talents)
                cache_key = (nature.nature_id, hp_talent, defense_talent)
                cached = calculation_cache.get(cache_key)
                if cached is None:
                    result = self._calculate_with_resolved_context(
                        calculator=calculator,
                        resolved_context_template=resolved_context_template,
                        defender_nature=nature,
                        defender_panel=defender_panel,
                    )
                    predicted_damage_percent = self._damage_percent(
                        result.damage_value,
                        defender_panel.hp,
                    )
                    predicted_damage_percent_exact = self._damage_percent_decimal(
                        result.damage_value,
                        defender_panel.hp,
                    )
                    calculation_cache[cache_key] = (
                        result,
                        predicted_damage_percent,
                        predicted_damage_percent_exact,
                    )
                else:
                    result, predicted_damage_percent, predicted_damage_percent_exact = cached
                delta = (
                    result.damage_value - payload.observed_damage_value
                    if result.damage_value is not None and payload.observed_damage_value is not None
                    else None
                )
                delta_damage_percent = (
                    round(
                        float(
                            predicted_damage_percent_exact
                            - Decimal(str(observed_hp_percent_delta))
                        ),
                        4,
                    )
                    if predicted_damage_percent_exact is not None
                    and observed_hp_percent_delta is not None
                    else None
                )
                combined_error = self._candidate_combined_error(
                    delta_value=delta,
                    observed_damage_value=payload.observed_damage_value,
                    delta_damage_percent=delta_damage_percent,
                    observed_hp_percent_delta=observed_hp_percent_delta,
                )
                matched = self._candidate_matches(
                    delta,
                    delta_damage_percent,
                    predicted_damage_percent_exact=predicted_damage_percent_exact,
                    payload=payload,
                    has_observed_damage=payload.observed_damage_value is not None,
                    has_observed_percent=observed_hp_percent_delta is not None,
                )
                if not matched:
                    continue
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
                        predicted_damage_percent=predicted_damage_percent,
                        delta_value=delta,
                        absolute_delta=abs(delta) if delta is not None else None,
                        delta_damage_percent=delta_damage_percent,
                        absolute_delta_damage_percent=(
                            abs(delta_damage_percent)
                            if delta_damage_percent is not None
                            else None
                        ),
                        combined_error=combined_error,
                        score=self._candidate_score(combined_error),
                        matched_within_tolerance=matched,
                        unknown_factors=result.unknown_factors,
                        missing_parts=result.missing_parts,
                    )
                )

        sorted_candidates_all = sorted(
            candidates,
            key=lambda item: (
                item.combined_error if item.combined_error is not None else 10**9,
                item.absolute_delta_damage_percent
                if item.absolute_delta_damage_percent is not None
                else 10**9,
                item.absolute_delta if item.absolute_delta is not None else 10**9,
                self._positive_nature_talent_missing(item, nature_by_id),
                self._default_config_preference(item, default_config_rule, nature_by_id),
                -item.score,
                item.nature_name,
                item.hp_talent,
                item.defense_talent,
                item.template_name or "",
            ),
        )
        sorted_candidates = self._diversify_candidates_by_positive_stat(
            sorted_candidates_all,
            natures=natures,
            top_n=payload.top_n,
        )
        for index, candidate in enumerate(sorted_candidates, start=1):
            candidate.rank = index

        return DamageCalculatorInferDefenderOut(
            status="ranked" if sorted_candidates else "no_matching_candidates",
            observed_damage_value=payload.observed_damage_value,
            observed_hp_percent_delta=observed_hp_percent_delta,
            observed_hp_percent_before=payload.observed_hp_percent_before,
            observed_hp_percent_after=payload.observed_hp_percent_after,
            skill_id=skill.skill_id,
            skill_name=skill.skill_name,
            searched_candidate_count=searched_count,
            returned_candidate_count=len(sorted_candidates),
            candidates=sorted_candidates,
            assumptions=[
                "反推默认枚举完整三维满资质配置；每个候选都会返回完整六维资质分布。",
                "后端用受击前后血量百分比自行计算扣血百分比；前端无需额外填写扣血百分比。",
                "整数血量百分比按游戏显示的伤害百分比向下取整匹配；"
                "返回结果只保留同时满足真实伤害和血量百分比显示的候选；"
                "若没有严格候选，会返回空列表而不是展示明显不可能的配置。",
                "独立计算器只读枚举候选，不写入 EnemyPanelEstimate，也不影响战斗事件流。",
                "结果复用当前项目伤害公式；若公式或状态上下文仍有 unknown factors，应降低置信度。",
            ],
        )

    def infer_attacker(
        self,
        payload: DamageCalculatorInferAttackerInput,
    ) -> DamageCalculatorInferAttackerOut:
        """枚举攻击方性格和三维资质，按真实伤害返回软候选。"""
        skill = self._require_skill(payload.skill_id)
        if skill.skill_category not in {"physical", "magic"}:
            raise ValueError("当前反推只支持物理/魔法攻击技能")
        attacker_elf = self._require_elf(payload.attacker_elf_id)
        defender = self._build_participant(payload.defender)
        defender_panel = PanelStats(**defender.panel_stats.model_dump())
        natures = list(
            self.db.scalars(
                select(NatureDefinition)
                .where(NatureDefinition.deleted_at.is_(None))
                .order_by(NatureDefinition.nature_name)
            ).all()
        )
        if not natures:
            raise ValueError("缺少性格定义，无法反推攻击方配置")
        nature_by_id = {nature.nature_id: nature for nature in natures}

        modifiers = payload.modifiers
        resolved_context_template = self._resolved_attacker_infer_context_template(
            skill=skill,
            attacker_elf=attacker_elf,
            defender=defender,
            defender_panel=defender_panel,
            modifiers=modifiers,
            notes=payload.notes,
        )
        calculator = DamageCalculator()
        relevant_attack_stat = (
            "physical_attack" if skill.skill_category == "physical" else "magic_attack"
        )
        candidates: list[DamageCalculatorAttackerCandidateOut] = []
        searched_count = 0
        for nature in natures:
            for template_name, talents in self._candidate_talent_options(
                relevant_defense_stats=[],
            ):
                searched_count += 1
                attack_talent = int(getattr(talents, relevant_attack_stat))
                attacker_panel = self._calculate_panel(attacker_elf, nature, talents)
                result = self._calculate_with_resolved_attacker_context(
                    calculator=calculator,
                    resolved_context_template=resolved_context_template,
                    attacker_nature=nature,
                    attacker_panel=attacker_panel,
                )
                delta = (
                    result.damage_value - payload.observed_damage_value
                    if result.damage_value is not None
                    else None
                )
                if delta != 0:
                    continue
                combined_error = self._candidate_combined_error(
                    delta_value=delta,
                    observed_damage_value=payload.observed_damage_value,
                    delta_damage_percent=None,
                    observed_hp_percent_delta=None,
                )
                candidates.append(
                    DamageCalculatorAttackerCandidateOut(
                        rank=0,
                        template_name=template_name,
                        nature_id=nature.nature_id,
                        nature_name=nature.nature_name,
                        individual_talent_distribution=DamageCalculatorTalentInput(
                            **talents.model_dump()
                        ),
                        relevant_attack_stat=relevant_attack_stat,
                        attack_talent=attack_talent,
                        panel_stats=DamageCalculatorPanelOut(**attacker_panel.model_dump()),
                        predicted_damage_value=result.damage_value,
                        delta_value=delta,
                        absolute_delta=abs(delta) if delta is not None else None,
                        score=self._candidate_score(combined_error),
                        matched_within_tolerance=True,
                        is_relevant_attack_positive_nature=(
                            nature.positive_stat == relevant_attack_stat
                        ),
                        has_relevant_attack_talent=attack_talent > 0,
                        unknown_factors=result.unknown_factors,
                        missing_parts=result.missing_parts,
                    )
                )

        sorted_candidates_all = sorted(
            candidates,
            key=lambda item: (
                item.absolute_delta if item.absolute_delta is not None else 10**9,
                not item.is_relevant_attack_positive_nature,
                not item.has_relevant_attack_talent,
                self._irrelevant_attack_stat_penalty(
                    item,
                    nature_by_id,
                    relevant_attack_stat=relevant_attack_stat,
                ),
                self._defensive_positive_nature_penalty(item, nature_by_id),
                self._positive_nature_talent_missing(item, nature_by_id),
                item.nature_name,
                item.template_name or "",
            ),
        )
        sorted_candidates = self._diversify_attacker_candidates_by_positive_stat(
            sorted_candidates_all,
            natures=natures,
            top_n=payload.top_n,
        )
        for index, candidate in enumerate(sorted_candidates, start=1):
            candidate.rank = index

        return DamageCalculatorInferAttackerOut(
            status="ranked" if sorted_candidates else "no_matching_candidates",
            observed_damage_value=payload.observed_damage_value,
            skill_id=skill.skill_id,
            skill_name=skill.skill_name,
            searched_candidate_count=searched_count,
            returned_candidate_count=len(sorted_candidates),
            relevant_attack_stat=relevant_attack_stat,
            candidates=sorted_candidates,
            assumptions=[
                "反推攻击方默认枚举完整三维满资质配置；每个候选都会返回完整六维资质分布。",
                "候选必须与真实伤害值完全一致；若没有候选，会返回空列表。",
                "结果会标记是否为对应攻击属性正修性格，以及是否点了对应攻击资质。",
                "独立计算器只读枚举候选，不写入 EnemyPanelEstimate，也不影响战斗事件流。",
                "结果复用当前项目伤害公式；若公式或状态上下文仍有 unknown factors，应降低置信度。",
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
            base_power=self._effective_base_power(skill, modifiers),
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

    def _resolved_infer_context_template(
        self,
        *,
        skill: SkillDefinition,
        attacker: DamageCalculatorParticipantOut,
        attacker_panel: PanelStats,
        defender_elf: ElfDefinition,
        modifiers: Any,
        notes: str | None,
    ) -> DamageFormulaContext:
        """反推枚举前只解析一次与候选面板无关的规则，避免每个候选重复查库。"""
        placeholder_panel = PanelStats(
            hp=1,
            physical_attack=1,
            physical_defense=1,
            magic_attack=1,
            magic_defense=1,
            speed=1,
        )
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
            base_power=self._effective_base_power(skill, modifiers),
            attacker_panel_stats=attacker_panel,
            defender_panel_stats=placeholder_panel,
            defender_max_hp=placeholder_panel.hp,
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
        return RuleResolver(self.db).resolve_damage_context(context, resolver_payload)

    def _resolved_attacker_infer_context_template(
        self,
        *,
        skill: SkillDefinition,
        attacker_elf: ElfDefinition,
        defender: DamageCalculatorParticipantOut,
        defender_panel: PanelStats,
        modifiers: Any,
        notes: str | None,
    ) -> DamageFormulaContext:
        """反推攻击方前只解析一次与候选攻击面板无关的规则。"""
        placeholder_panel = PanelStats(
            hp=1,
            physical_attack=1,
            physical_defense=1,
            magic_attack=1,
            magic_defense=1,
            speed=1,
        )
        context = DamageFormulaContext(
            battle_id="standalone_damage_calculator",
            formula_type="attack",
            attacker_side="enemy",
            attacker_elf_id=attacker_elf.elf_id,
            defender_side="self",
            defender_elf_id=defender.elf_id,
            skill_id=skill.skill_id,
            skill_element_type=skill.element_type,
            skill_category=skill.skill_category,
            base_power=self._effective_base_power(skill, modifiers),
            attacker_panel_stats=placeholder_panel,
            defender_panel_stats=defender_panel,
            defender_max_hp=defender_panel.hp,
            defender_hp_percent=modifiers.defender_hp_percent,
            attacker_element_types=self._element_types(attacker_elf),
            defender_element_types=defender.element_types,
            response_attack_success=modifiers.response_attack_success,
            response_defense_success=modifiers.response_defense_success,
            response_status_success=modifiers.response_status_success,
            notes=notes,
        )
        self._apply_modifier_values(context, modifiers)
        resolver_payload = self._resolver_payload_from_modifiers(modifiers)
        return RuleResolver(self.db).resolve_damage_context(context, resolver_payload)

    @staticmethod
    def _calculate_with_resolved_context(
        *,
        calculator: DamageCalculator,
        resolved_context_template: DamageFormulaContext,
        defender_nature: NatureDefinition,
        defender_panel: PanelStats,
    ) -> Any:
        """复用已解析规则模板，只替换候选防御方面板后计算伤害。"""
        context = resolved_context_template.model_copy(
            deep=True,
            update={
                "defender_panel_stats": defender_panel,
                "defender_max_hp": defender_panel.hp,
            },
        )
        result = calculator.calculate(context)
        result.explanation.setdefault(
            "defender_candidate",
            {
                "nature_id": defender_nature.nature_id,
                "nature_name": defender_nature.nature_name,
            },
        )
        return result

    @staticmethod
    def _calculate_with_resolved_attacker_context(
        *,
        calculator: DamageCalculator,
        resolved_context_template: DamageFormulaContext,
        attacker_nature: NatureDefinition,
        attacker_panel: PanelStats,
    ) -> Any:
        """复用已解析规则模板，只替换候选攻击方面板后计算伤害。"""
        context = resolved_context_template.model_copy(
            deep=True,
            update={
                "attacker_panel_stats": attacker_panel,
            },
        )
        result = calculator.calculate(context)
        result.explanation.setdefault(
            "attacker_candidate",
            {
                "nature_id": attacker_nature.nature_id,
                "nature_name": attacker_nature.nature_name,
            },
        )
        return result

    @staticmethod
    def _observed_hp_percent_delta(payload: DamageCalculatorInferDefenderInput) -> float | None:
        """解析本次敌方扣血百分比；直接填写优先，其次用前后百分比相减。"""
        if payload.observed_hp_percent_delta is not None:
            return payload.observed_hp_percent_delta
        if (
            payload.observed_hp_percent_before is not None
            and payload.observed_hp_percent_after is not None
        ):
            return round(payload.observed_hp_percent_before - payload.observed_hp_percent_after, 4)
        return None

    @staticmethod
    def _infer_modifiers(payload: DamageCalculatorInferDefenderInput) -> Any:
        """反推修正项；目标血量上下文字段已弃用，不再自动补齐。"""
        return payload.modifiers

    @classmethod
    def _candidate_talent_options(
        cls,
        *,
        relevant_defense_stats: list[str],
    ) -> list[tuple[str | None, IndividualTalentDistribution]]:
        return cls._complete_three_stat_talent_options(relevant_defense_stats)

    @classmethod
    def _complete_three_stat_talent_options(
        cls,
        relevant_defense_stats: list[str],
    ) -> list[tuple[str | None, IndividualTalentDistribution]]:
        """枚举完整三维资质配置。

        前端录入和项目配置页的口径是：被培养的维度取 7-10，未培养维度为 0。
        反推时不能只输出 HP/防御两个数，否则会让候选看起来像“不完整配置”。
        """
        relevant_defense_stat = (
            "physical_defense"
            if "physical_defense" in relevant_defense_stats
            else "magic_defense"
        )
        options: list[tuple[str | None, IndividualTalentDistribution]] = []
        stat_keys = cls.TALENT_STAT_KEYS
        for first_index, first_stat in enumerate(stat_keys):
            for second_index in range(first_index + 1, len(stat_keys)):
                second_stat = stat_keys[second_index]
                for third_index in range(second_index + 1, len(stat_keys)):
                    selected_stats = (first_stat, second_stat, stat_keys[third_index])
                    template_name = "+".join(
                        cls._talent_stat_label(item)
                        for item in selected_stats
                    )
                    for first_value in cls.TALENT_VALUES:
                        for second_value in cls.TALENT_VALUES:
                            for third_value in cls.TALENT_VALUES:
                                values = dict.fromkeys(stat_keys, 0)
                                values[selected_stats[0]] = first_value
                                values[selected_stats[1]] = second_value
                                values[selected_stats[2]] = third_value
                                options.append(
                                    (
                                        template_name,
                                        IndividualTalentDistribution(**values),
                                    )
                                )

        # 让包含 HP/相关防御的完整配置优先参与排序展示；不丢弃其它合法三维配置。
        return sorted(
            options,
            key=lambda item: (
                item[1].hp == 0,
                getattr(item[1], relevant_defense_stat) == 0,
                item[0] or "",
            ),
        )

    @staticmethod
    def _talent_stat_label(stat_key: str) -> str:
        labels = {
            "hp": "生命",
            "physical_attack": "物攻",
            "physical_defense": "物防",
            "magic_attack": "魔攻",
            "magic_defense": "魔防",
            "speed": "速度",
        }
        return labels.get(stat_key, stat_key)

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
            "base_power_override",
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
    def _effective_base_power(skill: SkillDefinition, modifiers: Any) -> int | None:
        """读取自填技能威力；留空时使用静态技能威力。"""
        return modifiers.base_power_override or skill.base_power

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
    def _candidate_combined_error(
        *,
        delta_value: int | None,
        observed_damage_value: int | None,
        delta_damage_percent: float | None,
        observed_hp_percent_delta: float | None,
    ) -> float | None:
        """把伤害值偏差和百分比偏差归一化后合并，供单次软排序。"""
        parts: list[float] = []
        if delta_value is not None and observed_damage_value is not None:
            parts.append(abs(delta_value) / max(observed_damage_value, 1))
        if delta_damage_percent is not None and observed_hp_percent_delta is not None:
            parts.append(abs(delta_damage_percent) / max(observed_hp_percent_delta, 0.01))
        if not parts:
            return None
        return round(sum(parts), 6)

    @staticmethod
    def _candidate_score(combined_error: float | None) -> float:
        if combined_error is None:
            return 0.0
        return round(max(0.0, 1 - combined_error), 4)

    @staticmethod
    def _diversify_candidates_by_positive_stat(
        candidates: list[DamageCalculatorDefenderCandidateOut],
        *,
        natures: list[NatureDefinition],
        top_n: int,
    ) -> list[DamageCalculatorDefenderCandidateOut]:
        """返回候选时优先覆盖不同正面性格，避免等价候选被全局 top_n 截断误解为排除。"""
        if len(candidates) <= top_n:
            return candidates

        positive_stat_by_nature_id = {nature.nature_id: nature.positive_stat for nature in natures}
        selected: list[DamageCalculatorDefenderCandidateOut] = []
        selected_keys: set[tuple[str, int, int, str | None]] = set()
        covered_positive_stats: set[str] = set()

        def candidate_key(
            candidate: DamageCalculatorDefenderCandidateOut,
        ) -> tuple[str, int, int, str | None]:
            return (
                candidate.nature_id,
                candidate.hp_talent,
                candidate.defense_talent,
                candidate.template_name,
            )

        for candidate in candidates:
            positive_stat = positive_stat_by_nature_id.get(candidate.nature_id, candidate.nature_id)
            if positive_stat in covered_positive_stats:
                continue
            selected.append(candidate)
            selected_keys.add(candidate_key(candidate))
            covered_positive_stats.add(positive_stat)
            if len(selected) >= top_n:
                return selected

        for candidate in candidates:
            key = candidate_key(candidate)
            if key in selected_keys:
                continue
            selected.append(candidate)
            selected_keys.add(key)
            if len(selected) >= top_n:
                break
        return selected

    @staticmethod
    def _diversify_attacker_candidates_by_positive_stat(
        candidates: list[DamageCalculatorAttackerCandidateOut],
        *,
        natures: list[NatureDefinition],
        top_n: int,
    ) -> list[DamageCalculatorAttackerCandidateOut]:
        """返回攻击方候选时优先覆盖不同正面性格，避免加速等性格被 top_n 截断。"""
        if len(candidates) <= top_n:
            return candidates

        positive_stat_by_nature_id = {nature.nature_id: nature.positive_stat for nature in natures}
        selected: list[DamageCalculatorAttackerCandidateOut] = []
        selected_keys: set[tuple[str, int, str | None]] = set()
        covered_positive_stats: set[str] = set()

        def candidate_key(
            candidate: DamageCalculatorAttackerCandidateOut,
        ) -> tuple[str, int, str | None]:
            return (
                candidate.nature_id,
                candidate.attack_talent,
                candidate.template_name,
            )

        for candidate in candidates:
            positive_stat = positive_stat_by_nature_id.get(candidate.nature_id, candidate.nature_id)
            if positive_stat in covered_positive_stats:
                continue
            selected.append(candidate)
            selected_keys.add(candidate_key(candidate))
            covered_positive_stats.add(positive_stat)
            if len(selected) >= top_n:
                return selected

        for candidate in candidates:
            key = candidate_key(candidate)
            if key in selected_keys:
                continue
            selected.append(candidate)
            selected_keys.add(key)
            if len(selected) >= top_n:
                break
        return selected

    @staticmethod
    def _default_config_preference(
        candidate: DamageCalculatorDefenderCandidateOut,
        default_config_rule: dict[str, Any],
        nature_by_id: dict[str, NatureDefinition],
    ) -> tuple[int, int, int]:
        """
        按敌方默认配置文档给候选排序加偏好，不新增候选也不硬排除。

        伤害/百分比命中误差仍然是主排序；这里仅在误差相近时，让“该精灵默认最适合的
        性格 + 三维 10 资质”更靠前，避免玩家优先看到随机等价配置。
        """
        nature = nature_by_id.get(candidate.nature_id)
        if nature is None:
            return (99, 99, 99)

        preferred_positive = default_config_rule.get("positive_stat")
        preferred_negative = default_config_rule.get("negative_stat")
        preferred_talents = default_config_rule.get("talents")
        if isinstance(preferred_positive, StatKey):
            preferred_positive = preferred_positive.value
        if isinstance(preferred_negative, StatKey):
            preferred_negative = preferred_negative.value

        if (
            nature.positive_stat == preferred_positive
            and nature.negative_stat == preferred_negative
        ):
            nature_rank = 0
        elif nature.positive_stat == preferred_positive:
            nature_rank = 1
        else:
            nature_rank = 2

        talent_rank = 2
        candidate_talents = candidate.individual_talent_distribution.model_dump()
        if isinstance(preferred_talents, dict):
            preferred_as_ints = {
                key: int(value)
                for key, value in preferred_talents.items()
                if key in candidate_talents
            }
            candidate_as_ints = {
                key: int(value)
                for key, value in candidate_talents.items()
            }
            if candidate_as_ints == preferred_as_ints:
                talent_rank = 0
            else:
                preferred_positive_stats = {
                    key
                    for key, value in preferred_as_ints.items()
                    if value > 0
                }
                candidate_positive_stats = {
                    key
                    for key, value in candidate_as_ints.items()
                    if value > 0
                }
                if candidate_positive_stats == preferred_positive_stats:
                    talent_rank = 1

        combined_rank = 0 if nature_rank == 0 and talent_rank == 0 else 1
        return (combined_rank, nature_rank, talent_rank)

    @staticmethod
    def _positive_nature_talent_missing(
        candidate: DamageCalculatorDefenderCandidateOut | DamageCalculatorAttackerCandidateOut,
        nature_by_id: dict[str, NatureDefinition],
    ) -> bool:
        """同误差候选中，优先展示点了正面性格对应资质的三维配置。"""
        nature = nature_by_id.get(candidate.nature_id)
        if nature is None or nature.positive_stat not in StandaloneDamageService.TALENT_STAT_KEYS:
            return True
        talents = candidate.individual_talent_distribution.model_dump()
        return int(talents.get(nature.positive_stat, 0) or 0) <= 0

    @staticmethod
    def _irrelevant_attack_stat_penalty(
        candidate: DamageCalculatorAttackerCandidateOut,
        nature_by_id: dict[str, NatureDefinition],
        *,
        relevant_attack_stat: str,
    ) -> int:
        """反推攻击方时，降低与本技能攻击类型无关的另一攻性格/资质权重。"""
        irrelevant_attack_stat_by_relevant = {
            "physical_attack": "magic_attack",
            "magic_attack": "physical_attack",
        }
        irrelevant_attack_stat = irrelevant_attack_stat_by_relevant.get(relevant_attack_stat)
        if irrelevant_attack_stat is None:
            return 0

        nature = nature_by_id.get(candidate.nature_id)
        penalty = 0
        if nature is not None and nature.positive_stat == irrelevant_attack_stat:
            penalty += 1

        talents = candidate.individual_talent_distribution.model_dump()
        if int(talents.get(irrelevant_attack_stat, 0) or 0) > 0:
            penalty += 1
        return penalty

    @staticmethod
    def _defensive_positive_nature_penalty(
        candidate: DamageCalculatorAttackerCandidateOut,
        nature_by_id: dict[str, NatureDefinition],
    ) -> int:
        """反推攻击方同权重排序时，降低物防+/魔防+这类防御性格的展示优先级。"""
        nature = nature_by_id.get(candidate.nature_id)
        if nature is None:
            return 0
        return 1 if nature.positive_stat in {"physical_defense", "magic_defense"} else 0

    @staticmethod
    def _candidate_matches(
        delta_value: int | None,
        delta_damage_percent: float | None,
        *,
        predicted_damage_percent_exact: Decimal | None,
        payload: DamageCalculatorInferDefenderInput,
        has_observed_damage: bool,
        has_observed_percent: bool,
    ) -> bool:
        """判断是否命中；整数百分比按游戏显示的伤害百分比向下取整校验。"""
        if has_observed_damage and delta_value != 0:
            return False
        if has_observed_percent:
            if payload.observed_hp_percent_before is not None and (
                payload.observed_hp_percent_after is not None
            ):
                if not StandaloneDamageService._remaining_hp_percent_matches(
                    before=payload.observed_hp_percent_before,
                    after=payload.observed_hp_percent_after,
                    predicted_damage_percent_exact=predicted_damage_percent_exact,
                ):
                    return False
            elif delta_damage_percent is None or abs(delta_damage_percent) > 0.05:
                return False
        return has_observed_damage or has_observed_percent

    @staticmethod
    def _remaining_hp_percent_matches(
        *,
        before: float,
        after: float,
        predicted_damage_percent_exact: Decimal | None,
    ) -> bool:
        """校验候选伤害百分比是否匹配录入扣血百分比。

        游戏内百分比看不到小数；当玩家录入的是整数百分比时，按“本次伤害百分比
        向下取整”匹配，即理论值落在 [N%, N+1%) 都视为显示 N%。
        """
        if predicted_damage_percent_exact is None:
            return False
        observed_delta = Decimal(str(before)) - Decimal(str(after))
        if observed_delta <= 0:
            return False
        if StandaloneDamageService._is_integer_percent(observed_delta):
            displayed_predicted_delta = predicted_damage_percent_exact.to_integral_value(
                rounding=ROUND_FLOOR
            )
            return displayed_predicted_delta == observed_delta.to_integral_value()
        return abs(predicted_damage_percent_exact - observed_delta) <= Decimal("0.05")

    @staticmethod
    def _is_integer_percent(value: Decimal) -> bool:
        """判断录入百分比是否等价于整数显示值。"""
        return abs(value - value.to_integral_value()) <= Decimal("0.0001")

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
    def _damage_percent_decimal(damage_value: int | None, max_hp: int) -> Decimal | None:
        """计算未四舍五入的伤害百分比，供向下取整显示匹配使用。"""
        if damage_value is None or max_hp <= 0:
            return None
        return (Decimal(damage_value) / Decimal(max_hp)) * Decimal(100)

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
            message="仅展示真实伤害与理论伤害偏差；不会写入战斗推算 evidence。",
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
