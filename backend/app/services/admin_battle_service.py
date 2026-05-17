"""管理端战斗清理服务。

普通“移除最近战斗”只会把战斗标记为 archived；本服务负责真正的
物理删除（purge）。物理删除不可逆，因此只允许清理已归档或已软删除
的战斗，并提供 dry-run 预览以降低误删风险。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.enums import BattlePhase
from app.models.battle import Battle, BattleElfState, BattleSkillSlot
from app.models.candidate import BuildCandidate, CalculationCache
from app.models.effect import BattleEffectInstance, BattleEffectSnapshot
from app.models.event import BattleEvent, DamageEvent, EffectChangeEvent, ResourceChangeEvent
from app.schemas.admin_battle import BattlePurgePlanOut, BattlePurgeResultOut


class AdminBattleService:
    """战斗归档数据清理服务。"""

    #: 删除顺序必须先删事件详情与依赖表，最后删 battle 主表。
    #: 目前模型没有依赖 SQLAlchemy 关系级 cascade，因此服务层显式控制顺序。
    _PURGE_ORDER = (
        DamageEvent,
        EffectChangeEvent,
        ResourceChangeEvent,
        BattleEffectSnapshot,
        BattleEffectInstance,
        BattleEvent,
        BuildCandidate,
        CalculationCache,
        BattleSkillSlot,
        BattleElfState,
        Battle,
    )

    def __init__(self, db: Session) -> None:
        self.db = db

    def plan_battle_purge(self, battle_id: str) -> BattlePurgePlanOut:
        """生成单场战斗的物理删除预览，不修改数据库。"""
        battle = self.db.get(Battle, battle_id)
        if battle is None:
            raise LookupError(f"战斗不存在：{battle_id}")
        can_purge, reason = self._can_purge_battle(battle)
        return BattlePurgePlanOut(
            battle_id=battle.battle_id,
            battle_name=battle.battle_name,
            phase=battle.phase,
            can_purge=can_purge,
            reason=reason,
            rows=self._count_related_rows(battle.battle_id),
        )

    def purge_battle(self, battle_id: str, *, dry_run: bool = True) -> BattlePurgeResultOut:
        """物理删除单场已归档或软删除战斗。"""
        battle = self.db.get(Battle, battle_id)
        if battle is None:
            raise LookupError(f"战斗不存在：{battle_id}")
        can_purge, reason = self._can_purge_battle(battle)
        if not can_purge:
            raise ValueError(reason or "当前战斗状态不允许物理删除")

        rows = self._count_related_rows(battle_id)
        if not dry_run:
            self._delete_battle_rows(battle_id)
            self.db.commit()
        return BattlePurgeResultOut(
            dry_run=dry_run,
            battle_count=1,
            battle_ids=[battle_id],
            rows=rows,
            message=(
                "dry-run 预览完成，未删除任何数据。" if dry_run else "战斗及关联数据已物理删除。"
            ),
        )

    def purge_archived_battles(
        self,
        *,
        older_than_days: int | None = None,
        dry_run: bool = True,
        limit: int | None = None,
    ) -> BattlePurgeResultOut:
        """批量物理删除 archived 战斗。

        Args:
            older_than_days: 只清理归档/更新时间早于 N 天的战斗；为空表示不按时间过滤。
            dry_run: 为 True 时只返回预览，不写数据库。
            limit: 最多清理多少场，用于避免误操作一次删除过多。
        """
        battle_ids = self._find_archived_battle_ids(older_than_days=older_than_days, limit=limit)
        rows = self._sum_related_rows(battle_ids)
        if not dry_run:
            for battle_id in battle_ids:
                self._delete_battle_rows(battle_id)
            self.db.commit()
        return BattlePurgeResultOut(
            dry_run=dry_run,
            battle_count=len(battle_ids),
            battle_ids=battle_ids,
            rows=rows,
            message=(
                "dry-run 预览完成，未删除任何数据。" if dry_run else "归档战斗及关联数据已物理删除。"
            ),
        )

    def _find_archived_battle_ids(
        self,
        *,
        older_than_days: int | None,
        limit: int | None,
    ) -> list[str]:
        """查询符合批量清理条件的 archived 战斗 ID。"""
        stmt = select(Battle.battle_id).where(
            Battle.phase == BattlePhase.ARCHIVED.value,
            Battle.deleted_at.is_(None),
        )
        if older_than_days is not None and older_than_days > 0:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            stmt = stmt.where(Battle.updated_at <= cutoff)
        stmt = stmt.order_by(Battle.updated_at.asc(), Battle.created_at.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.db.scalars(stmt).all())

    @staticmethod
    def _can_purge_battle(battle: Battle) -> tuple[bool, str | None]:
        """只允许物理删除 archived 或已软删除的战斗。"""
        if battle.deleted_at is not None:
            return True, None
        if battle.phase == BattlePhase.ARCHIVED.value:
            return True, None
        return False, "只能物理删除已归档或已软删除的战斗，请先归档后再清理。"

    def _sum_related_rows(self, battle_ids: list[str]) -> dict[str, int]:
        """汇总多场战斗的关联行数。"""
        total: dict[str, int] = {model.__tablename__: 0 for model in self._PURGE_ORDER}
        for battle_id in battle_ids:
            counts = self._count_related_rows(battle_id)
            for table_name, count in counts.items():
                total[table_name] = total.get(table_name, 0) + count
        return total

    def _count_related_rows(self, battle_id: str) -> dict[str, int]:
        """统计一场战斗将被删除的各表行数。"""
        return {
            model.__tablename__: self._count_rows(model, battle_id)
            for model in self._PURGE_ORDER
        }

    def _count_rows(self, model: Any, battle_id: str) -> int:
        """统计指定模型中 battle_id 对应的行数。"""
        stmt = select(func.count()).select_from(model).where(model.battle_id == battle_id)
        return int(self.db.scalar(stmt) or 0)

    def _delete_battle_rows(self, battle_id: str) -> None:
        """按依赖顺序删除一场战斗的所有关联行。"""
        for model in self._PURGE_ORDER:
            self.db.execute(delete(model).where(model.battle_id == battle_id))
