"""
FastAPI 应用入口

启动:
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

访问:
  http://localhost:8000/docs    # Swagger 自动文档(给前端看)
  http://localhost:8000/redoc   # ReDoc 文档
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api import articles
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    logger.info(f"🚀 {settings.app_name} 启动 (env={settings.app_env})")
    yield
    # 关闭时
    logger.info("🛑 应用关闭")


app = FastAPI(
    title="智源 - 校园智能信息服务平台 API",
    description="为前端/小程序提供文章、检索、问答接口",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发期允许所有,上线前改成具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(articles.router)


@app.get("/api/health", tags=["system"])
async def health_check():
    """健康检查 - 运维/前端确认服务在线"""
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/", include_in_schema=False)
async def root():
    """根路径 - 引导到文档"""
    return {
        "message": "Welcome to 智源 API",
        "docs": "/docs",
        "redoc": "/redoc",
    }