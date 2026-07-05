"""连击规则解析器测试。"""

from app.calculation.formula_context import DamageFormulaContext
from app.calculation.hit_rule_resolver import HitRuleResolver


def test_auto_effect_prefill_is_not_treated_as_manual_payload() -> None:
    """前端已按场上连击状态预填的次数，应保留来源并避免后端重复叠加。"""
    context = DamageFormulaContext(
        battle_id="battle_test",
        attacker_side="self",
        attacker_elf_id="elf_self",
        defender_side="enemy",
        defender_elf_id="elf_enemy",
        skill_id="skill_combo_status",
        formula_type="attack",
    )

    details = HitRuleResolver().resolve_hit_rule(
        context,
        {"hit_count": 4, "combo_count_source": "auto_effect_prefill"},
    )

    assert context.hit_count == 4
    assert details["hit_rule"]["source"] == "auto_effect_prefill"
    assert details["hit_rule"]["effect_prefill_hit_count"] == 4


def test_conditional_hit_rule_supports_hit_count_multiplier() -> None:
    """条件命中时可把基础连击数按倍率修正。"""
    resolver = HitRuleResolver()
    resolver._load_skill_hit_rule = lambda _skill_id: {  # type: ignore[method-assign]
        "hit_count": 2,
        "conditional_hit_rule": {
            "condition": "response_status_success",
            "hit_count_multiplier": 2,
        },
    }
    context = DamageFormulaContext(battle_id="battle_test", skill_id="skill_double_combo")

    details = resolver.resolve_hit_rule(context, {"response_status_success": True})

    assert context.hit_count == 4
    assert details["hit_rule"]["source"] == "conditional_hit_rule"
    assert details["hit_rule"]["conditional_hit_rule"]["status"] == "matched"


def test_conditional_hit_rule_any_response_success_matches_all_response_types() -> None:
    """any_response_success 包含攻击、防御、状态三类应对成功。"""
    resolver = HitRuleResolver()
    resolver._load_skill_hit_rule = lambda _skill_id: {  # type: ignore[method-assign]
        "hit_count": 2,
        "conditional_hit_rule": {
            "condition": "any_response_success",
            "hit_count_bonus": 2,
        },
    }
    context = DamageFormulaContext(battle_id="battle_test", skill_id="skill_any_response_combo")

    resolver.resolve_hit_rule(context, {"response_defense_success": True})

    assert context.hit_count == 4
