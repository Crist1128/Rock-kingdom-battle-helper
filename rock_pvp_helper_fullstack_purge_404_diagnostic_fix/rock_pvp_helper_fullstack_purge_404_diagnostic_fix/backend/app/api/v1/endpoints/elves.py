"""
精灵管理端点模块。

提供精灵定义的查询接口，包括：
- 精灵列表查询（支持搜索和分页）
- 单个精灵详情查询
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.static import ElfDefinition, ElfLearnableSkill, SkillDefinition
from app.schemas.static import ElfDefinitionOut, SkillDefinitionOut

# 创建路由实例
router = APIRouter()


@router.get("", response_model=list[ElfDefinitionOut])
def list_elves(
    q: str | None = Query(default=None, description="按 elf_name 模糊搜索"),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> list[ElfDefinition]:
    """
    获取精灵列表。

    支持按名称模糊搜索，返回精灵定义列表。

    Args:
        q: 搜索关键词，匹配 elf_name 字段
        limit: 返回数量限制，默认 50，最大 500
        offset: 分页偏移量，默认 0
        db: 数据库会话，由依赖注入提供

    Returns:
        list[ElfDefinition]: 精灵定义列表，按名称排序

    Example:
        GET /api/v1/elves?q=火&limit=10
    """
    # 构建基础查询，排除已软删除的记录
    stmt = select(ElfDefinition).where(ElfDefinition.deleted_at.is_(None))

    # 如果有搜索关键词，添加模糊匹配条件
    if q:
        stmt = stmt.where(ElfDefinition.elf_name.contains(q))

    # 按名称排序并应用分页
    stmt = stmt.order_by(ElfDefinition.elf_name).limit(limit).offset(offset)

    return list(db.scalars(stmt).all())


@router.get("/{elf_id}/skills", response_model=list[SkillDefinitionOut])
def list_elf_learnable_skills(
    elf_id: str,
    q: str | None = Query(default=None, description="按 skill_name 模糊搜索"),
    limit: int = Query(default=100, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> list[SkillDefinition]:
    """查询某只精灵的可学习技能池。"""
    elf = db.get(ElfDefinition, elf_id)
    if elf is None or elf.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Elf not found")
    stmt = (
        select(SkillDefinition)
        .join(ElfLearnableSkill, SkillDefinition.skill_id == ElfLearnableSkill.skill_id)
        .where(ElfLearnableSkill.elf_id == elf_id, SkillDefinition.deleted_at.is_(None))
    )
    if q:
        stmt = stmt.where(SkillDefinition.skill_name.contains(q))
    stmt = stmt.order_by(SkillDefinition.skill_name).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.get("/{elf_id}", response_model=ElfDefinitionOut)
def get_elf(elf_id: str, db: Session = Depends(get_db)) -> ElfDefinition:
    """
    获取单个精灵详情。

    根据精灵 ID 获取完整的精灵定义信息。

    Args:
        elf_id: 精灵唯一标识符
        db: 数据库会话，由依赖注入提供

    Returns:
        ElfDefinition: 精灵定义详情

    Raises:
        HTTPException: 404 - 精灵不存在或已删除

    Example:
        GET /api/v1/elves/elf_001
    """
    # 查询精灵，使用 db.get 通过主键快速查找
    elf = db.get(ElfDefinition, elf_id)

    # 检查精灵是否存在且未被软删除
    if elf is None or elf.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Elf not found")

    return elf
