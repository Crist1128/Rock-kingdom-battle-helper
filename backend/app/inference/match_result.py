"""观测匹配结果模型。

所有 matcher 都返回同一种结构，方便 InferenceEngine 统一更新候选分数、证据链和
未知因素。这里刻意允许 ``matched`` 为 ``None``：它表示“当前信息不足，不能判断”，
这种情况既不应加分，也不应扣分，更不能硬排除候选。
"""

from typing import Any

from pydantic import BaseModel, Field


class ObservationMatchResult(BaseModel):
    """单个候选对单个观测事件的匹配结果。"""

    matched: bool | None
    reason: str
    score_delta: float = 0.0
    can_hard_exclude: bool = False
    unknown_factors: list[str] = Field(default_factory=list)
    observed_value: int | float | str | None = None
    predicted_value: int | float | str | None = None
    predicted_range: tuple[int, int] | tuple[float, float] | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def matched_result(
        cls,
        *,
        reason: str,
        score_delta: float,
        observed_value: int | float | str | None = None,
        predicted_value: int | float | str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> "ObservationMatchResult":
        """构造“匹配成功”的结果。"""
        return cls(
            matched=True,
            reason=reason,
            score_delta=score_delta,
            observed_value=observed_value,
            predicted_value=predicted_value,
            evidence=evidence or {},
        )

    @classmethod
    def mismatched_result(
        cls,
        *,
        reason: str,
        score_delta: float,
        observed_value: int | float | str | None = None,
        predicted_value: int | float | str | None = None,
        can_hard_exclude: bool = False,
        evidence: dict[str, Any] | None = None,
    ) -> "ObservationMatchResult":
        """构造“明确不匹配”的结果。"""
        return cls(
            matched=False,
            reason=reason,
            score_delta=score_delta,
            can_hard_exclude=can_hard_exclude,
            observed_value=observed_value,
            predicted_value=predicted_value,
            evidence=evidence or {},
        )

    @classmethod
    def unknown_result(
        cls,
        *,
        reason: str,
        unknown_factors: list[str],
        observed_value: int | float | str | None = None,
        predicted_value: int | float | str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> "ObservationMatchResult":
        """构造“信息不足，暂不判断”的结果。"""
        return cls(
            matched=None,
            reason=reason,
            score_delta=0.0,
            unknown_factors=unknown_factors,
            observed_value=observed_value,
            predicted_value=predicted_value,
            evidence=evidence or {},
        )
