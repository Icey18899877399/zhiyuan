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

    # 向量检索（M2）
    # 1024 维向量；与 zhipuai embedding-3 / openai text-embedding-3-small (dim=1024) 对齐
    embedding_dim: int = 1024
    # 调用哪个 provider 算 embedding：zhipu / openai / disabled
    # disabled 时 retrieval.py 自动降级到关键词检索，便于无 key 环境本地跑
    embedding_provider: str = "disabled"
    embedding_model: str = "embedding-3"
    # 智谱 BigModel API（https://open.bigmodel.cn）
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    # 时间衰减系数：score = cos_sim * exp(-lambda * age_days)
    # 0.05 ≈ 14 天半衰期；0.10 ≈ 7 天半衰期
    time_decay_lambda: float = 0.05

    # 调度器（M1）
    # 关闭后 uvicorn 启动不会触发自动爬取，便于本地开发
    scheduler_enabled: bool = True

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
