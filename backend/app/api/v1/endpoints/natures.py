"""
性格定义查询端点。

前端己方配置编辑器需要让用户从已有性格规则中选择 nature_id，而不是手工
输入字符串。本模块只提供只读查询接口；性格数据仍由 seed 或规则库导入维护。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.static import NatureDefinition
from app.schemas.static import NatureDefinitionOut

router = APIRouter()


@router.get("", response_model=list[NatureDefinitionOut])
def list_natures(
    q: str | None = Query(default=None, description="按 nature_name 或 nature_id 模糊搜索"),
    positive_stat: str | None = Query(default=None, description="按正面修正属性筛选"),
    negative_stat: str | None = Query(default=None, description="按负面修正属性筛选"),
    limit: int = Query(default=100, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="分页偏移量"),
    db: Session = Depends(get_db),
) -> list[NatureDefinition]:
    """获取性格定义列表，用于己方配置编辑页的性格下拉框。"""
    stmt = select(NatureDefinition).where(NatureDefinition.deleted_at.is_(None))
    if q:
        stmt = stmt.where(
            NatureDefinition.nature_name.contains(q) | NatureDefinition.nature_id.contains(q)
        )
    if positive_stat:
        stmt = stmt.where(NatureDefinition.positive_stat == positive_stat)
    if negative_stat:
        stmt = stmt.where(NatureDefinition.negative_stat == negative_stat)
    stmt = stmt.order_by(NatureDefinition.nature_id).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.get("/{nature_id}", response_model=NatureDefinitionOut)
def get_nature(nature_id: str, db: Session = Depends(get_db)) -> NatureDefinition:
    """获取单个性格定义。"""
    nature = db.get(NatureDefinition, nature_id)
    if nature is None or nature.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Nature not found")
    return nature
