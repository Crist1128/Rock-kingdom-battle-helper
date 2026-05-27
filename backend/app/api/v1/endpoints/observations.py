"""观察事件处理端点。

该模块是第三里程碑的 API 接入层：前端把玩家手动录入的伤害、扣血比例、
技能出现、先后手等观察事实提交到这里，后端再复用 InferenceEngine 更新敌方候选配置的
软评分、置信度和证据链。
"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.inference.inference_engine import InferenceEngine
from app.inference.observation_matcher import ObservationEventInput
from app.schemas.observation import ObservationCreate, ObservationProcessResult
from app.services.battle_service import BattleService

router = APIRouter()


@router.post("/{battle_id}", response_model=ObservationProcessResult)
def process_observation(
    battle_id: str,
    payload: ObservationCreate,
    db: Session = Depends(get_db),
) -> ObservationProcessResult:
    """处理一条玩家观察事件，并更新指定敌方精灵的候选池评分。

    当前端调用示例：
    ``POST /api/v1/observations/{battle_id}``

    处理流程：
    1. 先校验战斗是否存在，避免把观察写入无效战斗；
    2. 为未显式指定 ID 的观察事件生成稳定前缀的 event_id，方便后续证据链追踪；
    3. 将 API Schema 转换为推理层的 ``ObservationEventInput``；
    4. 调用 ``InferenceEngine.process_observation_event`` 完成候选软评分更新；
    5. 返回本次处理摘要，详细候选分布由 candidates 接口继续查询。
    """
    try:
        BattleService(db).require_battle(battle_id)
        observation = ObservationEventInput(
            battle_id=battle_id,
            enemy_elf_id=payload.enemy_elf_id,
            event_id=payload.event_id or f"observation_{uuid4().hex}",
            observation_type=payload.observation_type,
            observed_value=payload.observed_value,
            payload=payload.payload,
            event_weight=payload.event_weight,
            allow_hard_exclude=payload.allow_hard_exclude,
        )
        result = InferenceEngine(db).process_observation_event(observation)
        return ObservationProcessResult(**result)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # 例如 payload 中面板字段类型不合法、数值无法转换等，都作为客户端请求错误返回。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
