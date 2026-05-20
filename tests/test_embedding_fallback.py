"""embedding 服务在无 key 环境下应静默降级，不能抛错。"""
from __future__ import annotations

import pytest

from app.services import embedding as emb


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    """每个测试前重置 singleton，避免相互污染"""
    monkeypatch.setattr(emb, "_singleton", None)
    yield
    monkeypatch.setattr(emb, "_singleton", None)


class TestDisabledProvider:
    def test_disabled_provider_means_is_enabled_false(self, monkeypatch) -> None:
        monkeypatch.setattr(emb.settings, "embedding_provider", "disabled")
        assert emb.is_enabled() is False

    async def test_embed_text_returns_none_when_disabled(self, monkeypatch) -> None:
        monkeypatch.setattr(emb.settings, "embedding_provider", "disabled")
        result = await emb.embed_text("辅修招生通知")
        assert result is None

    async def test_embed_texts_returns_none_list_when_disabled(self, monkeypatch) -> None:
        monkeypatch.setattr(emb.settings, "embedding_provider", "disabled")
        result = await emb.embed_texts(["一", "二", "三"])
        assert result == [None, None, None]

    async def test_embed_text_empty_returns_none(self, monkeypatch) -> None:
        monkeypatch.setattr(emb.settings, "embedding_provider", "disabled")
        result = await emb.embed_text("   ")
        assert result is None


class TestZhipuProviderWithoutKey:
    def test_zhipu_without_key_falls_back_to_disabled(self, monkeypatch) -> None:
        monkeypatch.setattr(emb.settings, "embedding_provider", "zhipu")
        monkeypatch.setattr(emb.settings, "zhipu_api_key", "")
        # 不应抛错，应静默退化为 Disabled
        assert emb.is_enabled() is False
