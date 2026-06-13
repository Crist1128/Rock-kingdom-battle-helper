"""
技能管理端点模块。

提供技能定义的查询接口，包括：
- 技能列表查询（支持搜索和分页）
- 单个技能详情查询
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.data_updates import verify_admin_token
from app.db.session import get_db
from app.models.static import SkillDefinition
from app.schemas.static import (
    SkillDefinitionOut,
    SkillRuleCapabilityAuditOut,
    SkillRuleCapabilityItem,
    SkillRuleManualUpdate,
    SkillRuleReviewOut,
)
from app.services.effect_operation_executor import EffectOperationExecutor
from app.utils.json import dumps_json, loads_json

# 创建路由实例
router = APIRouter()

REVIEW_STATUS_VALUES = {"unreviewed", "structured", "partial", "needs_review", "ambiguous"}
MINIMAL_EXECUTABLE_HOOKS = {
    "charge_before_attack",
    "charge_turn_mechanic",
    "charge_then_apply_effects",
    "next_skill_charge_requirement_override",
}
EXECUTABLE_WHEN_MARKED_HOOKS = {
    "persistent_skill_cost_modifier",
    "persistent_skill_power_modifier",
}


@router.get("", response_model=list[SkillDefinitionOut])
def list_skills(
    q: str | None = Query(default=None, description="按 skill_name 模糊搜索"),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> list[SkillDefinition]:
    """
    获取技能列表。

    支持按名称模糊搜索，返回技能定义列表。

    Args:
        q: 搜索关键词，匹配 skill_name 字段
        limit: 返回数量限制，默认 50，最大 500
        offset: 分页偏移量，默认 0
        db: 数据库会话，由依赖注入提供

    Returns:
        list[SkillDefinition]: 技能定义列表，按名称排序

    Example:
        GET /api/v1/skills?q=火&limit=10
    """
    # 构建基础查询，排除已软删除的记录
    stmt = select(SkillDefinition).where(SkillDefinition.deleted_at.is_(None))

    # 如果有搜索关键词，添加模糊匹配条件
    if q:
        stmt = stmt.where(SkillDefinition.skill_name.contains(q))

    # 按名称排序并应用分页
    stmt = stmt.order_by(SkillDefinition.skill_name).limit(limit).offset(offset)

    return list(db.scalars(stmt).all())


@router.get("/review", response_model=list[SkillRuleReviewOut])
def list_skill_rule_reviews(
    q: str | None = Query(default=None, description="按 skill_name 模糊搜索"),
    review_status: str | None = Query(
        default=None,
        description="按审阅状态筛选：unreviewed/structured/partial/needs_review/ambiguous",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> list[SkillRuleReviewOut]:
    """列出技能规则审阅队列，供人工逐条补齐技能效果。"""
    if review_status is not None and review_status not in REVIEW_STATUS_VALUES:
        raise HTTPException(status_code=400, detail=f"invalid review_status: {review_status}")

    stmt = select(SkillDefinition).where(SkillDefinition.deleted_at.is_(None))
    if q:
        stmt = stmt.where(SkillDefinition.skill_name.contains(q))
    rows = list(db.scalars(stmt.order_by(SkillDefinition.skill_name)).all())
    items = [_skill_review_out(row) for row in rows]
    if review_status is not None:
        items = [item for item in items if item.review_status == review_status]
    return items[offset : offset + limit]


@router.get("/capability-audit", response_model=SkillRuleCapabilityAuditOut)
def get_skill_rule_capability_audit(db: Session = Depends(get_db)) -> SkillRuleCapabilityAuditOut:
    """审计当前技能规则 JSON 中哪些机制已有执行链，哪些仍只是接口。"""
    skills = list(
        db.scalars(
            select(SkillDefinition)
            .where(SkillDefinition.deleted_at.is_(None))
            .order_by(SkillDefinition.skill_name)
        ).all()
    )
    review_status_counts: dict[str, int] = {}
    executable_operation_counts: dict[str, int] = {}
    unsupported_operation_counts: dict[str, int] = {}
    future_hook_counts: dict[str, int] = {}
    supported_future_hook_counts: dict[str, int] = {}
    reserved_future_hook_counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}

    supported_operations = EffectOperationExecutor.SUPPORTED_OPERATIONS
    for skill in skills:
        review_out = _skill_review_out(skill)
        _count(review_status_counts, review_out.review_status)

        for operation in _effect_operations(skill):
            op_type = _operation_type(operation)
            if op_type is None:
                continue
            _append_example(examples, f"operation:{op_type}", skill.skill_name)
            if op_type in supported_operations:
                _count(executable_operation_counts, op_type)
            else:
                _count(unsupported_operation_counts, op_type)

        for hook in _future_hooks(skill):
            hook_type = str(hook.get("hook_type") or "unknown")
            _count(future_hook_counts, hook_type)
            _append_example(examples, f"hook:{hook_type}", skill.skill_name)
            if _future_hook_has_execution_path(hook):
                _count(supported_future_hook_counts, hook_type)
            else:
                _count(reserved_future_hook_counts, hook_type)

    return SkillRuleCapabilityAuditOut(
        total_skills=len(skills),
        review_status_counts=review_status_counts,
        executable_operation_counts=executable_operation_counts,
        unsupported_operation_counts=unsupported_operation_counts,
        future_hook_counts=future_hook_counts,
        supported_future_hook_counts=supported_future_hook_counts,
        reserved_future_hook_counts=reserved_future_hook_counts,
        implemented_capabilities=_implemented_capabilities(examples),
        pending_capabilities=_pending_capabilities(
            reserved_future_hook_counts,
            unsupported_operation_counts,
            examples,
        ),
        risk_notes=[
            "审计只说明代码是否有执行链；复杂伤害公式未验证前仍不能用于硬排除候选。",
            "需要条件旗标的机制不会自动假定成功，例如风起先手、应对成功、迸发窗口。",
            "历史解释必须以事件快照为准；当前状态只用于工作台即时预览。",
        ],
    )


@router.get("/{skill_id}", response_model=SkillDefinitionOut)
def get_skill(skill_id: str, db: Session = Depends(get_db)) -> SkillDefinition:
    """
    获取单个技能详情。

    根据技能 ID 获取完整的技能定义信息。

    Args:
        skill_id: 技能唯一标识符
        db: 数据库会话，由依赖注入提供

    Returns:
        SkillDefinition: 技能定义详情

    Raises:
        HTTPException: 404 - 技能不存在或已删除

    Example:
        GET /api/v1/skills/skill_001
    """
    # 查询技能，使用 db.get 通过主键快速查找
    skill = db.get(SkillDefinition, skill_id)

    # 检查技能是否存在且未被软删除
    if skill is None or skill.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Skill not found")

    return skill


@router.put(
    "/{skill_id}/rules",
    response_model=SkillRuleReviewOut,
    summary="手动维护技能规则 JSON",
)
def update_skill_rules(
    skill_id: str,
    payload: SkillRuleManualUpdate,
    _: None = Depends(verify_admin_token),
    db: Session = Depends(get_db),
) -> SkillRuleReviewOut:
    """手动写入明确的技能规则，或仅标记为待确认/模糊。

    不确定的技能不要写入可执行规则字段；只保存 review_status 和 review_notes。
    """
    if payload.review_status not in REVIEW_STATUS_VALUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid review_status: {payload.review_status}",
        )
    skill = db.get(SkillDefinition, skill_id)
    if skill is None or skill.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Skill not found")

    fields = payload.model_fields_set
    if "damage_rule" in fields:
        skill.damage_rule_json = _json_or_none(payload.damage_rule)
    if "hit_rule" in fields:
        skill.hit_rule_json = _json_or_none(payload.hit_rule)
    if "effect_operations" in fields:
        skill.effect_operations_json = _json_or_none(payload.effect_operations)

    _write_manual_review(skill, payload.review_status, payload.review_notes)
    db.commit()
    db.refresh(skill)
    return _skill_review_out(skill)


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return dumps_json(value)


def _write_manual_review(
    skill: SkillDefinition,
    review_status: str,
    review_notes: str | None,
) -> None:
    rule = loads_json(skill.damage_rule_json, None)
    if not isinstance(rule, dict):
        rule = {}
    rule["manual_review"] = {
        "status": review_status,
        "notes": review_notes,
        "source": "manual_skill_rule_editor",
    }
    skill.damage_rule_json = dumps_json(rule)


def _skill_review_out(skill: SkillDefinition) -> SkillRuleReviewOut:
    damage_rule = loads_json(skill.damage_rule_json, None)
    hit_rule = loads_json(skill.hit_rule_json, None)
    effect_operations = loads_json(skill.effect_operations_json, None)
    review = damage_rule.get("manual_review", {}) if isinstance(damage_rule, dict) else {}
    has_damage_rule = _has_meaningful_damage_rule(damage_rule)
    has_hit_rule = isinstance(hit_rule, dict) and bool(hit_rule)
    has_effect_operations = isinstance(effect_operations, list) and bool(effect_operations)
    status_value = review.get("status") if isinstance(review, dict) else None
    review_status = (
        str(status_value)
        if isinstance(status_value, str) and status_value in REVIEW_STATUS_VALUES
        else "structured"
        if has_damage_rule or has_effect_operations
        else "partial"
        if has_hit_rule
        else "unreviewed"
    )
    review_notes = (
        str(review.get("notes"))
        if isinstance(review, dict) and review.get("notes") is not None
        else None
    )
    data = SkillDefinitionOut.model_validate(skill).model_dump()
    return SkillRuleReviewOut(
        **data,
        review_status=review_status,
        review_notes=review_notes,
        has_damage_rule=has_damage_rule,
        has_hit_rule=has_hit_rule,
        has_effect_operations=has_effect_operations,
        rule_source=(
            "manual"
            if isinstance(review, dict) and review
            else "structured_json"
            if has_damage_rule or has_effect_operations
            else "hit_rule_only"
            if has_hit_rule
            else "none"
        ),
    )


def _has_meaningful_damage_rule(rule: Any) -> bool:
    if not isinstance(rule, dict) or not rule:
        return False
    return any(key != "manual_review" for key in rule)


def _count(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _append_example(examples: dict[str, list[str]], key: str, value: str) -> None:
    values = examples.setdefault(key, [])
    if value not in values and len(values) < 5:
        values.append(value)


def _effect_operations(skill: SkillDefinition) -> list[dict[str, Any]]:
    operations = loads_json(skill.effect_operations_json, [])
    if not isinstance(operations, list):
        return []
    return [item for item in operations if isinstance(item, dict)]


def _operation_type(operation: dict[str, Any]) -> str | None:
    raw = operation.get("operation") or operation.get("op_type") or operation.get("type")
    return str(raw) if raw else None


def _future_hooks(skill: SkillDefinition) -> list[dict[str, Any]]:
    rule = loads_json(skill.damage_rule_json, {})
    if not isinstance(rule, dict):
        return []
    review = rule.get("manual_review")
    hooks = review.get("future_hooks") if isinstance(review, dict) else None
    if not isinstance(hooks, list):
        hooks = rule.get("future_hooks")
    if not isinstance(hooks, list):
        return []
    return [item for item in hooks if isinstance(item, dict)]


def _future_hook_has_execution_path(hook: dict[str, Any]) -> bool:
    hook_type = str(hook.get("hook_type") or "")
    if hook_type in MINIMAL_EXECUTABLE_HOOKS:
        return True
    return hook_type in EXECUTABLE_WHEN_MARKED_HOOKS and hook.get("status") == "executable"


def _implemented_capabilities(examples: dict[str, list[str]]) -> list[SkillRuleCapabilityItem]:
    return [
        SkillRuleCapabilityItem(
            key="effect_operations_core",
            label="结构化状态/天气/资源/清除/叠层操作",
            implemented=True,
            tested=True,
            notes="由 EffectOperationExecutor 执行；不支持的 op_type 会跳过并回显原因。",
        ),
        SkillRuleCapabilityItem(
            key="damage_response_modifier",
            label="防御/应对减伤与条件旗标",
            implemented=True,
            tested=True,
            notes="支持 defense_skill_id、response_*_success 和 condition_flags。",
        ),
        SkillRuleCapabilityItem(
            key="skill_slot_runtime_modifier",
            label="技能槽运行时威力/费用修正",
            implemented=True,
            tested=True,
            notes="支持永久费用/威力修正、状态来源费用/威力/连击修正。",
        ),
        SkillRuleCapabilityItem(
            key="confirmed_marks",
            label="湿润/光合/攻击/降灵/蓄势/减速/龙噬等确认印记",
            implemented=True,
            tested=True,
            notes="光合/降灵资源结算、龙噬触发和条件技能修正已有聚焦测试。",
        ),
        SkillRuleCapabilityItem(
            key="cute_mark_listener",
            label="萌化印记对新获得属性增益 +1 层",
            implemented=True,
            tested=True,
            notes="仅正向 stat_modifier；不作用于印记、天气、技能槽增益。",
        ),
        SkillRuleCapabilityItem(
            key="burst_window_record",
            label="初始首发/返场首回合迸发窗口与效果记录",
            implemented=True,
            tested=True,
            notes="只在存在 requires_burst 的具体附加效果时写 effect_trigger。",
        ),
        SkillRuleCapabilityItem(
            key="charge_minimal_state_machine",
            label="蓄力最小状态机",
            implemented=True,
            tested=True,
            notes="第一次选择扣能并等待；再次选择同技能释放；切换清除。",
        ),
        SkillRuleCapabilityItem(
            key="return_to_field_marker",
            label="返场后端语义",
            implemented=True,
            tested=True,
            notes="switch_elf 支持 from=to 并触发切换清除/入场结算；工作台队伍卡可手动返场。",
        ),
    ]


def _pending_capabilities(
    reserved_hook_counts: dict[str, int],
    unsupported_operation_counts: dict[str, int],
    examples: dict[str, list[str]],
) -> list[SkillRuleCapabilityItem]:
    pending = [
        SkillRuleCapabilityItem(
            key="cute_regression_panel",
            label="萌化导致种族值/面板回退",
            implemented=False,
            tested=False,
            notes="当前只记录层数；需要精灵进化链和面板替换模型。",
        ),
        SkillRuleCapabilityItem(
            key="burst_history_inheritance",
            label="迸发历史继承/复用",
            implemented=False,
            tested=False,
            count=reserved_hook_counts.get("burst_history_listener", 0)
            + reserved_hook_counts.get("next_turn_selected_skill_burst_replay", 0),
            examples=(
                examples.get("hook:burst_history_listener", [])
                + examples.get("hook:next_turn_selected_skill_burst_replay", [])
            )[:5],
        ),
        SkillRuleCapabilityItem(
            key="advanced_charge_branches",
            label="蓄力期间受击改威力/蓄力中可用防御技能",
            implemented=False,
            tested=False,
            count=reserved_hook_counts.get("charge_damage_taken_power_formula", 0)
            + reserved_hook_counts.get("usable_while_charging", 0),
            examples=(
                examples.get("hook:charge_damage_taken_power_formula", [])
                + examples.get("hook:usable_while_charging", [])
            )[:5],
        ),
        SkillRuleCapabilityItem(
            key="dynamic_power_formulas",
            label="体重/速度差/防御差/生命比例/能耗等动态威力公式",
            implemented=False,
            tested=False,
            notes="按用户要求体重等公式暂不实现；其它动态公式需逐条确认输入与取整。",
        ),
        SkillRuleCapabilityItem(
            key="slot_transmission_transform_copy",
            label="传动、槽位、变形、复制、技能交换",
            implemented=False,
            tested=False,
            notes="传动暂不考虑；变形/复制按要求只保留接口。",
        ),
        SkillRuleCapabilityItem(
            key="force_switch_interrupt",
            label="脱离强制换人、打断计划落库",
            implemented=False,
            tested=False,
            count=reserved_hook_counts.get("force_switch_out", 0)
            + reserved_hook_counts.get("interrupt_responded_skill", 0)
            + unsupported_operation_counts.get("force_switch_out", 0),
            examples=(
                examples.get("hook:force_switch_out", [])
                + examples.get("hook:interrupt_responded_skill", [])
                + examples.get("operation:force_switch_out", [])
            )[:5],
            notes="打断已有 action_interrupted 事件类型占位；不自动删除事件。",
        ),
        SkillRuleCapabilityItem(
            key="dedication",
            label="奉献相关机制",
            implemented=False,
            tested=False,
            count=reserved_hook_counts.get("dedication_gain", 0)
            + reserved_hook_counts.get("dedication_interaction", 0),
            examples=(
                examples.get("hook:dedication_gain", [])
                + examples.get("hook:dedication_interaction", [])
            )[:5],
            notes="按用户要求暂不实现。",
        ),
    ]
    for op_type, count in sorted(unsupported_operation_counts.items()):
        pending.append(
            SkillRuleCapabilityItem(
                key=f"unsupported_operation:{op_type}",
                label=f"未支持结构化操作：{op_type}",
                implemented=False,
                tested=False,
                count=count,
                examples=examples.get(f"operation:{op_type}", []),
            )
        )
    return pending
