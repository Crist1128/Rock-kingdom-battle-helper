from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.static import SkillDefinition
from app.schemas.static import SkillDefinitionOut

router = APIRouter()


@router.get("", response_model=list[SkillDefinitionOut])
def list_skills(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[SkillDefinition]:
    stmt = select(SkillDefinition).where(SkillDefinition.deleted_at.is_(None))
    if q:
        stmt = stmt.where(SkillDefinition.skill_name.contains(q))
    stmt = stmt.order_by(SkillDefinition.skill_name).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.get("/{skill_id}", response_model=SkillDefinitionOut)
def get_skill(skill_id: str, db: Session = Depends(get_db)) -> SkillDefinition:
    skill = db.get(SkillDefinition, skill_id)
    if skill is None or skill.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill
