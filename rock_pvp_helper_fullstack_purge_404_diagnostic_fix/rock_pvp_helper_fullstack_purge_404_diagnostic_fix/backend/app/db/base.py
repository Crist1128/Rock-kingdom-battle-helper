"""
数据库基础模块。

本模块定义 SQLAlchemy ORM 的基础类和混入类，为所有模型提供：
- 统一的元数据命名规范
- 时间戳混入类（创建时间、更新时间、软删除时间）
- UTC 时间辅助函数
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 定义 SQLAlchemy 命名规范，用于约束、索引等数据库对象的命名
# 这些规范确保数据库对象名称一致且可预测
naming_convention = {
    "ix": "ix_%(column_0_label)s",  # 索引命名：ix_列名
    "uq": "uq_%(table_name)s_%(column_0_name)s",  # 唯一约束：uq_表名_列名
    "ck": "ck_%(table_name)s_%(constraint_name)s",  # 检查约束：ck_表名_约束名
    # 外键：fk_表名_列名_引用表名
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",  # 主键：pk_表名
}


def utc_now() -> datetime:
    """
    获取当前 UTC 时间。

    Returns:
        datetime: 带 UTC 时区信息的当前时间
    """
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """
    SQLAlchemy 声明式基类。

    所有 ORM 模型都继承此类，使用统一的元数据和命名规范。

    Attributes:
        metadata: SQLAlchemy MetaData 实例，包含命名规范配置
    """
    metadata = MetaData(naming_convention=naming_convention)


class TimestampMixin:
    """
    时间戳混入类。

    为模型添加标准的审计字段：创建时间、更新时间、软删除时间。
    通过继承此类，模型自动获得这些字段，无需重复定义。

    Attributes:
        created_at: 记录创建时间，插入时自动设置
        updated_at: 记录最后更新时间，更新时自动刷新
        deleted_at: 软删除时间，为 None 表示未删除
    """
    # 记录创建时间，插入数据时自动设置为当前 UTC 时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False
    )

    # 记录最后更新时间，每次更新时自动刷新为当前 UTC 时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False
    )

    # 软删除时间戳，用于实现软删除功能
    # 为 None 表示记录未删除，有值表示已被软删除
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
