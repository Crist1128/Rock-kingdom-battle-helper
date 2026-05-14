"""
状态效果管理端点模块。

提供状态效果定义的查询接口，包括：
- 状态效果列表查询（支持分类筛选和搜索）
- 单个状态效果详情查询
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.static import EffectDefinition
from app.schemas.static import EffectDefinitionOut

# 创建路由实例
router = APIRouter()


@router.get("", response_model=list[EffectDefinitionOut])
def list_effects(
    category: str | None = Query(default=None, description="按 category 筛选"),
    q: str | None = Query(default=None, description="按 effect_name 模糊搜索"),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> list[EffectDefinition]:
    """
    获取状态效果列表。

    支持按分类筛选和按名称搜索，返回状态效果定义列表。

    Args:
        category: 分类筛选，匹配 category 字段
        q: 搜索关键词，匹配 effect_name 字段
        limit: 返回数量限制，默认 50，最大 500
        offset: 分页偏移量，默认 0
        db: 数据库会话，由依赖注入提供

    Returns:
        list[EffectDefinition]: 状态效果定义列表，先按显示优先级、再按名称排序

    Example:
        GET /api/v1/effects?category=mark&q=星&limit=10
    """
    # 构建基础查询，排除已软删除的记录
    stmt = select(EffectDefinition).where(EffectDefinition.deleted_at.is_(None))

    # 如果指定了分类，添加筛选条件
    if category:
        stmt = stmt.where(EffectDefinition.category == category)

    # 如果有搜索关键词，添加模糊匹配条件
    if q:
        stmt = stmt.where(EffectDefinition.effect_name.contains(q))

    # 先按显示优先级排序，再按名称排序，最后应用分页
    stmt = stmt.order_by(EffectDefinition.display_priority, EffectDefinition.effect_name).limit(limit).offset(offset)

    return list(db.scalars(stmt).all())


@router.get("/{effect_id}", response_model=EffectDefinitionOut)
def get_effect(effect_id: str, db: Session = Depends(get_db)) -> EffectDefinition:
    """
    获取单个状态效果详情。

    根据状态效果 ID 获取完整的状态效果定义信息。

    Args:
        effect_id: 状态效果唯一标识符
        db: 数据库会话，由依赖注入提供

    Returns:
        EffectDefinition: 状态效果定义详情

    Raises:
        HTTPException: 404 - 状态效果不存在或已删除

    Example:
        GET /api/v1/effects/effect_001
    """
    # 查询状态效果，使用 db.get 通过主键快速查找
    effect = db.get(EffectDefinition, effect_id)

    # 检查状态效果是否存在且未被软删除
    if effect is None or effect.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Effect not found")

    return effect
