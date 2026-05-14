"""
数据库初始化模块。

本模块提供数据库初始化功能，包括：
- 创建数据库文件目录（如果不存在）
- 创建所有定义的数据表
- 导入模型以确保元数据包含所有表

可作为独立脚本运行，也可作为应用启动流程的一部分调用。
"""

from pathlib import Path

from app.core.config import settings
from app.db.base import Base
from app.db.session import engine

# 导入模型，确保 Base.metadata 收集所有表。
# noqa: F401 表示忽略未使用的导入警告，这些导入是为了注册模型到 Base.metadata
from app.models import battle, candidate, effect, event, static  # noqa: F401


def init_db() -> None:
    """
    初始化数据库。

n    执行以下操作：
    1. 如果配置的是 SQLite 数据库，确保数据库文件所在目录存在
    2. 使用 Base.metadata.create_all 创建所有定义的数据表

    注意：此函数不会删除已有数据，仅创建不存在的表。
    如需数据迁移，请使用 Alembic。
    """
    # 对于 SQLite，确保数据库文件所在目录存在
    sqlite_path = settings.sqlite_file_path
    if sqlite_path is not None:
        # parents=True 创建所有必要的父目录
        # exist_ok=True 如果目录已存在则不报错
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    # 创建所有表
    # bind=engine 指定使用的数据库引擎
    Base.metadata.create_all(bind=engine)


# 当作为独立脚本运行时，执行数据库初始化
if __name__ == "__main__":
    init_db()
