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


def test_clean_from_raw_sprites_uses_skill_detail_power_as_authoritative() -> None:
    """技能图鉴详情应覆盖精灵页技能，数字威力保留为 int。"""
    from app.data_pipeline.rocom.cleaner import clean_from_raw_sprites

    dataset = clean_from_raw_sprites(
        [
            {
                "no": 1,
                "name": "迪莫",
                "form": None,
                "url": "https://example.test/elf",
                "has_shiny": False,
                "attributes": ["光"],
                "stats": {
                    "hp": 120,
                    "atk": 80,
                    "sp_atk": 80,
                    "def": 105,
                    "sp_def": 105,
                    "spd": 92,
                    "total": 582,
                },
                "ability": {"name": "最好的伙伴", "description": "测试"},
                "type_matchup": {},
                "evolution_chain": [],
                "skills": [
                    {
                        "name": "疾风涡轮",
                        "attribute": "翼",
                        "category": "物攻",
                        "power": 90,
                        "cost": 1,
                        "level": 1,
                        "description": "旧描述。",
                    }
                ],
            }
        ],
        raw_skill_rows=[
            {
                "name": "疾风涡轮",
                "attribute": "翼",
                "category": "攻击",
                "power": 100,
                "cost": 0,
                "description": "造成物伤，无法主动使用，在使用3次翼系技能后会自动使用此技能。",
                "parse_status": "parsed",
                "url": "https://example.test/skill",
            }
        ],
        image_url_rows=[],
    )

    skill = next(item for item in dataset.skills if item["skill_name"] == "疾风涡轮")
    tags = json.loads(skill["tags_json"])
    effect_operations = json.loads(skill["effect_operations_json"])

    assert skill["skill_category"] == "physical"
    assert skill["base_power"] == 100
    assert skill["base_energy_cost"] == 0
    assert "cannot_manual_use" in tags
    assert effect_operations[0]["status"] == "parsed_auto_trigger_rule"


def test_clean_from_raw_sprites_uses_sprite_image_as_avatar() -> None:
    """raw 精灵详情中的 sprite_image 应作为 avatar 写入 cleaned 精灵数据。"""
    from app.data_pipeline.rocom.cleaner import clean_from_raw_sprites

    avatar_url = "https://patchwiki.biligame.com/images/rocom/thumb/8/84/main.png/960px-main.png"
    dataset = clean_from_raw_sprites(
        [
            {
                "no": 7,
                "name": "火神",
                "form": None,
                "url": "https://wiki.biligame.com/rocom/火神",
                "sprite_image": avatar_url,
                "has_shiny": False,
                "attributes": ["火"],
                "stats": {
                    "hp": 114,
                    "atk": 150,
                    "sp_atk": 53,
                    "def": 80,
                    "sp_def": 61,
                    "spd": 111,
                    "total": 569,
                },
                "ability": {"name": "助燃", "description": "测试"},
                "type_matchup": {},
                "evolution_chain": [],
                "skills": [],
            }
        ],
        image_url_rows=[],
    )

    assert dataset.elves[0]["avatar"] == avatar_url


def test_clean_from_raw_sprites_keeps_status_skill_power_none() -> None:
    """无威力状态技不应伪装为 0 威力伤害技能。"""
    from app.data_pipeline.rocom.cleaner import clean_from_raw_sprites

    dataset = clean_from_raw_sprites(
        [],
        raw_skill_rows=[
            {
                "name": "求雨",
                "attribute": "水",
                "category": "状态",
                "power": None,
                "cost": 8,
                "description": "将天气变为雨天，本技能能耗降低效果收益翻倍。",
                "parse_status": "parsed",
            }
        ],
        image_url_rows=[],
    )

    skill = next(item for item in dataset.skills if item["skill_name"] == "求雨")
    operations = json.loads(skill["effect_operations_json"])

    assert skill["base_power"] is None
    assert skill["base_energy_cost"] == 8
    assert operations[0]["operation"] == "change_weather"
    assert operations[0]["effect_id"] == "weather_rain"


def test_cleaner_parses_basic_weather_and_strength_operations() -> None:
    """基础天气和力量增效应直接清洗为结构化技能操作。"""
    from app.data_pipeline.rocom.cleaner import clean_from_raw_sprites

    dataset = clean_from_raw_sprites(
        [],
        raw_skill_rows=[
            {
                "name": "落雨",
                "attribute": "水",
                "category": "状态",
                "power": None,
                "cost": 5,
                "description": "将天气改为雨天，持续8回合。",
                "parse_status": "parsed",
            },
            {
                "name": "冬至",
                "attribute": "冰",
                "category": "状态",
                "power": None,
                "cost": 7,
                "description": "将天气改为暴风雪，持续8回合。",
                "parse_status": "parsed",
            },
            {
                "name": "力量增效",
                "attribute": "普通",
                "category": "状态",
                "power": None,
                "cost": 1,
                "description": "自己获得物攻+100%。",
                "parse_status": "parsed",
            },
        ],
        image_url_rows=[],
    )

    skills = {item["skill_name"]: item for item in dataset.skills}
    rain_ops = json.loads(skills["落雨"]["effect_operations_json"])
    blizzard_ops = json.loads(skills["冬至"]["effect_operations_json"])
    strength_ops = json.loads(skills["力量增效"]["effect_operations_json"])

    assert rain_ops[0]["effect_id"] == "weather_rain"
    assert rain_ops[0]["remaining_turns"] == 8
    assert blizzard_ops[0]["effect_id"] == "weather_blizzard"
    assert blizzard_ops[0]["remaining_turns"] == 8
    assert strength_ops[0]["operation"] == "apply_effect"
    assert strength_ops[0]["effect_id"] == "effect_physical_attack_up_layered"
    assert strength_ops[0]["layers"] == 10


def test_clean_from_raw_sprites_keeps_dex_card_metadata_in_forms_json() -> None:
    """Dex-card metadata should stay in forms_json without requiring new DB columns."""
    from app.data_pipeline.rocom.cleaner import clean_from_raw_sprites

    dataset = clean_from_raw_sprites(
        [
            {
                "no": 7,
                "name": "火花",
                "form": None,
                "url": "https://wiki.biligame.com/rocom/%E7%81%AB%E8%8A%B1",
                "has_shiny": False,
                "attributes": ["火"],
                "stats": {
                    "hp": 100,
                    "atk": 90,
                    "sp_atk": 80,
                    "def": 70,
                    "sp_def": 60,
                    "spd": 50,
                    "total": 450,
                },
                "ability": {"name": "test", "description": "test"},
                "type_matchup": {},
                "evolution_chain": [],
                "skills": [],
                "dex_stage": "初始",
                "dex_element": "火",
                "dex_form_type": "主形态",
                "dex_is_main_form": True,
                "dex_evolution_role": "一阶",
            }
        ],
        image_url_rows=[],
    )

    forms = json.loads(dataset.elves[0]["forms_json"])
    assert forms["dex_metadata"] == {
        "stage": "初始",
        "element": "火",
        "form_type": "主形态",
        "is_main_form": True,
        "evolution_role": "一阶",
    }
