"""
FastAPI 应用入口

启动:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

访问:
  http://localhost:8000/         # 前端首页 (frontend/index.html)
  http://localhost:8000/docs     # Swagger 自动文档
  http://localhost:8000/redoc    # ReDoc 文档
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from loguru import logger

from app import scheduler as zhiyuan_scheduler
from app.api import articles, chat, stats
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 {settings.app_name} 启动 (env={settings.app_env})")
    if settings.scheduler_enabled:
        zhiyuan_scheduler.start()
    else:
        logger.info("调度器未启用 (SCHEDULER_ENABLED=false)，跳过定时爬取")
    yield
    if settings.scheduler_enabled:
        zhiyuan_scheduler.shutdown()
    logger.info("🛑 应用关闭")


app = FastAPI(
    title="智源 - 校园智能信息服务平台 API",
    description="为前端/小程序提供文章、检索、问答接口",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(articles.router)
app.include_router(chat.router)
app.include_router(stats.router)


@app.get("/api/health", tags=["system"])
async def health_check():
    """健康检查 - 运维/前端确认服务在线"""
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


# ─────────────────── 前端静态托管（单端口） ───────────────────
# 把 frontend/ 整体挂在根路径；index.html 作为默认入口。
# 如果 frontend/ 目录不存在（例如纯 API 部署），回退到 JSON 欢迎页。
_frontend_path = Path(settings.frontend_dir).resolve()
if _frontend_path.is_dir():
    logger.info(f"📦 挂载前端静态目录：{_frontend_path}")

    # 根路径返回首页
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(_frontend_path / "index.html")

    # 显式登记每个前端文件，避免 catch-all 吞掉 /docs /redoc /openapi.json
    def _make_static_handler(file_path: Path):
        async def _handler():
            return FileResponse(file_path)
        return _handler

    for _f in sorted(_frontend_path.iterdir()):
        if _f.is_file() and not _f.name.startswith("."):
            app.add_api_route(
                f"/{_f.name}",
                _make_static_handler(_f),
                methods=["GET"],
                include_in_schema=False,
            )
else:
    logger.warning(
        f"⚠️  前端目录不存在：{_frontend_path}，仅提供 JSON 欢迎页。"
    )

    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "message": "Welcome to 智源 API",
            "docs": "/docs",
            "redoc": "/redoc",
        }
