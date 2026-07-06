"""技能规则审阅批次导入器测试。"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.data_pipeline.skill_rule_reviews.importer import import_skill_rule_reviews
from app.data_pipeline.static_rule_sync import (
    check_structured_skill_rule_sync,
    sync_structured_skill_rules,
)
from app.db.base import Base
from app.models import battle as _battle_models  # noqa: F401
from app.models import effect as _effect_models  # noqa: F401
from app.models import event as _event_models  # noqa: F401
from app.models import static as _static_models  # noqa: F401
from app.models.static import EffectDefinition, SkillDefinition
from app.utils.json import dumps_json, loads_json


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """创建隔离的内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_import_skill_rule_reviews_preserves_damage_rule_and_writes_review(
    db_session: Session,
) -> None:
    """未传 damage_rule 时应保留原规则，并写入人工审阅状态。"""
    db_session.add(
        _skill(
            "skill_attack",
            damage_rule_json=dumps_json({"damage_type": "normal_formula"}),
            effect_operations_json=dumps_json([{"status": "unparsed"}]),
        )
    )
    db_session.commit()

    summary = import_skill_rule_reviews(
        db_session,
        [
            {
                "skill_id": "skill_attack",
                "skill_name": "测试技能",
                "review_status": "partial",
                "review_notes": "保留基础伤害规则，清空未解析效果。",
                "effect_operations": None,
                "future_hooks": [
                    {
                        "hook_type": "skill_transform",
                        "status": "reserved",
                    }
                ],
                "structure_gaps": ["missing_effect_definition"],
            }
        ],
    )

    assert summary["skills_updated"] == 1
    assert summary["structure_gap_counts"] == {"missing_effect_definition": 1}
    skill = db_session.get(SkillDefinition, "skill_attack")
    assert skill is not None
    damage_rule = loads_json(skill.damage_rule_json, {})
    assert damage_rule["damage_type"] == "normal_formula"
    assert damage_rule["manual_review"]["status"] == "partial"
    assert damage_rule["manual_review"]["future_hooks"][0]["hook_type"] == "skill_transform"
    assert skill.effect_operations_json is None


def test_import_skill_rule_reviews_can_replace_rules(db_session: Session) -> None:
    """明确传入的规则字段应覆盖旧 JSON。"""
    db_session.add(_skill("skill_defense"))
    db_session.commit()

    import_skill_rule_reviews(
        db_session,
        [
            {
                "skill_id": "skill_defense",
                "review_status": "structured",
                "review_notes": "确认减伤。",
                "damage_rule": {
                    "damage_type": "defense_modifier",
                    "damage_reduction": 0.8,
                },
                "hit_rule": None,
                "effect_operations": [
                    {
                        "op_type": "apply_effect",
                        "effect_id": "effect_freeze",
                        "target": "enemy_side",
                        "layers": 2,
                    }
                ],
            }
        ],
    )

    skill = db_session.get(SkillDefinition, "skill_defense")
    assert skill is not None
    damage_rule = loads_json(skill.damage_rule_json, {})
    operations = loads_json(skill.effect_operations_json, [])
    assert damage_rule["damage_reduction"] == 0.8
    assert damage_rule["manual_review"]["status"] == "structured"
    assert skill.hit_rule_json is None
    assert operations[0]["effect_id"] == "effect_freeze"


def test_import_skill_rule_reviews_preserves_nested_future_hooks(
    db_session: Session,
) -> None:
    """damage_rule 内已有的可执行钩子不能被人工审阅元信息覆盖丢失。"""
    db_session.add(_skill("skill_switch_out_hook"))
    db_session.commit()

    import_skill_rule_reviews(
        db_session,
        [
            {
                "skill_id": "skill_switch_out_hook",
                "review_status": "structured",
                "review_notes": "每离场一次，本技能使用次数永久+1。",
                "future_hooks": [],
                "damage_rule": {
                    "damage_type": "magic_attack",
                    "manual_review": {
                        "future_hooks": [
                            {
                                "hook_type": "persistent_skill_use_count_modifier",
                                "trigger": "switch_out",
                                "target": "source_skill",
                                "use_count_delta": 1,
                                "status": "executable",
                            }
                        ]
                    },
                },
            }
        ],
    )

    skill = db_session.get(SkillDefinition, "skill_switch_out_hook")
    assert skill is not None
    rule = loads_json(skill.damage_rule_json, {})
    hooks = rule["manual_review"]["future_hooks"]
    assert hooks[0]["hook_type"] == "persistent_skill_use_count_modifier"
    assert hooks[0]["trigger"] == "switch_out"
    assert hooks[0]["use_count_delta"] == 1


def test_import_skill_rule_reviews_falls_back_to_unique_skill_name(
    db_session: Session,
) -> None:
    """人工规则的 skill_id 失效时，应按唯一技能名兜底匹配。"""
    db_session.add(_skill("new_stable_skill_id", skill_name="力量增效"))
    db_session.commit()

    summary = import_skill_rule_reviews(
        db_session,
        [
            {
                "skill_id": "old_stale_skill_id",
                "skill_name": "力量增效",
                "review_status": "structured",
                "clear_damage_rule": True,
                "effect_operations": [
                    {
                        "op_type": "apply_effect",
                        "effect_id": "effect_physical_attack_up_layered",
                        "target": "actor_side",
                        "layers": 10,
                    }
                ],
            }
        ],
    )

    assert summary["skills_updated"] == 1
    assert summary["skills_missing"] == 0
    assert summary["skill_name_fallbacks"] == [
        {
            "review_skill_id": "old_stale_skill_id",
            "skill_name": "力量增效",
            "matched_skill_id": "new_stable_skill_id",
        }
    ]
    skill = db_session.get(SkillDefinition, "new_stable_skill_id")
    assert skill is not None
    operations = loads_json(skill.effect_operations_json, [])
    assert operations[0]["layers"] == 10


def test_static_rule_sync_checks_and_commits_structured_rules(
    db_session: Session,
    tmp_path,
) -> None:
    """同步检查器只列出 structured 差异，并由 commit 显式写库。"""
    db_session.add(_skill("skill_sync", skill_name="同步测试"))
    db_session.add(_skill("skill_partial", skill_name="未完备测试"))
    db_session.commit()
    reviews_json = tmp_path / "reviews.json"
    reviews_json.write_text(
        dumps_json(
            [
                {
                    "skill_id": "skill_sync",
                    "skill_name": "同步测试",
                    "review_status": "structured",
                    "review_notes": "确认减伤。",
                    "damage_rule": {"damage_type": "defense_modifier", "damage_reduction": 0.5},
                    "hit_rule": {"damage_display_type": "single_damage"},
                    "effect_operations": None,
                },
                {
                    "skill_id": "skill_partial",
                    "skill_name": "未完备测试",
                    "review_status": "partial",
                    "structure_gaps": ["future_rule"],
                    "damage_rule": {"damage_type": "normal_formula"},
                },
            ]
        ),
        encoding="utf-8",
    )

    plan = check_structured_skill_rule_sync(
        db_session,
        reviews_json=reviews_json,
        effect_json_paths=[],
    )
    assert plan["pending_count"] == 1
    assert plan["pending_items"][0]["skill_id"] == "skill_sync"

    dry_run = sync_structured_skill_rules(
        db_session,
        skill_ids=["skill_sync"],
        commit=False,
        reviews_json=reviews_json,
        effect_json_paths=[],
    )
    assert dry_run["applied_count"] == 1
    assert dry_run["transaction"] == "rolled_back_dry_run"
    assert db_session.get(SkillDefinition, "skill_sync").damage_rule_json is None

    committed = sync_structured_skill_rules(
        db_session,
        skill_ids=["skill_sync"],
        commit=True,
        reviews_json=reviews_json,
        effect_json_paths=[],
    )
    assert committed["applied_count"] == 1
    assert committed["transaction"] == "committed"
    skill = db_session.get(SkillDefinition, "skill_sync")
    assert skill is not None
    assert loads_json(skill.damage_rule_json, {})["manual_review"]["status"] == "structured"
    assert loads_json(skill.hit_rule_json, {})["damage_display_type"] == "single_damage"


def test_static_rule_sync_also_applies_effect_definitions(
    db_session: Session,
    tmp_path,
) -> None:
    """同步完备技能规则时，应同事务补齐项目状态定义 seed。"""
    db_session.add(_skill("skill_with_effect_seed"))
    db_session.commit()
    reviews_json = tmp_path / "reviews.json"
    reviews_json.write_text(
        dumps_json(
            [
                {
                    "skill_id": "skill_with_effect_seed",
                    "skill_name": "状态同步技能",
                    "review_status": "structured",
                    "damage_rule": {"damage_type": "normal_formula"},
                }
            ]
        ),
        encoding="utf-8",
    )
    effect_json = tmp_path / "effects.json"
    effect_json.write_text(
        dumps_json(
            [
                {
                    "effect_id": "effect_sync_state",
                    "effect_name": "同步状态",
                    "category": "skill_modifier",
                    "polarity": "positive",
                    "display_group": "skill_modifier",
                    "owner_scope": "skill_slot",
                    "target_scope": "single_skill_slot",
                    "attach_target_type": "skill_slot",
                    "is_visible_icon": True,
                    "is_recognizable_by_icon": False,
                    "default_layers": 1,
                    "stack_rule": "replace",
                    "duration_type": "until_removed",
                    "clear_on_switch": False,
                    "clear_by_abnormal_cleanse": False,
                    "clear_by_stat_clear": False,
                    "clear_by_mark_clear": False,
                    "clear_by_weather_replace": False,
                    "clear_by_skill_specific": False,
                    "can_be_transferred": False,
                    "can_be_converted": False,
                    "can_be_inherited": False,
                    "can_be_stolen": False,
                    "can_be_doubled": False,
                    "skill_modifier_json": {"modifier_type": "power_add", "power_add": 10},
                }
            ]
        ),
        encoding="utf-8",
    )
    fallback_effect_json = tmp_path / "fallback_effects.json"
    fallback_effect_json.write_text(
        dumps_json(
            [
                {
                    "effect_id": "effect_sync_state",
                    "effect_name": "旧版同步状态",
                    "category": "skill_modifier",
                    "polarity": "positive",
                    "display_group": "legacy_modifier",
                    "owner_scope": "skill_slot",
                    "target_scope": "single_skill_slot",
                    "attach_target_type": "skill_slot",
                    "display_priority": 99,
                }
            ]
        ),
        encoding="utf-8",
    )

    plan = check_structured_skill_rule_sync(
        db_session,
        reviews_json=reviews_json,
        effect_json_paths=[effect_json, fallback_effect_json],
    )
    assert plan["pending_skill_count"] == 1
    assert plan["pending_effect_count"] == 1
    assert plan["pending_count"] == 2

    dry_run = sync_structured_skill_rules(
        db_session,
        commit=False,
        reviews_json=reviews_json,
        effect_json_paths=[effect_json, fallback_effect_json],
    )
    assert dry_run["applied_skill_count"] == 1
    assert dry_run["applied_effect_count"] == 1
    assert db_session.get(EffectDefinition, "effect_sync_state") is None

    committed = sync_structured_skill_rules(
        db_session,
        commit=True,
        reviews_json=reviews_json,
        effect_json_paths=[effect_json, fallback_effect_json],
    )
    assert committed["applied_skill_count"] == 1
    assert committed["applied_effect_count"] == 1
    assert committed["pending_skill_count"] == 0
    assert committed["pending_effect_count"] == 0
    assert committed["pending_count"] == 0
    effect = db_session.get(EffectDefinition, "effect_sync_state")
    assert effect is not None
    assert effect.effect_name == "同步状态"
    assert effect.display_group == "skill_modifier"


def test_static_rule_sync_can_filter_by_skill_name(
    db_session: Session,
    tmp_path,
) -> None:
    """同步检查器支持按技能名筛选，避免目标技能被默认列表上限截断。"""
    db_session.add(_skill("skill_a", skill_name="三连破"))
    db_session.add(_skill("skill_b", skill_name="花炮"))
    db_session.commit()
    reviews_json = tmp_path / "reviews.json"
    reviews_json.write_text(
        dumps_json(
            [
                {
                    "skill_id": "skill_a",
                    "skill_name": "三连破",
                    "review_status": "structured",
                    "hit_rule": {"hit_count": 3},
                },
                {
                    "skill_id": "skill_b",
                    "skill_name": "花炮",
                    "review_status": "structured",
                    "hit_rule": {"hit_count": 2},
                },
            ]
        ),
        encoding="utf-8",
    )

    plan = check_structured_skill_rule_sync(
        db_session,
        reviews_json=reviews_json,
        effect_json_paths=[],
        q="花炮",
    )

    assert plan["query"] == "花炮"
    assert plan["pending_count"] == 1
    assert plan["pending_items"][0]["skill_id"] == "skill_b"


def _skill(
    skill_id: str,
    *,
    skill_name: str = "测试技能",
    damage_rule_json: str | None = None,
    effect_operations_json: str | None = None,
) -> SkillDefinition:
    return SkillDefinition(
        skill_id=skill_id,
        skill_name=skill_name,
        element_type="普通",
        skill_category="status",
        base_power=None,
        base_energy_cost=0,
        priority_modifier=0,
        damage_rule_json=damage_rule_json,
        effect_operations_json=effect_operations_json,
    )
