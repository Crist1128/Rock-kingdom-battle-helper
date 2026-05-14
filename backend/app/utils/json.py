"""
JSON 与 ORM 辅助工具。

项目中大量复杂规则字段以 JSON 字符串落库。这里集中提供序列化、
反序列化和 ORM 对象转字典工具，保持各服务层编码风格一致。
"""

import json
from typing import Any

from pydantic import BaseModel


def dumps_json(value: Any) -> str:
    """
    将 Python 对象序列化为 UTF-8 JSON 字符串。

    说明：
    - Pydantic 模型会先转换为 dict。
    - datetime 等非 JSON 原生类型使用 str 兜底，保证快照可落库。
    - ensure_ascii=False 便于直接阅读中文内容。
    """
    if isinstance(value, BaseModel):
        value = value.model_dump()
    return json.dumps(value, ensure_ascii=False, default=str)


def loads_json(value: str | None, default: Any = None) -> Any:
    """
    安全读取 JSON 字符串。

    Args:
        value: 数据库中的 JSON 字符串，可为空。
        default: 空值或解析失败时返回的默认值。

    Returns:
        Any: 解析后的 Python 对象。
    """
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def model_to_dict(model: object) -> dict[str, Any]:
    """
    将 SQLAlchemy ORM 模型转换为普通字典。

    本函数只读取模型声明的列，不会触发关系属性加载，适合 API 响应、
    快照和调试日志使用。
    """
    return {
        column.name: getattr(model, column.name)
        for column in model.__table__.columns  # type: ignore[attr-defined]
    }
