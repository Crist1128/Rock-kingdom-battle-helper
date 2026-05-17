"""
敌方配置推算引擎模块。

当前阶段不实现真实候选过滤。引擎只负责接收伤害事件上下文，调用伤害计算
占位器，并返回“公式未确认”的结构化结果。这样后续公式确认后可以直接在本
模块补充候选评分与排除逻辑，而不破坏 API 和事件流。
"""

from sqlalchemy.orm import Session

from app.calculation.damage_calculator import DamageCalculator
from app.calculation.formula_context import DamageFormulaContext
from app.models.event import DamageEvent


class InferenceEngine:
    """
    敌方配置推算引擎。

    后续真实实现应在 process_damage_event 中增加：
    1. 读取 DamageEvent 与 BattleEffectSnapshot；
    2. 枚举对应敌方 BuildCandidate；
    3. 使用 DamageCalculator 计算理论伤害；
    4. 对比观测伤害和扣血百分比；
    5. 更新候选 match_score、confidence、is_excluded；
    6. 记录 evidence_ids_json 与解释信息。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.damage_calculator = DamageCalculator()

    def process_damage_event(
        self,
        damage_event: DamageEvent,
        context: DamageFormulaContext,
    ) -> dict:
        """
        处理伤害事件。

        当前不排除任何候选，只返回公式占位结果，并把 calculation_confidence
        保持为 0.0。
        """
        result = self.damage_calculator.calculate(context)
        damage_event.calculation_confidence = result.confidence
        return {
            "status": result.status,
            "damage_event_id": damage_event.event_id,
            "candidate_filter_applied": False,
            "excluded_candidate_count": 0,
            "confidence": result.confidence,
            "missing_parts": result.missing_parts,
            "message": result.message,
        }
