"""
战斗状态实例 Schema。

静态状态定义仍在 schemas.static 中。本模块描述战斗过程中实际发生的
状态应用、移除和切换清除请求。
"""

from pydantic import BaseModel, Field


class EffectApplyInput(BaseModel):
    """
    手动施加状态请求。

    第一阶段暂不自动执行技能 effect_operations，前端或用户可以通过该接口
    手动把状态写入统一状态系统。\n
    owner_scope 决定状态挂载位置：
    - elf：需要 owner_side + owner_elf_id。
    - side：需要 owner_side。
    - field：挂在全战场。
    - skill_slot：需要 owner_skill_slot_id。
    """

    effect_id: str = Field(..., description="状态定义 ID")
    battle_id: str = Field(..., description="战斗 ID")
    owner_scope: str = Field(..., description="归属范围")
    owner_side: str | None = Field(default=None, description="归属阵营")
    owner_elf_id: str | None = Field(default=None, description="归属精灵 ID")
    owner_skill_slot_id: str | None = Field(default=None, description="归属技能槽 ID")
    field_id: str | None = Field(default="main", description="战场 ID")
    source_side: str | None = Field(default=None, description="来源阵营")
    source_elf_id: str | None = Field(default=None, description="来源精灵 ID")
    source_skill_id: str | None = Field(default=None, description="来源技能 ID")
    turn_number: int | None = Field(default=None, description="发生回合")
    layers: int | None = Field(default=None, ge=1, description="层数，不传则使用默认层数")
    remaining_turns: int | None = Field(default=None, ge=0, description="剩余回合")
    remaining_uses: int | None = Field(default=None, ge=0, description="剩余次数")
    notes: str | None = Field(default=None, description="备注")


class EffectRemoveInput(BaseModel):
    """手动移除状态请求。"""

    turn_number: int | None = Field(default=None, description="发生回合")
    reason: str | None = Field(default="manual_remove", description="移除原因")


class EffectInstanceOut(BaseModel):
    """战斗状态实例输出。"""

    instance_id: str
    battle_id: str
    effect_id: str
    category: str
    owner_scope: str
    owner_side: str | None = None
    owner_elf_id: str | None = None
    owner_skill_slot_id: str | None = None
    field_id: str | None = None
    source_side: str | None = None
    source_elf_id: str | None = None
    source_skill_id: str | None = None
    layers: int
    remaining_turns: int | None = None
    remaining_uses: int | None = None
    is_active: bool
    applied_turn: int | None = None
    expire_turn: int | None = None
    last_updated_turn: int | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}
