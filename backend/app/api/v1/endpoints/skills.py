"""
技能管理端点模块。

提供技能定义的查询接口，包括：
- 技能列表查询（支持搜索和分页）
- 单个技能详情查询
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.endpoints.data_updates import verify_admin_token
from app.db.session import get_db
from app.models.static import SkillDefinition
from app.schemas.static import (
    SkillDefinitionOut,
    SkillRuleCapabilityAuditOut,
    SkillRuleManualUpdate,
    SkillRuleReviewOut,
)
from app.services.skill_rule_capability_service import build_skill_rule_capability_audit
from app.services.skill_rule_review_service import (
    list_skill_rule_review_items,
    update_skill_rule_review,
)

# 创建路由实例
router = APIRouter()


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
    try:
        return list_skill_rule_review_items(
            db,
            q=q,
            review_status=review_status,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"invalid review_status: {review_status}",
        ) from exc


@router.get("/capability-audit", response_model=SkillRuleCapabilityAuditOut)
def get_skill_rule_capability_audit(db: Session = Depends(get_db)) -> SkillRuleCapabilityAuditOut:
    """审计当前技能规则 JSON 中已落地和仍保留的机制能力。"""
    return build_skill_rule_capability_audit(db)


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
    try:
        return update_skill_rule_review(db, skill_id=skill_id, payload=payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid review_status: {payload.review_status}",
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Skill not found") from exc
