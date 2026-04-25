"""
应用配置
统一从 .env 读取，避免硬编码。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用
    app_name: str = "zhiyuan-backend"
    app_env: str = "development"
    log_level: str = "INFO"

    # 数据库
    database_url: str
    database_url_sync: str

    # LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 微信
    wechat_appid: str = ""
    wechat_secret: str = ""

    # 爬虫
    wechat_mp_cookie: str = ""
    wechat_mp_token: str = ""


@lru_cache
def get_settings() -> Settings:
    """单例配置对象"""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
