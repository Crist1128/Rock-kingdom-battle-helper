"""观察事件 API Schema。

第三里程碑开始把“玩家手动录入的观察事实”开放给前端调用。
这些 Schema 只负责 API 层的输入输出校验；真正的候选匹配与评分逻辑仍在
``app.inference`` 包中，避免接口层混入数学计算细节。
"""

from typing import Any

from pydantic import BaseModel, Field

from app.inference.observation_types import ObservationType


class ObservationCreate(BaseModel):
    """提交一条观察事件的请求体。

    字段设计原则：
    - ``battle_id`` 放在 URL 路径中，保证同一类资源路径稳定；
    - ``enemy_elf_id`` 明确指定本次观察要更新哪只敌方精灵的候选池；
    - ``observation_type`` 决定由哪个 matcher 处理；
    - ``observed_value`` 存放最常见的单值观察，例如伤害数字、扣血百分比、先后手结果；
    - ``payload`` 存放不同观察类型的扩展上下文，例如我方攻击面板、技能威力、容差等；
    - ``allow_hard_exclude`` 默认关闭，延续 MVP 阶段“软评分优先”的策略。
    """

    enemy_elf_id: str = Field(..., min_length=1, description="被观察的敌方精灵 ID")
    event_id: str | None = Field(
        default=None,
        description="观察事件 ID；不传时后端自动生成 observation_<uuid>",
    )
    observation_type: ObservationType = Field(..., description="观察事件类型")
    observed_value: int | float | str | None = Field(
        default=None,
        description="观察到的核心数值或枚举值，例如伤害数字、扣血百分比、self_first",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="观察上下文；不同 observation_type 使用不同键集合",
    )
    event_weight: float | None = Field(
        default=None,
        description="本事件的评分权重；不传时由 matcher 使用默认权重",
    )
    allow_hard_exclude: bool = Field(
        default=False,
        description="是否允许本次观察直接硬排除候选；MVP 默认应保持 false",
    )


class ObservationProcessResult(BaseModel):
    """观察事件处理结果。

    该响应给前端提供“本次录入是否改变了候选分布”的摘要。
    更详细的候选列表与证据链仍通过 candidates 相关接口查看，避免单次提交返回过大的数据。
    """

    status: str
    battle_id: str
    enemy_elf_id: str
    event_id: str
    observation_type: str
    candidate_count: int
    matched_count: int
    mismatched_count: int
    unknown_count: int
    hard_excluded_count: int
    hard_filter_applied: bool
    top_candidate_id: str | None = None
    top_confidence: float | None = None
