"""管理端战斗清理 Schema。

这些 Schema 只用于归档战斗的清理管理接口。物理删除会移除战斗关联的
运行时、事件、快照、候选和缓存数据，因此默认要求先 dry-run 预览。
"""

from pydantic import BaseModel, Field


class BattlePurgePlanOut(BaseModel):
    """单场战斗物理删除预览。"""

    battle_id: str
    battle_name: str | None = None
    phase: str | None = None
    can_purge: bool
    reason: str | None = None
    rows: dict[str, int] = Field(default_factory=dict)


class BattlePurgeResultOut(BaseModel):
    """物理删除执行结果。"""

    dry_run: bool
    battle_count: int
    battle_ids: list[str] = Field(default_factory=list)
    rows: dict[str, int] = Field(default_factory=dict)
    message: str
