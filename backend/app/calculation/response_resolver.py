"""应对结果解析器。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.calculation.formula_context import DamageFormulaContext


class ResponseResolver:
    """把应对成功分支解析为公式上下文中的应对倍率。"""

    def resolve_response_modifiers(
        self,
        context: DamageFormulaContext,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """解析应对倍率；成功与否未知时只记录 unknown，不强行套倍率。"""
        if "response_multiplier" in payload:
            return {
                "response_multiplier": {
                    "source": "manual_payload",
                    "value": str(context.response_multiplier),
                }
            }

        response_rule = self._dict_or_empty(
            payload.get("response_rule") or payload.get("skill_response_rule")
        )
        multiplier = self._first_present(
            payload,
            response_rule,
            (
                "response_success_multiplier",
                "response_rule_multiplier",
                "success_multiplier",
                "response_multiplier",
                "power_multiplier",
            ),
        )
        if multiplier is None:
            return {}

        success_key, success_value = self._response_success(payload, response_rule)
        if success_key is None:
            context.unknown_factors.append("response_success_unknown")
            return {
                "response_multiplier": {
                    "source": "rule_branch_unknown",
                    "candidate_multiplier": str(multiplier),
                    "response_target": response_rule.get("target"),
                }
            }

        if success_value:
            context.response_multiplier = multiplier
        else:
            context.response_multiplier = Decimal("1")
        return {
            "response_multiplier": {
                "source": success_key,
                "response_success": success_value,
                "value": str(context.response_multiplier),
            }
        }

    def _response_success(
        self,
        payload: dict[str, Any],
        response_rule: dict[str, Any],
    ) -> tuple[str | None, bool]:
        if "response_success" in payload:
            return "response_success", self._payload_bool(payload["response_success"])

        condition = payload.get("response_condition") or response_rule.get("condition")
        target = response_rule.get("target") or response_rule.get("response_target")
        if condition is None and target in {"attack", "defense", "status"}:
            condition = f"response_{target}_success"
        if isinstance(condition, str) and condition in payload:
            return condition, self._payload_bool(payload[condition])
        return None, False

    @staticmethod
    def _dict_or_empty(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _first_present(
        payload: dict[str, Any],
        rule: dict[str, Any],
        keys: tuple[str, ...],
    ) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
            if key in rule and rule[key] is not None:
                return rule[key]
        return None

    @staticmethod
    def _payload_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)
