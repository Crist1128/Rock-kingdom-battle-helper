"""
配队预设 Schema。

配队预设用于准备阶段快速填充阵容：己方配队引用已计算好的 build_id，
敌方热门阵容可以只保存 elf_id。
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class TeamPresetSlotInput(BaseModel):
    """配队槽位输入。"""

    slot_index: int = Field(..., ge=0, le=5, description="槽位序号，0-5")
    elf_id: str = Field(..., description="精灵 ID")
    build_id: str | None = Field(default=None, description="己方配置 ID，可为空")
    notes: str | None = Field(default=None, description="槽位备注")


class TeamPresetCreate(BaseModel):
    """创建配队预设请求。"""

    preset_name: str = Field(..., min_length=1, description="配队名称")
    side_usage: str = Field(default="self", description="使用侧：self/enemy/both")
    source_type: str = Field(default="custom", description="来源类型：custom/popular")
    notes: str | None = Field(default=None, description="备注")
    slots: list[TeamPresetSlotInput] = Field(default_factory=list, description="配队槽位")

    @field_validator("side_usage")
    @classmethod
    def validate_side_usage(cls, value: str) -> str:
        """限制配队使用侧枚举。"""
        if value not in {"self", "enemy", "both"}:
            raise ValueError("side_usage 只能是 self、enemy 或 both")
        return value

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, value: str) -> str:
        """限制配队来源枚举。"""
        if value not in {"custom", "popular"}:
            raise ValueError("source_type 只能是 custom 或 popular")
        return value

    @model_validator(mode="after")
    def validate_slots(self) -> "TeamPresetCreate":
        """槽位数量和序号不能重复。"""
        if len(self.slots) > 6:
            raise ValueError("配队最多只能包含 6 个槽位")
        slot_indexes = [slot.slot_index for slot in self.slots]
        if len(slot_indexes) != len(set(slot_indexes)):
            raise ValueError("配队槽位不能重复")
        return self


class TeamPresetUpdate(TeamPresetCreate):
    """更新配队预设请求，采用整单替换槽位。"""


class TeamPresetSlotOut(BaseModel):
    """配队槽位输出。"""

    slot_id: str
    preset_id: str
    slot_index: int
    elf_id: str
    elf_name: str | None = None
    avatar: str | None = None
    element_types_json: str | None = None
    build_id: str | None = None
    build_name: str | None = None
    notes: str | None = None


class TeamPresetOut(BaseModel):
    """配队预设输出。"""

    preset_id: str
    preset_name: str
    side_usage: str
    source_type: str
    notes: str | None = None
    slots: list[TeamPresetSlotOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
