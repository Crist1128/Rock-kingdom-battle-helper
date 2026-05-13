from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.static import ElfDefinition
from app.schemas.static import ElfDefinitionOut

router = APIRouter()


@router.get("", response_model=list[ElfDefinitionOut])
def list_elves(
    q: str | None = Query(default=None, description="按 elf_name 模糊搜索"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ElfDefinition]:
    stmt = select(ElfDefinition).where(ElfDefinition.deleted_at.is_(None))
    if q:
        stmt = stmt.where(ElfDefinition.elf_name.contains(q))
    stmt = stmt.order_by(ElfDefinition.elf_name).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


@router.get("/{elf_id}", response_model=ElfDefinitionOut)
def get_elf(elf_id: str, db: Session = Depends(get_db)) -> ElfDefinition:
    elf = db.get(ElfDefinition, elf_id)
    if elf is None or elf.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Elf not found")
    return elf
