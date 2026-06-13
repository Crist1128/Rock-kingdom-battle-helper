"""观察事件处理端点。"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.inference.observation_event import ObservationEventInput
from app.schemas.observation import ObservationCreate, ObservationProcessResult
from app.services.battle_service import BattleService
from app.services.estimate_service import EstimateService

router = APIRouter()


@router.post("/{battle_id}", response_model=ObservationProcessResult)
def process_observation(
    battle_id: str,
    payload: ObservationCreate,
    db: Session = Depends(get_db),
) -> ObservationProcessResult:
    """处理一条玩家观察事件，并更新敌方实时面板估计。"""
    try:
        BattleService(db).require_battle(battle_id)
        event_id = payload.event_id or f"observation_{uuid4().hex}"
        observation = ObservationEventInput(
            battle_id=battle_id,
            enemy_elf_id=payload.enemy_elf_id,
            event_id=event_id,
            observation_type=payload.observation_type,
            observed_value=payload.observed_value,
            payload=payload.payload,
            event_weight=payload.event_weight,
        )
        estimate = EstimateService(db).record_observation(observation, commit=True)
        inferred_stats = estimate.evidence_summary[-1].get("affected_stats", []) if estimate else []
        return ObservationProcessResult(
            status="estimate_updated" if estimate is not None else "ignored",
            battle_id=battle_id,
            enemy_elf_id=payload.enemy_elf_id,
            event_id=event_id,
            observation_type=payload.observation_type.value,
            estimate_id=estimate.estimate_id if estimate is not None else None,
            inferred_stat_count=len(inferred_stats),
            affected_stats=[str(item) for item in inferred_stats],
            unknown_factor_count=len(estimate.unknown_factors) if estimate is not None else 0,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # 例如 payload 中面板字段类型不合法、数值无法转换等，都作为客户端请求错误返回。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
