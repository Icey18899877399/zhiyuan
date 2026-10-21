"""健康检查接口测试。"""
from __future__ import annotations

import pytest

from app import main


@pytest.mark.asyncio
async def test_health_reports_database_unavailable_without_exposing_llm_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingConnection:
        async def __aenter__(self):
            raise ConnectionError("PostgreSQL unavailable")

        async def __aexit__(self, *args):  # noqa: ANN002
            return False

    class FailingEngine:
        def connect(self):
            return FailingConnection()

    monkeypatch.setattr(main, "engine", FailingEngine())
    monkeypatch.setattr(main.settings, "deepseek_api_key", "secret-test-key")
    monkeypatch.setattr(main.settings, "llm_fallback_enabled", True)

    result = await main.health_check()

    assert result["status"] == "degraded"
    assert result["dependencies"] == {
        "database": "unavailable",
        "llm": "configured",
    }
    assert result["llm_fallback_enabled"] is True
    assert "secret-test-key" not in str(result)
