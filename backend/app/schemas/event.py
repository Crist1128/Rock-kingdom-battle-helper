"""
战斗事件 Schema 定义模块。

本模块定义战斗事件相关的 Pydantic Schema，用于：
- 战斗事件创建请求
- 战斗事件查询响应
"""

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class BattleEventCreate(BaseModel):
    """
    战斗事件创建请求 Schema。

    用于创建战斗事件时的请求数据校验。
    包含事件的基础信息，具体细节根据事件类型存储在 payload_json 中。

    Attributes:
        turn_number: 发生回合
        event_type: 事件类型
        actor_side: 行动方阵营
        actor_elf_id: 行动方精灵 ID
        target_side: 目标方阵营
        target_elf_id: 目标方精灵 ID
        skill_id: 关联技能 ID
        skill_confirmed: 技能是否已确认
        snapshot_id: 关联快照 ID
        source: 事件来源
        recognition_confidence: 识别可信度
        manual_override: 是否被手动覆盖
        payload_json: 附加数据（JSON 字符串）
        notes: 备注
    """
    turn_number: int = Field(..., description="回合数")
    event_type: str = Field(..., description="事件类型")
    actor_side: str | None = Field(default=None, description="行动方阵营")
    actor_elf_id: str | None = Field(default=None, description="行动方精灵 ID")
    target_side: str | None = Field(default=None, description="目标方阵营")
    target_elf_id: str | None = Field(default=None, description="目标方精灵 ID")
    skill_id: str | None = Field(default=None, description="技能 ID")
    skill_confirmed: bool = Field(default=False, description="技能是否已确认")
    snapshot_id: str | None = Field(default=None, description="快照 ID")
    source: str = Field(default="manual_input", description="事件来源")
    recognition_confidence: float | None = Field(default=None, description="识别可信度")
    manual_override: bool = Field(default=False, description="是否手动覆盖")
    payload_json: str | None = Field(default=None, description="附加数据")
    notes: str | None = Field(default=None, description="备注")


class BattleEventOut(ORMBase):
    """
    战斗事件输出 Schema。

    用于 API 响应中返回事件信息。

    Attributes:
        event_id: 事件唯一标识
        battle_id: 所属战斗 ID
        turn_number: 发生回合
        event_type: 事件类型
        actor_side: 行动方阵营
        actor_elf_id: 行动方精灵 ID
        target_side: 目标方阵营
        target_elf_id: 目标方精灵 ID
        skill_id: 关联技能 ID
        skill_confirmed: 技能是否已确认
        snapshot_id: 关联快照 ID
        source: 事件来源
        recognition_confidence: 识别可信度
        manual_override: 是否被手动覆盖
        payload_json: 附加数据
        notes: 备注
    """
    event_id: str
    battle_id: str
    turn_number: int
    event_type: str
    actor_side: str | None = None
    actor_elf_id: str | None = None
    target_side: str | None = None
    target_elf_id: str | None = None
    skill_id: str | None = None
    skill_confirmed: bool
    snapshot_id: str | None = None
    source: str
    recognition_confidence: float | None = None
    manual_override: bool
    payload_json: str | None = None
    notes: str | None = None
