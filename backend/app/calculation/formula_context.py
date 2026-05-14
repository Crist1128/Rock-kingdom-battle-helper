"""
公式上下文模型。

这里定义计算模块的稳定输入/输出结构。即使真实公式尚未实现，事件流、
快照和候选配置也可以先按照这些结构组织，后续替换计算器即可。
"""

from pydantic import BaseModel, Field


class DamageFormulaContext(BaseModel):
    """
    伤害公式上下文。

    第一阶段只作为“记录计算所需事实”的容器，不执行真实公式。后续公式确认后，
    DamageCalculator 可以直接读取此上下文进行计算。
    """

    battle_id: str
    damage_event_id: str
    battle_event_id: str
    snapshot_id: str
    attacker_side: str | None = None
    attacker_elf_id: str | None = None
    defender_side: str | None = None
    defender_elf_id: str | None = None
    skill_id: str | None = None
    damage_display_type: str
    observed_damage_value: int | None = None
    observed_hp_percent_delta: float | None = None
    snapshot_payload: dict | list | None = None
    notes: str | None = None


class CalculationPlaceholderResult(BaseModel):
    """
    计算占位结果。

    status 固定使用 formula_unavailable，明确告诉调用方：当前记录了事实，但没有
    执行真实伤害公式，也不会据此排除候选配置。
    """

    status: str = "formula_unavailable"
    damage_value: int | None = None
    damage_range: tuple[int, int] | None = None
    confidence: float = 0.0
    missing_parts: list[str] = Field(default_factory=list)
    context_id: str | None = None
    message: str = "伤害公式尚未确认，本次只记录事实，不执行候选排除。"
