"""
战斗事件 Schema 定义模块。

本模块定义通用战斗事件和伤害事件的输入/输出结构。第一阶段以手动录入为主，
伤害公式尚未确认，因此伤害事件只负责记录事实、创建快照并返回公式占位状态。
"""

from pydantic import BaseModel, Field, model_validator

from app.core.enums import DamageDisplayType
from app.schemas.common import ORMBase


class BattleEventCreate(BaseModel):
    """
    战斗事件创建请求 Schema。

    用于创建通用战斗事件。具体事件详情可写入 payload_json，或通过更专门的
    端点创建，例如 /damage-events。\n
    Attributes:
        turn_number: 发生回合。
        event_type: 事件类型。
        actor_side: 行动方阵营。
        actor_elf_id: 行动方精灵 ID。
        target_side: 目标方阵营。
        target_elf_id: 目标方精灵 ID。
        skill_id: 关联技能 ID。
        skill_confirmed: 技能是否已确认。
        snapshot_id: 关联快照 ID。
        source: 事件来源。
        recognition_confidence: 识别可信度。
        manual_override: 是否被手动覆盖。
        payload_json: 附加数据 JSON 字符串。
        notes: 备注。
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
    """战斗事件输出 Schema。"""

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


class DamageEventCreate(BaseModel):
    """
    伤害事件创建请求。

    三种伤害显示类型的校验规则：\n
    - single_damage：必须传 damage_value。
    - visual_total_damage：必须传 final_total_damage_value；服务层会同步为 damage_value。
    - combo_repeated_damage：必须传 per_hit_damage_value 和 hit_count；服务层计算总伤害。

    伤害公式尚未确认，本请求不会触发候选排除，只会创建事件、快照和公式占位结果。
    """

    turn_number: int | None = Field(default=None, description="发生回合，默认使用战斗当前回合")
    attacker_side: str | None = Field(default=None, description="攻击方阵营")
    attacker_elf_id: str | None = Field(default=None, description="攻击方精灵 ID")
    defender_side: str | None = Field(default=None, description="防御方阵营")
    defender_elf_id: str | None = Field(default=None, description="防御方精灵 ID")
    skill_id: str | None = Field(default=None, description="技能 ID")
    skill_confirmed: bool = Field(default=False, description="技能是否确认")
    damage_display_type: DamageDisplayType = Field(..., description="伤害显示类型")
    damage_value: int | None = Field(default=None, ge=0, description="单次或总伤害")
    final_total_damage_value: int | None = Field(
        default=None,
        ge=0,
        description="动画多段最终总伤害",
    )
    per_hit_damage_value: int | None = Field(default=None, ge=0, description="连击单段伤害")
    hit_count: int | None = Field(default=None, ge=1, description="连击次数")
    combo_count_source: str | None = Field(default="manual_input", description="连击次数来源")
    combo_confidence: float | None = Field(default=1.0, ge=0, le=1, description="连击可信度")
    hp_percent_before: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="受击前生命百分比",
    )
    hp_percent_after: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="受击后生命百分比",
    )
    enemy_hp_percent_damage: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="扣血百分比",
    )
    notes: str | None = Field(default=None, description="备注")

    @model_validator(mode="after")
    def validate_damage_payload(self) -> "DamageEventCreate":
        """按 damage_display_type 校验必填字段。"""
        if self.damage_display_type == DamageDisplayType.SINGLE_DAMAGE:
            if self.damage_value is None:
                raise ValueError("single_damage 必须提供 damage_value")
        elif self.damage_display_type == DamageDisplayType.VISUAL_TOTAL_DAMAGE:
            if self.final_total_damage_value is None:
                raise ValueError("visual_total_damage 必须提供 final_total_damage_value")
        elif self.damage_display_type == DamageDisplayType.COMBO_REPEATED_DAMAGE:
            if self.per_hit_damage_value is None or self.hit_count is None:
                raise ValueError("combo_repeated_damage 必须提供 per_hit_damage_value 和 hit_count")
        return self


class DamageEventOut(ORMBase):
    """伤害事件输出 Schema。"""

    event_id: str
    battle_id: str
    battle_event_id: str
    attacker_side: str | None = None
    attacker_elf_id: str | None = None
    defender_side: str | None = None
    defender_elf_id: str | None = None
    skill_id: str | None = None
    damage_display_type: str
    damage_value: int | None = None
    final_total_damage_value: int | None = None
    per_hit_damage_value: int | None = None
    hit_count: int | None = None
    computed_total_damage_value: int | None = None
    hp_percent_before: float | None = None
    hp_percent_after: float | None = None
    hp_percent_delta: float | None = None
    enemy_hp_percent_damage: float | None = None
    formula_context_json: str | None = None
    calculation_confidence: float | None = None
    manual_override: bool


class DamageEventCreateResult(BaseModel):
    """
    创建伤害事件后的组合响应。

    包含通用事件、伤害详情、快照 ID 和推算占位结果，方便前端一次调用后
    立即更新战斗状态与提示信息。
    """

    battle_event: BattleEventOut
    damage_event: DamageEventOut
    snapshot_id: str
    inference_result: dict
