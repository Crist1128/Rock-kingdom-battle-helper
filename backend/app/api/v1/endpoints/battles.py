"""
战斗管理端点模块。

提供战斗的 CRUD 和事件记录接口，包括：
- 创建战斗
- 获取战斗详情
- 获取战斗状态
- 创建战斗事件
- 获取战斗事件列表
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.battle import Battle
from app.models.event import BattleEvent
from app.schemas.battle import BattleCreate, BattleOut, BattleStateOut
from app.schemas.event import BattleEventCreate, BattleEventOut
from app.services.battle_service import BattleService

# 创建路由实例
router = APIRouter()


@router.post("", response_model=BattleOut, status_code=201)
def create_battle(payload: BattleCreate, db: Session = Depends(get_db)) -> Battle:
    """
    创建新战斗。

    创建一场新的战斗，进入准备阶段（preparation）。

    Args:
        payload: 战斗创建参数，包含战斗名称和备注
        db: 数据库会话，由依赖注入提供

    Returns:
        Battle: 新创建的战斗对象

    Example:
        POST /api/v1/battles
        Body: {"battle_name": "对战#1", "notes": "排位赛"}
    """
    return BattleService(db).create_battle(payload)


@router.get("/{battle_id}", response_model=BattleOut)
def get_battle(battle_id: str, db: Session = Depends(get_db)) -> Battle:
    """
    获取战斗详情。

    根据战斗 ID 获取战斗的基本信息。

    Args:
        battle_id: 战斗唯一标识符
        db: 数据库会话，由依赖注入提供

    Returns:
        Battle: 战斗对象

    Raises:
        HTTPException: 404 - 战斗不存在或已删除

    Example:
        GET /api/v1/battles/battle_xxx
    """
    battle = db.get(Battle, battle_id)
    if battle is None or battle.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Battle not found")
    return battle


@router.get("/{battle_id}/state", response_model=BattleStateOut)
def get_battle_state(battle_id: str, db: Session = Depends(get_db)) -> BattleStateOut:
    """
    获取战斗完整状态。

    获取战斗的完整状态，包括：
    - 战斗基本信息
    - 所有参战精灵状态
    - 当前生效的状态效果
    - 最新快照 ID

    Args:
        battle_id: 战斗唯一标识符
        db: 数据库会话，由依赖注入提供

    Returns:
        BattleStateOut: 战斗完整状态

    Raises:
        HTTPException: 404 - 战斗不存在或已删除

    Example:
        GET /api/v1/battles/battle_xxx/state
    """
    battle = db.get(Battle, battle_id)
    if battle is None or battle.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Battle not found")
    return BattleService(db).get_state(battle)


@router.post("/{battle_id}/events", response_model=BattleEventOut, status_code=201)
def create_battle_event(
    battle_id: str,
    payload: BattleEventCreate,
    db: Session = Depends(get_db),
) -> BattleEvent:
    """
    创建战斗事件。

    为指定战斗创建一个新的事件记录。

    Args:
        battle_id: 战斗唯一标识符
        payload: 事件创建参数
        db: 数据库会话，由依赖注入提供

    Returns:
        BattleEvent: 新创建的事件对象

    Raises:
        HTTPException: 404 - 战斗不存在或已删除

    Example:
        POST /api/v1/battles/battle_xxx/events
        Body: {"turn_number": 1, "event_type": "skill_use", ...}
    """
    battle = db.get(Battle, battle_id)
    if battle is None or battle.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Battle not found")
    return BattleService(db).create_event(battle_id, payload)


@router.get("/{battle_id}/events", response_model=list[BattleEventOut])
def list_battle_events(battle_id: str, db: Session = Depends(get_db)) -> list[BattleEvent]:
    """
    获取战斗事件列表。

    获取指定战斗的所有事件，按回合数和时间排序。

    Args:
        battle_id: 战斗唯一标识符
        db: 数据库会话，由依赖注入提供

    Returns:
        list[BattleEvent]: 事件列表

    Raises:
        HTTPException: 404 - 战斗不存在或已删除

    Example:
        GET /api/v1/battles/battle_xxx/events
    """
    battle = db.get(Battle, battle_id)
    if battle is None or battle.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Battle not found")

    # 构建查询，按回合数和创建时间排序
    stmt = select(BattleEvent).where(BattleEvent.battle_id == battle_id).order_by(
        BattleEvent.turn_number, BattleEvent.created_at
    )
    return list(db.scalars(stmt).all())
