"""星陨伤害观测软评分测试。"""

from app.inference.observation_matcher import ObservationEventInput, ObservationMatcher
from app.inference.observation_types import ObservationType
from app.models.candidate import BuildCandidate
from app.utils.json import dumps_json


def test_damage_observation_can_match_starfall_formula() -> None:
    """DAMAGE_VALUE 观测可通过 payload 指定星陨公式并进入软评分。"""
    candidate = BuildCandidate(
        candidate_id="candidate_1",
        battle_id="battle_1",
        side="enemy",
        elf_id="enemy_elf",
        nature_id="neutral",
        individual_talent_distribution_json=dumps_json({}),
        final_hp=300,
        final_physical_attack=100,
        final_physical_defense=100,
        final_magic_attack=100,
        final_magic_defense=150,
        final_speed=100,
        possible_skill_ids_json=None,
        confirmed_skill_ids_json=None,
        skill_weights_json=None,
        match_score=0,
        confidence=0,
        is_excluded=False,
        excluded_reason=None,
        evidence_ids_json=None,
        matched_event_ids_json=None,
        mismatched_event_ids_json=None,
    )
    observation = ObservationEventInput(
        battle_id="battle_1",
        enemy_elf_id="enemy_elf",
        event_id="damage_starfall_1",
        observation_type=ObservationType.DAMAGE_VALUE,
        observed_value=1140,
        payload={
            "formula_type": "starfall",
            "effect_id": "effect_starfall_mark",
            "effect_layers": 10,
            "trigger_skill_element_type": "火",
            "trigger_skill_category": "physical",
            "type_multiplier": 2,
            "attacker_panel_stats": {
                "hp": 300,
                "physical_attack": 200,
                "physical_defense": 100,
                "magic_attack": 120,
                "magic_defense": 100,
                "speed": 100,
            },
        },
    )

    result = ObservationMatcher().match_candidate(observation=observation, candidate=candidate)

    assert result.matched is True
    assert result.reason == "damage_value_matched"
    assert result.predicted_value == 1140
    assert result.evidence["starfall_power"] == 316
    assert result.evidence["starfall_element_type"] == "幻"
