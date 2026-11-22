from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，优先读取环境变量及 backend/.env 文件。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # 基础应用配置
    APP_NAME: str = "AILOVE API"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # 安全与 JWT 配置（默认 24 小时自动过期，支持多点登录与防爆破锁定）
    JWT_SECRET_KEY: str = "dev-only-secret-key-please-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 小时
    MAX_SESSIONS_PER_USER: int = 5  # 单账号最多同时在线设备数
    LOGIN_MAX_FAIL_ATTEMPTS: int = 5  # 连续登录失败锁定阈值
    LOGIN_LOCK_MINUTES: int = 15  # 触发防爆破锁定时长（分钟）

    # 初始化管理员配置
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "Admin123456"
    ALLOW_DEV_FALLBACK_AUTH: bool = True

    # MySQL 配置
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "ailove"
    MYSQL_PASSWORD: str = "ailove_123456"
    MYSQL_DATABASE: str = "ailove"
    MYSQL_POOL_SIZE: int = 10
    MYSQL_MAX_OVERFLOW: int = 20

    # Redis 配置
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # LangChain / LLM 默认回退配置（首期默认 DeepSeek，生产推荐在管理后台动态配置并加密落库）
    LLM_PROVIDER: str = "deepseek"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-flash"
    LLM_TEMPERATURE: float = 0.7
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_SYSTEM_PROMPT: str = "你是 AILOVE 智能助手，请用清晰、温暖、专业的中文回答用户问题。"

    # 微信小程序配置
    WECHAT_APP_ID: str = ""
    WECHAT_APP_SECRET: str = ""

    @property
    def mysql_dsn(self) -> str:
        user = quote_plus(self.MYSQL_USER)
        password = quote_plus(self.MYSQL_PASSWORD)
        return (
            f"mysql+aiomysql://{user}:{password}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            pwd = quote_plus(self.REDIS_PASSWORD)
            return f"redis://:{pwd}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def is_llm_configured(self) -> bool:
        return bool(self.LLM_API_KEY.strip())

    @property
    def is_wechat_configured(self) -> bool:
        return bool(self.WECHAT_APP_ID.strip() and self.WECHAT_APP_SECRET.strip())

    @property
    def is_development(self) -> bool:
        return self.APP_ENV.lower() in {"dev", "development", "local"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
