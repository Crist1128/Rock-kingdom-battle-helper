"""rocom 技能清洗中的防御减伤规则测试。"""

import json

from app.data_pipeline.rocom.cleaner import build_skill_catalog


def test_build_skill_catalog_parses_defense_damage_reduction() -> None:
    """防御技能的稳定减伤描述应写入 damage_rule_json。"""
    catalog = build_skill_catalog(
        [
            {
                "技能名": "防御",
                "属性": "普通",
                "类型": "防御",
                "威力": "0",
                "耗能": "1",
                "效果描述": "减伤70%，应对攻击。",
            }
        ],
        [],
    )

    skill = next(iter(catalog.values()))
    damage_rule = json.loads(skill["damage_rule_json"])
    tags = json.loads(skill["tags_json"])

    assert skill["skill_category"] == "status"
    assert skill["base_power"] is None
    assert damage_rule["damage_type"] == "defense_modifier"
    assert damage_rule["damage_reduction"] == 0.7
    assert damage_rule["response_rule"]["condition"] == "response_attack_success"
    assert "defense_reduction" in tags
