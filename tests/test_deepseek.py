"""大模型客户端配置测试。"""
from __future__ import annotations

import asyncio

import pytest

from app.services import deepseek


def test_client_uses_configured_request_timeout(monkeypatch) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    def fake_client(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(deepseek, "AsyncOpenAI", fake_client)
    monkeypatch.setattr(deepseek.settings, "llm_timeout_seconds", 12.5)
    deepseek.get_client.cache_clear()
    try:
        deepseek.get_client()
    finally:
        deepseek.get_client.cache_clear()

    assert captured["timeout"] == 12.5


@pytest.mark.asyncio
async def test_chat_completion_enforces_total_timeout(monkeypatch) -> None:  # noqa: ANN001
    class SlowCompletions:
        async def create(self, **kwargs):  # noqa: ANN003
            await asyncio.sleep(1)

    client = type(
        "FakeClient",
        (),
        {"chat": type("FakeChat", (), {"completions": SlowCompletions()})()},
    )()
    monkeypatch.setattr(deepseek, "get_client", lambda: client)
    monkeypatch.setattr(deepseek.settings, "llm_timeout_seconds", 0.01)

    with pytest.raises(TimeoutError):
        await deepseek.chat_completion(
            system_prompt="test",
            user_prompt="test",
        )
