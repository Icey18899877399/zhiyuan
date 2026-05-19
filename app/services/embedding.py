"""Embedding 客户端封装

设计目标：
- 把 provider 隐藏在一个统一的 `embed_text()` / `embed_texts()` 接口背后
- 没有 API Key 时（EMBEDDING_PROVIDER=disabled）所有方法返回 None，
  调用方据此降级到关键词检索；不要因此抛错
- 当前内置 zhipu / openai 两个 provider；后续要换本地 BGE 只需多写一个
  EmbeddingClient 子类即可
- 单条 + 批量两种调用方式；批量内部分批，避免 provider 单次上限

为什么不默认开启：在 dev / CI / 没钱买 API 的环境中也能跑通项目。
"""
from __future__ import annotations

from typing import Protocol

import httpx
from loguru import logger

from app.config import settings


class EmbeddingClient(Protocol):
    """所有 provider 客户端的共同接口"""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class _DisabledClient:
    """占位实现：无 API Key 时使用，调用方据此降级到关键词检索"""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingDisabledError("EMBEDDING_PROVIDER=disabled")


class EmbeddingDisabledError(RuntimeError):
    """embedding provider 未启用 / 不可用，由调用方决定降级策略"""


class _ZhipuClient:
    """智谱 BigModel（https://open.bigmodel.cn）

    文档：https://open.bigmodel.cn/dev/api/vector/embedding-3
    单次最多 64 条，单条最长 8192 token；服务端按字节计费。
    """

    BATCH = 32  # 略低于上限，避免边界条件

    def __init__(self) -> None:
        if not settings.zhipu_api_key:
            raise EmbeddingDisabledError(
                "EMBEDDING_PROVIDER=zhipu 但未配置 ZHIPU_API_KEY"
            )
        self._client = httpx.AsyncClient(
            base_url=settings.zhipu_base_url,
            headers={"Authorization": f"Bearer {settings.zhipu_api_key}"},
            timeout=30.0,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH):
            batch = texts[i : i + self.BATCH]
            resp = await self._client.post(
                "/embeddings",
                json={
                    "model": settings.embedding_model,
                    "input": batch,
                    "dimensions": settings.embedding_dim,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # 智谱返回结构与 openai 兼容：{ data: [{embedding, index}, ...] }
            items = sorted(data["data"], key=lambda x: x["index"])
            results.extend([item["embedding"] for item in items])
        return results

    async def aclose(self) -> None:
        await self._client.aclose()


class _OpenAIClient:
    """OpenAI text-embedding-3-small，dim 可配（1024 或 1536）"""

    BATCH = 64

    def __init__(self) -> None:
        # 复用 DEEPSEEK_API_KEY 路径上的 openai SDK 即可，但这里直接 httpx 调更轻
        from app.config import settings as _s
        if not _s.deepseek_api_key:
            # 注意：OpenAI provider 仍需 DEEPSEEK_API_KEY 等价的真 OPENAI_API_KEY
            # 简化：复用 DEEPSEEK_API_KEY env 变量，base_url 切到 OpenAI 即可
            raise EmbeddingDisabledError(
                "EMBEDDING_PROVIDER=openai 但未配置 OPENAI_API_KEY (复用 DEEPSEEK_API_KEY)"
            )
        self._client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {_s.deepseek_api_key}"},
            timeout=30.0,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH):
            batch = texts[i : i + self.BATCH]
            resp = await self._client.post(
                "/embeddings",
                json={
                    "model": settings.embedding_model,
                    "input": batch,
                    "dimensions": settings.embedding_dim,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            items = sorted(data["data"], key=lambda x: x["index"])
            results.extend([item["embedding"] for item in items])
        return results

    async def aclose(self) -> None:
        await self._client.aclose()


_singleton: EmbeddingClient | None = None


def get_client() -> EmbeddingClient:
    """按 settings.embedding_provider 选取 client；失败时返回 _DisabledClient"""
    global _singleton
    if _singleton is not None:
        return _singleton

    provider = settings.embedding_provider.lower().strip()
    try:
        if provider == "zhipu":
            _singleton = _ZhipuClient()
        elif provider == "openai":
            _singleton = _OpenAIClient()
        else:
            _singleton = _DisabledClient()
    except EmbeddingDisabledError as e:
        logger.warning(f"embedding 不可用，将走关键词检索降级：{e}")
        _singleton = _DisabledClient()

    return _singleton


def is_enabled() -> bool:
    """供调用方快速判断是否要走向量路径"""
    return not isinstance(get_client(), _DisabledClient)


async def embed_text(text: str) -> list[float] | None:
    """对单条文本编码；失败返回 None，由调用方决定降级"""
    if not text.strip():
        return None
    client = get_client()
    if isinstance(client, _DisabledClient):
        return None
    try:
        vectors = await client.embed_texts([text])
        return vectors[0] if vectors else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"embed_text 失败：{e}")
        return None


async def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """批量编码；单条失败用 None 占位（保持顺序），便于批量回填脚本一一对应"""
    if not texts:
        return []
    client = get_client()
    if isinstance(client, _DisabledClient):
        return [None] * len(texts)
    try:
        vectors = await client.embed_texts(texts)
        return list(vectors)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"embed_texts 失败：{e}")
        return [None] * len(texts)
