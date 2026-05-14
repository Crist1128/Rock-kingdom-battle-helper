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


class StartBattleInput(BaseModel):
    """
    进入战斗阶段请求。

    准备阶段阵容录入后，调用此请求确认双方首发并切换到 battle 阶段。
    如果阵容录入时已经设置首发，也可以不传 active_elf_id。
    """

    self_active_elf_id: str | None = Field(default=None, description="己方首发精灵 ID")
    enemy_active_elf_id: str | None = Field(default=None, description="敌方首发精灵 ID")


class SwitchElfInput(BaseModel):
    """
    切换当前上场精灵请求。

    切换时会触发 clear_on_switch 规则：可切换清除的状态会失效，不能
    切换清除的状态会保留，并记录状态变化事件。
    """

    side: str = Field(..., description="切换阵营：self 或 enemy")
    elf_id: str = Field(..., description="新上场精灵 ID")
    turn_number: int | None = Field(default=None, description="发生回合，默认使用战斗当前回合")
    notes: str | None = Field(default=None, description="备注")


class LineupOut(BaseModel):
    """
    阵容录入响应。

    返回本次生成的战斗精灵状态数量和敌方候选数量，便于前端确认准备
    阶段是否完成。
    """

    battle_id: str
    created_elf_state_count: int
    generated_candidate_count: int
    self_active_elf_id: str | None = None
    enemy_active_elf_id: str | None = None
