"""
公共 Schema 定义模块。

本模块定义 Pydantic Schema 的公共基类和工具类，供其他 schema 模块继承和使用。
包括：
- ORM 基础类（支持从 ORM 模型转换）
- 通用响应结构
- 时间戳混入类
- 分页参数
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMBase(BaseModel):
    """
    ORM 模型转换基础类。

    继承此类的 Pydantic 模型可以直接从 SQLAlchemy ORM 模型创建，
    通过 model_validate 方法自动转换。

    Example:
        class UserOut(ORMBase):
            id: int
            name: str

        # 从 ORM 模型创建
        user_orm = db.query(User).first()
        user_out = UserOut.model_validate(user_orm)
    """
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    """
    通用消息响应模型。

    用于返回简单的消息响应，如操作成功提示。

    Attributes:
        message: 响应消息内容
    """
    message: str


class TimestampFields(BaseModel):
    """
    时间戳字段混入类。

    为 Schema 添加标准的时间戳字段，与模型的 TimestampMixin 对应。

    Attributes:
        created_at: 创建时间（可选）
        updated_at: 更新时间（可选）
        deleted_at: 删除时间（可选，None 表示未删除）
    """
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


# JSON 字典类型别名，用于声明任意键值对的字典
JsonDict = dict[str, Any]


def default_list() -> list[Any]:
    """
    返回空列表的工厂函数。

    用于 Pydantic Field 的 default_factory，确保每次创建新实例时
    都获得一个新的空列表，而不是共享同一个列表对象。

    Returns:
        list[Any]: 新的空列表
    """
    return []


class PaginationParams(BaseModel):
    """
    分页参数模型。

    用于 API 端点的分页查询参数。

    Attributes:
        limit: 返回数量限制，默认 50，范围 1-500
        offset: 偏移量，默认 0
    """
    limit: int = Field(default=50, ge=1, le=500, description="返回数量限制")
    offset: int = Field(default=0, ge=0, description="偏移量")
