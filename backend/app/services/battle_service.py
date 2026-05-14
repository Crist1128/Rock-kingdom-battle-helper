"""
战斗服务模块。

本模块提供战斗相关的业务逻辑服务，包括：
- 创建战斗
- 获取战斗状态
- 创建战斗事件

服务层负责协调多个数据模型的操作，实现业务规则，
为 API 层提供高层次的业务接口。
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.battle import Battle, BattleElfState
from app.models.effect import BattleEffectInstance
from app.models.event import BattleEvent
from app.schemas.battle import BattleCreate, BattleStateOut
from app.schemas.event import BattleEventCreate


class BattleService:
    """
    战斗业务服务类。

    封装战斗相关的业务逻辑，为 API 层提供服务接口。
    每个实例绑定一个数据库会话，确保操作的一致性。

    Attributes:
        db: SQLAlchemy 数据库会话

    Example:
        service = BattleService(db)
        battle = service.create_battle(payload)
    """

    def __init__(self, db: Session) -> None:
        """
        初始化战斗服务。

        Args:
            db: SQLAlchemy 数据库会话
        """
        self.db = db

    def create_battle(self, payload: BattleCreate) -> Battle:
        """
        创建新战斗。

        创建一场新的战斗，初始状态为 preparation（准备阶段）。
        自动生成唯一的 battle_id。

        Args:
            payload: 战斗创建参数，包含 battle_name 和 notes

        Returns:
            Battle: 新创建的战斗对象
        """
        # 创建战斗实例，使用 uuid 生成唯一标识
        battle = Battle(
            battle_id=f"battle_{uuid4().hex}",  # 生成唯一战斗 ID
            battle_name=payload.battle_name,
            notes=payload.notes,
            phase="preparation",  # 初始阶段为准备阶段
            turn_number=0,  # 初始回合为 0
        )
        self.db.add(battle)
        self.db.commit()
        self.db.refresh(battle)
        return battle

    def get_state(self, battle: Battle) -> BattleStateOut:
        """
        获取战斗完整状态。

        查询战斗的完整状态，包括：
        - 战斗基本信息
        - 所有参战精灵的状态
        - 当前生效的状态效果

        Args:
            battle: 战斗对象

        Returns:
            BattleStateOut: 战斗完整状态响应对象
        """
        # 查询所有参战精灵状态
        elves = self.db.scalars(
            select(BattleElfState).where(BattleElfState.battle_id == battle.battle_id)
        ).all()

        # 查询所有生效的状态效果
        effects = self.db.scalars(
            select(BattleEffectInstance).where(
                BattleEffectInstance.battle_id == battle.battle_id,
                BattleEffectInstance.is_active.is_(True),
            )
        ).all()

        # 构建响应对象
        return BattleStateOut(
            battle=battle,
            elves=[self._model_to_dict(item) for item in elves],
            active_effects=[self._model_to_dict(item) for item in effects],
            latest_snapshot_id=battle.current_snapshot_id,
        )

    def create_event(self, battle_id: str, payload: BattleEventCreate) -> BattleEvent:
        """
        创建战斗事件。

        为指定战斗创建一个新的事件记录。
        自动生成唯一的 event_id。

        Args:
            battle_id: 战斗 ID
            payload: 事件创建参数

        Returns:
            BattleEvent: 新创建的事件对象
        """
        # 创建事件实例
        event = BattleEvent(
            event_id=f"event_{uuid4().hex}",  # 生成唯一事件 ID
            battle_id=battle_id,
            turn_number=payload.turn_number,
            event_type=payload.event_type,
            actor_side=payload.actor_side,
            actor_elf_id=payload.actor_elf_id,
            target_side=payload.target_side,
            target_elf_id=payload.target_elf_id,
            skill_id=payload.skill_id,
            skill_confirmed=payload.skill_confirmed,
            snapshot_id=payload.snapshot_id,
            source=payload.source,
            recognition_confidence=payload.recognition_confidence,
            manual_override=payload.manual_override,
            payload_json=payload.payload_json,
            notes=payload.notes,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    @staticmethod
    def _model_to_dict(model: object) -> dict:
        """
        将 SQLAlchemy 模型对象转换为字典。

        辅助方法，用于将 ORM 模型转换为可序列化的字典格式。

        Args:
            model: SQLAlchemy ORM 模型对象

        Returns:
            dict: 包含模型所有列数据的字典
        """
        return {column.name: getattr(model, column.name) for column in model.__table__.columns}  # type: ignore[attr-defined]
