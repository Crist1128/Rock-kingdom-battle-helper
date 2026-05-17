"""
应用配置模块。

本模块负责管理应用的全局配置，使用 Pydantic Settings 进行配置验证和加载。
支持从环境变量文件（.env）加载配置，提供类型安全的配置访问。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 路径基准：config.py -> core -> app -> backend -> 项目根目录。
# 用代码位置而不是当前工作目录解析，避免从 backend 或项目根目录启动时路径漂移。
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _sqlite_url_from_path(path: Path) -> str:
    """把本地 SQLite 文件路径转换为 SQLAlchemy URL。"""
    return f"sqlite:///{path.resolve().as_posix()}"


def _resolve_path_from_backend(value: str) -> Path:
    """把相对路径按 backend 目录解析；绝对路径保持不变。"""
    path = Path(value)
    if path.is_absolute():
        return path
    return (BACKEND_DIR / path).resolve()


def _resolve_sqlite_database_url(value: str) -> str:
    """把 sqlite:/// 相对数据库路径稳定解析到 backend 目录基准。"""
    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value
    raw_path = value.removeprefix(prefix)
    if raw_path == ":memory:" or raw_path.startswith("/"):
        return value
    return _sqlite_url_from_path(_resolve_path_from_backend(raw_path))


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
    database_url: str = _sqlite_url_from_path(DEFAULT_DATA_DIR / "app.db")  # 默认写入项目根目录 data/app.db

    # 数据更新管理配置
    admin_update_token: str | None = None  # 配置后，数据更新接口要求 X-Admin-Token
    rocom_data_dir: str = str(DEFAULT_DATA_DIR / "rocom")  # 默认写入项目根目录 data/rocom，不应提交 Git
    rocom_auto_update_on_startup: bool = False  # 是否在后端启动时被动触发一次数据更新
    rocom_auto_update_commit: bool = False  # 启动时被动更新是否提交数据库；默认 dry-run
    rocom_auto_update_force: bool = False  # 启动时是否强制重爬
    rocom_auto_update_limit: int = 0  # 启动时调试限制；0 表示全量
    rocom_auto_update_with_images: bool = False  # MVP 默认不下载图片
    rocom_update_delay: float = 1.5  # 爬虫请求间隔下限

    # CORS 配置，默认允许前端开发服务器访问
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:5173",  # Vite 默认开发服务器地址
        "http://127.0.0.1:5173",  # 本地回环地址
    ])

    # Pydantic Settings 配置
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",  # 固定读取 backend/.env，避免受启动目录影响
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

    @model_validator(mode="after")
    def normalize_local_paths(self) -> "Settings":
        """统一解析本地运行路径。

        - SQLite 相对路径按 backend 目录解析，例如 sqlite:///../data/app.db。
        - ROCOM_DATA_DIR 相对路径也按 backend 目录解析，例如 ../data/rocom。
        """
        self.database_url = _resolve_sqlite_database_url(self.database_url)
        self.rocom_data_dir = str(_resolve_path_from_backend(self.rocom_data_dir))
        return self

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
