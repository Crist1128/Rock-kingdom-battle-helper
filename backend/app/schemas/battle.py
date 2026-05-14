"""
战斗相关 Schema 定义模块。

本模块定义战斗相关的 Pydantic Schema，用于：
- 战斗创建请求和响应
- 战斗状态查询响应
- 阵容录入请求
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMBase


class BattleCreate(BaseModel):
    """
    战斗创建请求 Schema。

    用于创建新战斗时的请求数据校验。

    Attributes:
        battle_name: 战斗名称（可选）
        notes: 备注信息（可选）
    """
    battle_name: str | None = Field(default=None, description="战斗名称，可为空")
    notes: str | None = Field(default=None, description="备注信息")


class BattleOut(ORMBase):
    """
    战斗基础信息输出 Schema。

    用于 API 响应中返回战斗的基本信息。

    Attributes:
        battle_id: 战斗唯一标识
        battle_name: 战斗名称
        phase: 当前阶段
        turn_number: 当前回合数
        self_active_elf_id: 己方当前上场精灵 ID
        enemy_active_elf_id: 敌方当前上场精灵 ID
        current_snapshot_id: 当前状态快照 ID
        notes: 备注信息
    """
    battle_id: str
    battle_name: str | None = None
    phase: str
    turn_number: int
    self_active_elf_id: str | None = None
    enemy_active_elf_id: str | None = None
    current_snapshot_id: str | None = None
    notes: str | None = None


class BattleStateOut(BaseModel):
    """
    战斗完整状态输出 Schema。

    用于 API 响应中返回战斗的完整状态，包括：
    - 战斗基本信息
    - 所有参战精灵状态
    - 当前生效的状态效果
    - 最新快照 ID

    Attributes:
        battle: 战斗基础信息
        elves: 精灵状态列表（字典格式）
        active_effects: 生效状态效果列表（字典格式）
        latest_snapshot_id: 最新快照 ID
    """
    model_config = ConfigDict(from_attributes=True)

    battle: BattleOut
    elves: list[dict] = Field(default_factory=list, description="精灵状态列表")
    active_effects: list[dict] = Field(default_factory=list, description="生效状态效果列表")
    latest_snapshot_id: str | None = Field(default=None, description="最新快照 ID")


class LineupElfInput(BaseModel):
    """
    阵容录入-精灵输入 Schema。

    用于录入战斗阵容时指定单个精灵的信息。

    Attributes:
        side: 所属阵营（self/enemy）
        elf_id: 精灵定义 ID
        build_id: 己方配置 ID（仅己方需要）
        is_active_elf: 是否首发上场
    """
    side: str = Field(..., description="所属阵营")
    elf_id: str = Field(..., description="精灵 ID")
    build_id: str | None = Field(default=None, description="配置 ID（己方）")
    is_active_elf: bool = Field(default=False, description="是否首发")


class LineupInput(BaseModel):
    """
    阵容录入请求 Schema。

    用于录入战斗的完整阵容。

    Attributes:
        elves: 精灵列表，包含双方六只精灵
    """
    elves: list[LineupElfInput] = Field(..., description="精灵列表")
