"""独立伤害计算器端点。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.damage_calculator import (
    DamageCalculatorBootstrapOut,
    DamageCalculatorCalculateInput,
    DamageCalculatorInferDefenderBatchInput,
    DamageCalculatorInferDefenderBatchOut,
    DamageCalculatorInferDefenderInput,
    DamageCalculatorInferDefenderOut,
    DamageCalculatorResultOut,
)
from app.services.standalone_damage_service import StandaloneDamageService

router = APIRouter()


@router.get("/bootstrap", response_model=DamageCalculatorBootstrapOut)
def bootstrap_damage_calculator(db: Session = Depends(get_db)) -> DamageCalculatorBootstrapOut:
    """读取最近战斗摘要，供独立计算器快捷填充。"""
    return StandaloneDamageService(db).bootstrap()


@router.post("/calculate", response_model=DamageCalculatorResultOut)
def calculate_standalone_damage(
    payload: DamageCalculatorCalculateInput,
    db: Session = Depends(get_db),
) -> DamageCalculatorResultOut:
    """执行一次独立伤害计算，不写入战斗事件流或推算证据。"""
    try:
        return StandaloneDamageService(db).calculate(payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/infer-defender", response_model=DamageCalculatorInferDefenderOut)
def infer_standalone_defender(
    payload: DamageCalculatorInferDefenderInput,
    db: Session = Depends(get_db),
) -> DamageCalculatorInferDefenderOut:
    """根据真实伤害枚举防御方软候选，不写入实时估计。"""
    try:
        return StandaloneDamageService(db).infer_defender(payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/infer-defender-batch", response_model=DamageCalculatorInferDefenderBatchOut)
def infer_standalone_defender_batch(
    payload: DamageCalculatorInferDefenderBatchInput,
    db: Session = Depends(get_db),
) -> DamageCalculatorInferDefenderBatchOut:
    """根据多条真实伤害累计枚举防御方软候选，不写入实时估计。"""
    try:
        return StandaloneDamageService(db).infer_defender_batch(payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
