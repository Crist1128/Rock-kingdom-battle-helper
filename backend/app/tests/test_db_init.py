"""数据库启动初始化测试。"""

import sqlite3

from app.core.config import settings
from app.db.init_db import ensure_database_schema_current


def test_ensure_database_schema_current_creates_empty_sqlite_db(tmp_path) -> None:
    """空 SQLite 库应能在后端启动前自动执行 Alembic 建表。"""
    original_database_url = settings.database_url
    db_path = tmp_path / "empty_app.db"
    settings.database_url = f"sqlite:///{db_path.as_posix()}"
    try:
        ensure_database_schema_current()

        connection = sqlite3.connect(db_path)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "select name from sqlite_master where type='table'"
                ).fetchall()
            }
            version = connection.execute("select version_num from alembic_version").fetchone()[0]
        finally:
            connection.close()
    finally:
        settings.database_url = original_database_url

    assert "nature_definition" in tables
    assert "skill_definition" in tables
    assert "elf_evolution_chain" in tables
    assert "elf_evolution_stage" in tables
    assert version == "0009_elf_evolution_chains"


def test_ensure_database_schema_current_rejects_unversioned_non_empty_db(tmp_path) -> None:
    """已有表但缺迁移版本的异常库不能静默当作最新库。"""
    original_database_url = settings.database_url
    db_path = tmp_path / "partial_app.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("create table legacy_table (id integer primary key)")
        connection.commit()
    finally:
        connection.close()

    settings.database_url = f"sqlite:///{db_path.as_posix()}"
    try:
        try:
            ensure_database_schema_current()
        except RuntimeError as exc:
            assert "缺少 alembic_version" in str(exc)
        else:
            raise AssertionError("应拒绝已有表但无 alembic_version 的异常库")
    finally:
        settings.database_url = original_database_url
