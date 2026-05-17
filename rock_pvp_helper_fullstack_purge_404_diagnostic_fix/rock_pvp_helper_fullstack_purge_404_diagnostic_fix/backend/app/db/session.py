"""
数据库会话管理模块。

本模块负责 SQLAlchemy 引擎和会话的创建与配置，包括：
- 数据库引擎创建和配置
- SQLite PRAGMA 设置（外键、WAL 模式等）
- 会话工厂和依赖注入函数
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# 创建 SQLAlchemy 引擎
# - SQLite 需要 check_same_thread=False 以允许多线程访问
# - future=True 启用 SQLAlchemy 2.0 行为
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    future=True,
)

# 创建会话工厂
# - autoflush=False: 不自动刷新，需要手动控制
# - autocommit=False: 不自动提交，需要显式调用 commit
# - future=True: 使用 SQLAlchemy 2.0 行为
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
    """
    SQLite 连接时自动执行的 PRAGMA 设置。

    当建立新的数据库连接时，自动配置 SQLite 的推荐设置：
    - foreign_keys=ON: 启用外键约束检查
    - journal_mode=WAL: 使用 WAL 模式，提高并发性能
    - synchronous=NORMAL: 降低同步开销，平衡性能和安全性
    - busy_timeout=5000: 设置忙等待超时为 5 秒

    Args:
        dbapi_connection: 底层数据库连接对象
        connection_record: 连接记录（SQLAlchemy 内部使用）
    """
    # SQLite 本地应用推荐配置：外键、WAL、降低同步开销、避免短锁失败。
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")  # 启用外键约束
        cursor.execute("PRAGMA journal_mode=WAL")  # 启用 WAL 模式
        cursor.execute("PRAGMA synchronous=NORMAL")  # 设置同步模式
        cursor.execute("PRAGMA busy_timeout=5000")  # 设置忙等待超时 5 秒
    finally:
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话的依赖注入函数。

    用于 FastAPI 的 Depends 依赖注入，确保每个请求都有独立的会话，
    并在请求结束时正确关闭会话。

    Yields:
        Session: SQLAlchemy 数据库会话

    Example:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db  # 提供会话给请求处理
    finally:
        db.close()  # 确保会话被关闭，释放连接
