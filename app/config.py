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

    # RAG
    chat_top_k: int = 5

    # CORS：逗号分隔；"*" 表示允许全部
    cors_origins: str = "*"

    # 前端静态目录（FastAPI 单端口托管）；为空则不挂载
    frontend_dir: str = "frontend"

    # 微信
    wechat_appid: str = ""
    wechat_secret: str = ""

    # 爬虫
    wechat_mp_cookie: str = ""
    wechat_mp_token: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if not raw or raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """单例配置对象"""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
