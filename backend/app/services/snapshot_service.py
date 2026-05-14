"""
状态快照服务模块。

本模块提供状态快照的业务逻辑服务，包括：
- 创建状态快照

状态快照用于记录事件发生瞬间的所有状态信息，是以下功能的基础：
- 伤害计算（基于事件发生时的状态）
- 候选配置过滤（基于事件发生时的面板属性）
- 事件回放（重现事件发生时的场景）
- 纠错重算（从特定时间点重新计算）
"""

import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.effect import BattleEffectSnapshot
from app.services.effect_service import BattleEffectService


class SnapshotService:
    """
    状态快照业务服务类。

    封装状态快照的创建和管理逻辑。
    第一阶段快照直接保存实例 ID 列表和完整状态数据 JSON。

    Attributes:
        db: SQLAlchemy 数据库会话

    Example:
        service = SnapshotService(db)
        snapshot = service.create_effect_snapshot(battle_id, turn_number)
    """

    def __init__(self, db: Session) -> None:
        """
        初始化快照服务。

        Args:
            db: SQLAlchemy 数据库会话
        """
        self.db = db

    def create_effect_snapshot(
        self,
        battle_id: str,
        turn_number: int,
        source_event_id: str | None = None,
    ) -> BattleEffectSnapshot:
        """
        创建状态快照。

        记录指定战斗在指定回合的所有生效状态信息。
        快照包含：
        - 生效状态实例 ID 列表（便于快速查询）
        - 完整状态数据（JSON 格式，包含所有详情）

        Args:
            battle_id: 战斗唯一标识符
            turn_number: 当前回合数
            source_event_id: 触发此快照的事件 ID（可选）

        Returns:
            BattleEffectSnapshot: 新创建的快照对象
        """
        # 查询当前所有生效的状态效果
        effects = BattleEffectService(self.db).list_active_effects(battle_id)

        # 提取状态实例 ID 列表
        active_ids = [item.instance_id for item in effects]

        # 创建快照实例
        snapshot = BattleEffectSnapshot(
            snapshot_id=f"snapshot_{uuid4().hex}",  # 生成唯一快照 ID
            battle_id=battle_id,
            turn_number=turn_number,
            active_effect_instance_ids_json=json.dumps(active_ids, ensure_ascii=False),
            full_snapshot_json=json.dumps(
                [self._model_to_dict(item) for item in effects], ensure_ascii=False, default=str
            ),
            source_event_id=source_event_id,
        )
        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    @staticmethod
    def _model_to_dict(model: object) -> dict:
        """
        将 SQLAlchemy 模型对象转换为字典。

        辅助方法，用于将 ORM 模型转换为可序列化的字典格式。
        默认使用 str 转换器处理无法序列化的类型（如 datetime）。

        Args:
            model: SQLAlchemy ORM 模型对象

        Returns:
            dict: 包含模型所有列数据的字典
        """
        return {column.name: getattr(model, column.name) for column in model.__table__.columns}  # type: ignore[attr-defined]
