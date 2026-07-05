"""连击规则解析器。

该模块只负责把静态技能 hit_rule_json 与事件 payload 中的手动连击输入合并到
DamageFormulaContext；真正的单段伤害和总伤害仍由 AttackDamageCalculator 计算。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.calculation.formula_context import DamageFormulaContext
from app.models.static import SkillDefinition
from app.utils.json import loads_json


class HitRuleResolver:
    """解析技能固定连击数与本次事件手动连击数。"""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def resolve_hit_rule(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """把连击规则写入公式上下文，并返回可解释细节。"""
        if context.formula_type != "attack":
            return {}

        details: dict[str, Any] = {}
        skill_rule = self._load_skill_hit_rule(context.skill_id)
        manual_hit_count = self._positive_int(payload.get("hit_count"))
        skill_hit_count = self._positive_int(skill_rule.get("hit_count"))

        if payload.get("damage_display_type") is not None:
            context.damage_display_type = str(payload["damage_display_type"])
        elif skill_rule.get("damage_display_type") is not None:
            context.damage_display_type = str(skill_rule["damage_display_type"])

        if manual_hit_count is not None:
            context.hit_count = manual_hit_count
            source = "manual_payload"
        elif skill_hit_count is not None:
            context.hit_count = skill_hit_count
            source = "skill_hit_rule"
        else:
            context.hit_count = max(int(context.hit_count or 1), 1)
            source = "context_default"

        if source != "context_default" or skill_rule:
            details["hit_rule"] = {
                "source": source,
                "hit_count": context.hit_count,
                "damage_display_type": context.damage_display_type,
                "runtime_record_strategy": skill_rule.get("runtime_record_strategy"),
                "skill_hit_count": skill_hit_count,
                "manual_hit_count": manual_hit_count,
            }
        return details

    def _load_skill_hit_rule(self, skill_id: str | None) -> dict[str, Any]:
        if self.db is None or not skill_id:
            return {}
        skill = self.db.get(SkillDefinition, skill_id)
        if skill is None or skill.deleted_at is not None:
            return {}
        rule = loads_json(skill.hit_rule_json, {})
        return rule if isinstance(rule, dict) else {}

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
