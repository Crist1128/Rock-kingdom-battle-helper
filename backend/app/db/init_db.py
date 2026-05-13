from pathlib import Path

from app.core.config import settings
from app.db.base import Base
from app.db.session import engine

# 导入模型，确保 Base.metadata 收集所有表。
from app.models import battle, candidate, effect, event, static  # noqa: F401


def init_db() -> None:
    sqlite_path = settings.sqlite_file_path
    if sqlite_path is not None:
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
