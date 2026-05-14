"""
应用配置模块。

本模块负责管理应用的全局配置，使用 Pydantic Settings 进行配置验证和加载。
支持从环境变量文件（.env）加载配置，提供类型安全的配置访问。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    应用配置类。

    使用 Pydantic Settings 管理应用配置，支持从环境变量和 .env 文件加载。
    所有配置项都有默认值，可在 .env 文件中覆盖。

    Attributes:
        app_name: 应用名称
        app_env: 应用环境（local, development, production）
        debug: 是否开启调试模式
        database_url: 数据库连接 URL
        cors_origins: 允许的跨域来源列表
    """

    # 应用基础配置
    app_name: str = "Rock PVP Helper API"  # 应用名称
    app_env: str = "local"  # 应用环境，默认为本地环境
    debug: bool = True  # 调试模式开关，默认开启

    # 数据库配置
    database_url: str = "sqlite:///../data/app.db"  # SQLite 数据库文件路径

    # CORS 配置，默认允许前端开发服务器访问
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:5173",  # Vite 默认开发服务器地址
        "http://127.0.0.1:5173",  # 本地回环地址
    ])

    # Pydantic Settings 配置
    model_config = SettingsConfigDict(
        env_file=".env",  # 环境变量文件路径
        env_file_encoding="utf-8",  # 文件编码
        extra="ignore",  # 忽略未定义的配置项
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        """
        解析 CORS 来源配置。

        支持两种格式：
        1. 字符串格式：逗号分隔的 URL 列表（如 "http://a.com,http://b.com"）
        2. 列表格式：直接的字符串列表

        Args:
            value: 原始配置值，可能是字符串或列表

        Returns:
            list[str]: 解析后的 URL 列表
        """
        if isinstance(value, str):
            # 如果是字符串，按逗号分割并去除空白
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def sqlite_file_path(self) -> Path | None:
        """
        获取 SQLite 数据库文件的本地路径。

        从 database_url 中解析出文件路径，用于确保目录存在等操作。

        Returns:
            Path | None: 数据库文件路径，如果不是 SQLite 或路径无效则返回 None
        """
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        return Path(self.database_url.removeprefix(prefix)).resolve()


@lru_cache
def get_settings() -> Settings:
    """
    获取 Settings 实例（带缓存）。

    使用 lru_cache 装饰器缓存配置实例，避免重复读取和解析。

    Returns:
        Settings: 应用配置实例
    """
    return Settings()


# 全局配置实例，供其他模块直接导入使用
settings = get_settings()
