"""伤害规则解析器雏形。

RuleResolver 位于“规则数据/事件上下文”和“纯数学公式”之间：
它负责把技能、属性、应对成功、减伤来源等业务规则解析为
``DamageFormulaContext`` 中的倍率字段；DamageCalculator 仍只做数学计算。

第四阶段只实现可验证的最小闭环：
- 从 skill_id 读取技能属性、类别和基础威力；
- 从精灵定义或 payload 读取双方系别；
- 计算本系加成；
- 按项目数学建模文档计算单双属性克制倍率；
- 解析应对成功倍率和基础减伤来源。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculation.formula_context import DamageFormulaContext
from app.calculation.modifier_resolver import ModifierResolver
from app.calculation.response_resolver import ResponseResolver
from app.models.battle import BattleSkillSlot
from app.models.static import ElfDefinition, SkillDefinition, TypeEffectivenessRule
from app.utils.json import loads_json


class RuleResolver:
    """把可结构化规则解析为伤害公式上下文。"""

    DEFAULT_STAB_MULTIPLIER = Decimal("1.25")

    def __init__(self, db: Session | None = None) -> None:
        self.db = db
        self.modifier_resolver = ModifierResolver(db)
        self.response_resolver = ResponseResolver()

    def resolve_damage_context(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any] | None = None,
    ) -> DamageFormulaContext:
        """解析普通攻击伤害所需的规则字段。

        该方法会原地补全并返回 ``context``。这样可以避免在实时估计链路中频繁复制大型对象，
        也让后续 evidence 能直接看到最终参与计算的上下文。
        """
        payload = dict(payload or {})
        if not self._payload_bool(payload, "resolve_rules", False):
            return context

        details: dict[str, Any] = {}
        self._fill_skill_definition(context, details)
        self._fill_runtime_skill_slot(context, details)
        self._fill_element_types(context, payload, details)
        self._load_attack_skill_response_rule(context, payload, details)
        self._record_condition_flags(payload, details)
        details.update(self.response_resolver.resolve_response_modifiers(context, payload))
        self._resolve_stab_multiplier(context, payload, details)
        self._resolve_type_multiplier(context, payload, details)
        details.update(self.modifier_resolver.resolve_formula_modifiers(context, payload))

        context.rule_resolution_enabled = True
        context.rule_resolution_details = details
        return context

    def _fill_skill_definition(
        self,
        context: DamageFormulaContext,
        details: dict[str, Any],
    ) -> None:
        """根据 skill_id 尝试从静态技能表补全技能基础字段。"""
        if self.db is None or not context.skill_id:
            return
        skill = self.db.get(SkillDefinition, context.skill_id)
        if skill is None or skill.deleted_at is not None:
            context.unknown_factors.append(f"skill_definition_missing:{context.skill_id}")
            return

        if context.skill_category is None:
            context.skill_category = skill.skill_category
        if context.base_power is None:
            context.base_power = skill.base_power
        if context.skill_element_type is None:
            context.skill_element_type = skill.element_type
        details["skill_definition"] = {
            "skill_id": skill.skill_id,
            "element_type": skill.element_type,
            "skill_category": skill.skill_category,
            "base_power": skill.base_power,
        }

    def _fill_runtime_skill_slot(
        self,
        context: DamageFormulaContext,
        details: dict[str, Any],
    ) -> None:
        """读取当前战斗技能槽覆盖值；没有覆盖时不改变静态技能定义。"""
        if (
            self.db is None
            or not context.battle_id
            or not context.attacker_side
            or not context.attacker_elf_id
            or not context.skill_id
        ):
            return
        slot = self.db.scalars(
            select(BattleSkillSlot).where(
                BattleSkillSlot.battle_id == context.battle_id,
                BattleSkillSlot.side == context.attacker_side,
                BattleSkillSlot.elf_id == context.attacker_elf_id,
                BattleSkillSlot.skill_id == context.skill_id,
            )
        ).first()
        if slot is None:
            return
        if slot.current_power is not None:
            context.base_power = slot.current_power
        details["skill_slot_runtime"] = {
            "slot_id": slot.slot_id,
            "current_energy_cost": slot.current_energy_cost,
            "current_power": slot.current_power,
            "cooldown_remaining": slot.cooldown_remaining,
            "base_power_overridden": slot.current_power is not None,
        }

    def _load_attack_skill_response_rule(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """从攻击技能规则中自动带入应对分支，缺少成功标记时只记录 unknown。"""
        if (
            payload.get("response_rule") is not None
            or payload.get("skill_response_rule") is not None
        ):
            return
        if self.db is None or not context.skill_id:
            return
        skill = self.db.get(SkillDefinition, context.skill_id)
        if skill is None or skill.deleted_at is not None:
            return
        rule = loads_json(skill.damage_rule_json, {})
        if not isinstance(rule, dict):
            return
        response_rule = rule.get("response_rule")
        if not isinstance(response_rule, dict):
            return
        payload["skill_response_rule"] = response_rule
        details["attack_skill_response_rule"] = {
            "source": "skill_definition.damage_rule_json",
            "skill_id": skill.skill_id,
            "target": response_rule.get("target"),
            "condition": response_rule.get("condition"),
            "modifier": response_rule.get("modifier") or "response_multiplier",
        }

    @staticmethod
    def _record_condition_flags(payload: dict[str, Any], details: dict[str, Any]) -> None:
        flags = payload.get("condition_flags")
        if isinstance(flags, dict) and flags:
            details["condition_flags"] = {
                str(key): bool(value)
                for key, value in flags.items()
                if isinstance(key, str) and isinstance(value, bool)
            }

    def _fill_element_types(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """从 payload 或精灵定义中补齐攻击方、防御方和技能系别。"""
        if payload.get("skill_element_type") and context.skill_element_type is None:
            context.skill_element_type = str(payload["skill_element_type"])
        if payload.get("attacker_element_types"):
            context.attacker_element_types = self._normalize_element_types(
                payload.get("attacker_element_types")
            )
        if payload.get("defender_element_types"):
            context.defender_element_types = self._normalize_element_types(
                payload.get("defender_element_types")
            )

        if not context.attacker_element_types and context.attacker_elf_id:
            context.attacker_element_types = self._load_elf_element_types(context.attacker_elf_id)
        if not context.defender_element_types and context.defender_elf_id:
            context.defender_element_types = self._load_elf_element_types(context.defender_elf_id)

        details["element_types"] = {
            "skill": context.skill_element_type,
            "attacker": context.attacker_element_types,
            "defender": context.defender_element_types,
        }

    def _resolve_response_multiplier(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """解析应对成功倍率。

        应对是否成功是规则分支判断结果，不属于伤害公式本身。若调用方明确给了
        ``response_multiplier``，则尊重手动值；否则可用 ``response_success`` 与
        ``response_success_multiplier`` 解析。若存在应对规则但成功与否未知，则标记 unknown，
        让实时估计不进行误判。
        """
        if "response_multiplier" in payload:
            details["response_multiplier"] = {
                "source": "manual_payload",
                "value": str(context.response_multiplier),
            }
            return

        response_success_multiplier = payload.get("response_success_multiplier")
        if response_success_multiplier is None:
            response_success_multiplier = payload.get("response_rule_multiplier")

        if response_success_multiplier is None:
            return

        if "response_success" not in payload:
            context.unknown_factors.append("response_success_unknown")
            details["response_multiplier"] = {
                "source": "rule_branch_unknown",
                "possible_multiplier": str(response_success_multiplier),
            }
            return

        if self._payload_bool(payload, "response_success", False):
            context.response_multiplier = response_success_multiplier
        else:
            context.response_multiplier = Decimal("1")
        details["response_multiplier"] = {
            "source": "response_success_flag",
            "response_success": self._payload_bool(payload, "response_success", False),
            "value": str(context.response_multiplier),
        }

    def _resolve_stab_multiplier(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """计算本系加成。已手动传入时不覆盖。"""
        if "stab_multiplier" in payload:
            details["stab_multiplier"] = {
                "source": "manual_payload",
                "value": str(context.stab_multiplier),
            }
            return
        if not context.skill_element_type or not context.attacker_element_types:
            return

        context.stab_multiplier = (
            self.DEFAULT_STAB_MULTIPLIER
            if context.skill_element_type in context.attacker_element_types
            else Decimal("1")
        )
        details["stab_multiplier"] = {
            "source": "element_match",
            "value": str(context.stab_multiplier),
        }

    def _resolve_type_multiplier(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """计算属性克制倍率。已手动传入时不覆盖。"""
        if "type_multiplier" in payload:
            details["type_multiplier"] = {
                "source": "manual_payload",
                "value": str(context.type_multiplier),
            }
            return
        attack_element_type = self._damage_element_type(context)
        if not attack_element_type or not context.defender_element_types:
            return

        single_multipliers = [
            self._single_type_multiplier(attack_element_type, defender_type)
            for defender_type in context.defender_element_types[:2]
        ]
        context.type_multiplier = self._combine_type_multipliers(single_multipliers)
        details["type_multiplier"] = {
            "source": "type_effectiveness_rule",
            "attack_element_type": attack_element_type,
            "single_multipliers": [str(item) for item in single_multipliers],
            "value": str(context.type_multiplier),
        }

    def _resolve_damage_reductions(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
        details: dict[str, Any],
    ) -> None:
        """解析结构化减伤来源为公式可消费的 reduction 列表。"""
        if "damage_reductions" in payload:
            details["damage_reductions"] = {
                "source": "manual_payload",
                "value": [str(item) for item in context.damage_reductions],
            }
            return

        sources = payload.get("damage_reduction_sources") or []
        if not isinstance(sources, list) or not sources:
            return

        reductions: list[Decimal] = []
        normalized_sources: list[dict[str, Any]] = []
        for index, item in enumerate(sources):
            if not isinstance(item, dict):
                context.unknown_factors.append(f"damage_reduction_source_invalid:{index}")
                continue
            active = item.get("active", True)
            if active is None:
                context.unknown_factors.append(f"damage_reduction_active_unknown:{index}")
                continue
            if not bool(active):
                continue

            reduction = item.get("reduction")
            if reduction is None and item.get("multiplier") is not None:
                reduction = Decimal("1") - self._to_decimal(item["multiplier"])
            if reduction is None:
                context.unknown_factors.append(f"damage_reduction_value_missing:{index}")
                continue
            decimal_reduction = self._to_decimal(reduction)
            reductions.append(decimal_reduction)
            normalized_sources.append(
                {
                    "source_id": item.get("source_id"),
                    "reduction": str(decimal_reduction),
                }
            )

        context.damage_reductions = reductions
        details["damage_reductions"] = {
            "source": "damage_reduction_sources",
            "items": normalized_sources,
        }

    def _single_type_multiplier(self, attack_type: str, defense_type: str) -> Decimal:
        """读取单属性克制倍率；缺失规则按数学文档视为 1。"""
        if self.db is None:
            return Decimal("1")
        stmt = select(TypeEffectivenessRule.multiplier).where(
            TypeEffectivenessRule.attack_element_type == attack_type,
            TypeEffectivenessRule.defense_element_type == defense_type,
        )
        value = self.db.scalar(stmt)
        if value is None:
            return Decimal("1")
        return self._to_decimal(value)

    def _load_elf_element_types(self, elf_id: str) -> list[str]:
        """从精灵定义读取系别。"""
        if self.db is None:
            return []
        elf = self.db.get(ElfDefinition, elf_id)
        if elf is None or elf.deleted_at is not None:
            return []
        return self._normalize_element_types(loads_json(elf.element_types_json, []))

    @staticmethod
    def _damage_element_type(context: DamageFormulaContext) -> str | None:
        """返回本次伤害实际用于属性克制的攻击属性。"""
        if context.formula_type == "starfall":
            return context.starfall_element_type
        return context.skill_element_type

    @classmethod
    def _combine_type_multipliers(cls, values: list[Decimal]) -> Decimal:
        """按项目数学建模文档合并单双属性克制倍率。"""
        if not values:
            return Decimal("1")
        if len(values) == 1:
            return values[0]

        first, second = values[0], values[1]
        strong = Decimal("2")
        weak = Decimal("0.5")
        neutral = Decimal("1")
        if first == strong and second == strong:
            return Decimal("3")
        if first == weak and second == weak:
            return Decimal("0.3333333333333333333333333333")
        if {first, second} == {strong, weak}:
            return neutral
        if {first, second} == {strong, neutral}:
            return strong
        if {first, second} == {weak, neutral}:
            return weak
        return neutral

    @staticmethod
    def _normalize_element_types(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if item is not None and str(item)]
        return []

    @staticmethod
    def _to_decimal(value: Decimal | int | float | str) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _payload_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
        value = payload.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)
