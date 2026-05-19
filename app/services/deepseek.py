"""DeepSeek 异步客户端封装

DeepSeek 与 OpenAI Chat Completions 协议兼容，因此直接复用 openai SDK。
"""
from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import settings


@lru_cache
def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )


async def chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> str:
    """发起一次阻塞式对话，返回纯文本回答。"""
    client = get_client()
    resp = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()
