"""
数据库初始化模块。

本模块提供数据库初始化功能，包括：
- 创建数据库文件目录（如果不存在）
- 通过 Alembic 创建或迁移所有定义的数据表
- 拒绝自动处理已有业务表但缺少迁移版本的异常库，避免误判结构

可作为独立脚本运行，也可作为应用启动流程的一部分调用。
"""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core.config import BACKEND_DIR, settings


def ensure_database_schema_current() -> None:
    """确保数据库结构已迁移到 Alembic 最新版本。

    该函数用于后端启动前置检查：如果默认 SQLite 文件不存在或是空库，直接执行
    ``alembic upgrade head`` 自动建表；如果已有 ``alembic_version``，也会继续补齐未执行
    的迁移。这样新电脑或空库不会在核心规则自检时因为缺表而启动失败。

    对于“已有业务表但没有 alembic_version”的历史/异常库，不自动猜测版本，避免把不明
    结构误当成最新库处理。
    """
    sqlite_path = settings.sqlite_file_path
    if sqlite_path is not None:
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    connect_args = (
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    )
    db_engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
    try:
        inspector = inspect(db_engine)
        table_names = set(inspector.get_table_names())
    finally:
        db_engine.dispose()

    has_version_table = "alembic_version" in table_names
    if not has_version_table and table_names:
        raise RuntimeError(
            "数据库已有表但缺少 alembic_version，无法安全自动迁移；"
            "请先备份数据库，并手动确认迁移版本或重建空库。"
        )

    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(alembic_config, "head")


def init_db() -> None:
    """
    初始化数据库。

n    执行以下操作：
    1. 如果配置的是 SQLite 数据库，确保数据库文件所在目录存在
    2. 使用 Alembic 迁移到最新数据库结构

    注意：此函数不会删除已有数据，仅创建不存在的表。
    保留该入口是为了兼容现有 importer/service 调用，实际建表统一由 Alembic 负责。
    """
    ensure_database_schema_current()


# 当作为独立脚本运行时，执行数据库初始化
if __name__ == "__main__":
    init_db()
