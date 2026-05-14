"""
敌方候选配置端点。

用于查看准备阶段生成的候选摘要和分页候选明细。第一阶段只展示候选池状态，
伤害公式未确认时不会执行候选排除。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.candidate import CandidateOut, CandidateSummaryOut
from app.services.battle_service import BattleService
from app.services.candidate_service import CandidateService

router = APIRouter()


@router.post("/{battle_id}/{elf_id}/generate", response_model=CandidateSummaryOut)
def generate_candidates(
    battle_id: str,
    elf_id: str,
    db: Session = Depends(get_db),
) -> CandidateSummaryOut:
    """手动重新生成某只敌方精灵的候选配置。"""
    try:
        BattleService(db).require_battle(battle_id)
        service = CandidateService(db)
        service.generate_for_enemy_elf(battle_id, elf_id)
        return service.summarize(battle_id, elf_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{battle_id}/{elf_id}/summary", response_model=CandidateSummaryOut)
def get_candidate_summary(
    battle_id: str,
    elf_id: str,
    db: Session = Depends(get_db),
) -> CandidateSummaryOut:
    """获取候选配置摘要。"""
    try:
        BattleService(db).require_battle(battle_id)
        return CandidateService(db).summarize(battle_id, elf_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{battle_id}/{elf_id}", response_model=list[CandidateOut])
def list_candidates(
    battle_id: str,
    elf_id: str,
    include_excluded: bool = Query(default=False, description="是否包含已排除候选"),
    limit: int = Query(default=50, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
):
    """分页查看候选配置明细。"""
    try:
        BattleService(db).require_battle(battle_id)
        return CandidateService(db).list_candidates(
            battle_id,
            elf_id,
            include_excluded=include_excluded,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
