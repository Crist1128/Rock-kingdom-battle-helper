"""
状态效果服务模块。

本模块提供状态效果的业务逻辑服务，包括：
- 查询生效状态列表
- 获取状态定义

后续将实现：
- 状态施加（apply）
- 状态移除（remove）
- 状态叠层（stack）
- 切换清除（switch_clear）
- 状态驱散（dispel）
- 状态转换（convert）
- 状态转移（transfer）
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.effect import BattleEffectInstance
from app.models.static import EffectDefinition


class BattleEffectService:
    """
    统一状态效果业务服务类。

    封装状态效果的业务逻辑，为 API 层和领域层提供服务接口。
    这是统一状态系统的核心服务，所有状态（印记、天气、异常、属性修正）
    都通过此类管理。

    Attributes:
        db: SQLAlchemy 数据库会话

    Example:
        service = BattleEffectService(db)
        effects = service.list_active_effects(battle_id)
        definition = service.get_definition(effect_id)
    """

    def __init__(self, db: Session) -> None:
        """
        初始化状态效果服务。

        Args:
            db: SQLAlchemy 数据库会话
        """
        self.db = db

    def list_active_effects(self, battle_id: str) -> list[BattleEffectInstance]:
        """
        获取战斗中所有生效的状态实例。

        查询指定战斗中当前处于生效状态（is_active=True）的所有状态实例。

        Args:
            battle_id: 战斗唯一标识符

        Returns:
            list[BattleEffectInstance]: 生效状态实例列表
        """
        # 构建查询条件：属于指定战斗且处于生效状态
        stmt = select(BattleEffectInstance).where(
            BattleEffectInstance.battle_id == battle_id,
            BattleEffectInstance.is_active.is_(True),
        )
        return list(self.db.scalars(stmt).all())

    def get_definition(self, effect_id: str) -> EffectDefinition | None:
        """
        获取状态定义。

        根据状态 ID 获取状态的静态定义信息。

        Args:
            effect_id: 状态唯一标识符

        Returns:
            EffectDefinition | None: 状态定义对象，如果不存在则返回 None
        """
        return self.db.get(EffectDefinition, effect_id)
