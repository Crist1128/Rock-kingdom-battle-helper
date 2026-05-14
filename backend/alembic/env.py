"""
Alembic 环境配置模块。

本模块配置 Alembic 数据库迁移环境，包括：
- 数据库连接配置
- 目标元数据定义
- 迁移执行函数（在线和离线模式）

Alembic 是 SQLAlchemy 的数据库迁移工具，用于管理数据库模式的版本控制。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base
from app.models import *  # noqa: F403,F401 - 导入所有模型确保元数据完整

# 获取 Alembic 配置对象
config = context.config

# 从应用配置设置数据库连接 URL
config.set_main_option("sqlalchemy.url", settings.database_url)

# 如果有配置文件，加载日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置目标元数据，用于 Alembic 检测模型变化
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    以离线模式运行迁移。

    离线模式不使用实际的数据库连接，而是生成 SQL 脚本。
    适用于在无法直接连接数据库的环境中执行迁移（如 CI/CD）。

    生成的 SQL 可以直接在数据库客户端中执行。
    """
    # 从配置获取数据库 URL
    url = config.get_main_option("sqlalchemy.url")

    # 配置 Alembic 上下文
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,  # 使用字面量绑定参数
        dialect_opts={"paramstyle": "named"},  # 使用命名参数风格
    )

    # 执行迁移
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    以在线模式运行迁移。

    在线模式使用实际的数据库连接执行迁移。
    这是默认的迁移执行方式，直接在数据库上应用变更。
    """
    # 从配置创建数据库引擎
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # 不使用连接池
    )

    # 使用连接执行迁移
    with connectable.connect() as connection:
        # 配置 Alembic 上下文
        context.configure(connection=connection, target_metadata=target_metadata)

        # 在事务中执行迁移
        with context.begin_transaction():
            context.run_migrations()


# 根据运行模式选择执行方式
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
