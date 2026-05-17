"""战斗归档数据清理管理接口。

这些接口用于清理已经归档的战斗记录。普通“移除最近战斗”只会归档，
不会删除数据；本接口执行不可逆物理删除，因此需要管理令牌保护，并默认
使用 dry-run 预览。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.data_updates import verify_admin_token
from app.db.session import get_db
from app.schemas.admin_battle import BattlePurgePlanOut, BattlePurgeResultOut
from app.services.admin_battle_service import AdminBattleService

router = APIRouter()


@router.get(
    "/{battle_id}/purge-plan",
    response_model=BattlePurgePlanOut,
    summary="预览单场战斗物理删除范围",
)
def get_battle_purge_plan(
    battle_id: str,
    _: None = Depends(verify_admin_token),
    db: Session = Depends(get_db),
) -> BattlePurgePlanOut:
    """预览单场战斗将删除的关联表行数，不修改数据库。"""
    try:
        return AdminBattleService(db).plan_battle_purge(battle_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "battle_not_found",
                "message": str(exc),
                "hint": "请刷新归档战斗列表；如果该战斗刚被批量清理，它已经不存在。",
            },
        ) from exc


@router.delete(
    "/purge-archived",
    response_model=BattlePurgeResultOut,
    summary="批量物理删除已归档战斗",
)
def purge_archived_battles(
    older_than_days: int | None = Query(
        default=None,
        ge=0,
        description="只清理更新时间早于 N 天的归档战斗；为空表示不按时间过滤。",
    ),
    dry_run: bool = Query(default=True, description="为 true 时只预览不删除。"),
    limit: int | None = Query(default=None, ge=1, le=500, description="最多清理多少场。"),
    _: None = Depends(verify_admin_token),
    db: Session = Depends(get_db),
) -> BattlePurgeResultOut:
    """批量清理 archived 战斗，默认 dry-run。"""
    return AdminBattleService(db).purge_archived_battles(
        older_than_days=older_than_days,
        dry_run=dry_run,
        limit=limit,
    )


@router.delete(
    "/{battle_id}/purge",
    response_model=BattlePurgeResultOut,
    summary="物理删除单场已归档战斗",
)
def purge_battle(
    battle_id: str,
    dry_run: bool = Query(default=True, description="为 true 时只预览不删除。"),
    _: None = Depends(verify_admin_token),
    db: Session = Depends(get_db),
) -> BattlePurgeResultOut:
    """物理删除单场 archived 或已软删除战斗，默认 dry-run。"""
    try:
        return AdminBattleService(db).purge_battle(battle_id, dry_run=dry_run)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "battle_not_found",
                "message": str(exc),
                "hint": "请刷新归档战斗列表；如果该战斗刚被批量清理，它已经不存在。",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "battle_not_purgeable",
                "message": str(exc),
                "hint": "只能物理删除 phase=archived 或已软删除的战斗；普通战斗请先归档。",
            },
        ) from exc
