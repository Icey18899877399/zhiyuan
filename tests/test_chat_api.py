"""聊天 HTTP 接口的路由与响应契约测试。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app import main
from app.api import chat as chat_api
from app.database import get_db
from app.services import intent as intent_service
from app.services.retrieval import RetrievedArticle


class FakeSession:
    def add(self, value: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def fake_database():
    async def override_get_db():
        yield FakeSession()

    main.app.dependency_overrides[get_db] = override_get_db
    yield
    main.app.dependency_overrides.pop(get_db, None)


def _article(category: str) -> RetrievedArticle:
    article_id = 1 if category == "学业" else 2
    return RetrievedArticle(
        id=article_id,
        title=f"{category}通知",
        source="测试来源",
        source_url=f"https://example.com/{article_id}",
        category=category,
        snippet="测试摘要",
    )


@pytest.mark.asyncio
async def test_chat_api_returns_compound_auto_route_contract(
    monkeypatch: pytest.MonkeyPatch,
    fake_database: None,
) -> None:
    monkeypatch.setattr(chat_api.settings, "deepseek_api_key", "test-key")

    async def fake_search(db, question, *, category, top_k):  # noqa: ANN001
        return [_article(category)]

    async def fake_completion(*, system_prompt, user_prompt, **kwargs):  # noqa: ANN003
        if "编排器" in system_prompt:
            return "毕业与就业的综合回答。"
        if "学业专家" in system_prompt:
            return "学业回答。"
        return "就业回答。"

    monkeypatch.setattr(chat_api, "search_articles", fake_search)
    monkeypatch.setattr(chat_api, "chat_completion", fake_completion)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "question": "毕业和就业有哪些通知？",
                "route_mode": "auto",
                "agent": None,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["answer"] == "毕业与就业的综合回答。"
    assert payload["intent"] == "学业、就业"
    assert payload["intents"] == ["学业", "就业"]
    assert payload["route_source"] == "rules"
    assert payload["experts"] == ["academic", "career"]
    assert payload["confidence"] > 0
    assert [item["category"] for item in payload["retrieved"]] == ["学业", "就业"]
    assert [item["citations"] for item in payload["retrieved"]] == [
        ["[学业-1]"],
        ["[就业-1]"],
    ]


@pytest.mark.asyncio
async def test_chat_api_manual_route_uses_selected_agent(
    monkeypatch: pytest.MonkeyPatch,
    fake_database: None,
) -> None:
    monkeypatch.setattr(chat_api.settings, "deepseek_api_key", "test-key")
    searched_categories: list[str | None] = []

    async def fake_search(db, question, *, category, top_k):  # noqa: ANN001
        searched_categories.append(category)
        return [_article(category)]

    async def fake_completion(*, system_prompt, user_prompt, **kwargs):  # noqa: ANN003
        return "手动选择的学业回答。"

    monkeypatch.setattr(chat_api, "search_articles", fake_search)
    monkeypatch.setattr(chat_api, "chat_completion", fake_completion)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "question": "毕业和就业有哪些通知？",
                "route_mode": "manual",
                "agent": "学业",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert searched_categories == ["学业"]
    assert payload["intent"] == "学业"
    assert payload["intents"] == ["学业"]
    assert payload["route_source"] == "manual"
    assert payload["experts"] == ["academic"]
    assert [item["category"] for item in payload["retrieved"]] == ["学业"]


@pytest.mark.asyncio
async def test_chat_api_reports_llm_intent_source(
    monkeypatch: pytest.MonkeyPatch,
    fake_database: None,
) -> None:
    monkeypatch.setattr(chat_api.settings, "deepseek_api_key", "test-key")

    async def fake_search(db, question, *, category, top_k):  # noqa: ANN001
        assert category == "活动"
        return [_article(category)]

    async def fake_completion(*, system_prompt, user_prompt, **kwargs):  # noqa: ANN003
        if "意图分类器" in system_prompt:
            return '{"categories":["活动"],"confidence":0.88}'
        return "活动安排的回答。"

    monkeypatch.setattr(chat_api, "search_articles", fake_search)
    monkeypatch.setattr(chat_api, "chat_completion", fake_completion)
    monkeypatch.setattr(intent_service, "chat_completion", fake_completion)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"question": "学院最近有什么安排？", "route_mode": "auto"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intents"] == ["活动"]
    assert payload["route_source"] == "llm"
    assert payload["confidence"] == 0.88


@pytest.mark.asyncio
async def test_chat_api_reports_intent_classifier_fallback_to_keyword_route(
    monkeypatch: pytest.MonkeyPatch,
    fake_database: None,
) -> None:
    monkeypatch.setattr(chat_api.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(chat_api.settings, "intent_confidence_threshold", 0.9)

    async def fake_search(db, question, *, category, top_k):  # noqa: ANN001
        assert category == "活动"
        return [_article(category)]

    async def invalid_intent_completion(*, system_prompt, user_prompt, **kwargs):  # noqa: ANN003
        return "not valid JSON"

    async def fake_answer_completion(*, system_prompt, user_prompt, **kwargs):  # noqa: ANN003
        return "活动安排的回答。"

    monkeypatch.setattr(chat_api, "search_articles", fake_search)
    monkeypatch.setattr(chat_api, "chat_completion", fake_answer_completion)
    monkeypatch.setattr(intent_service, "chat_completion", invalid_intent_completion)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"question": "学院最近有什么活动？", "route_mode": "auto"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intents"] == ["活动"]
    assert payload["route_source"] == "rules"
    assert payload["warnings"] == ["大模型意图识别未能提供有效结果，已按关键词规则路由。"]


@pytest.mark.asyncio
async def test_chat_api_returns_no_context_mode_without_calling_expert(
    monkeypatch: pytest.MonkeyPatch,
    fake_database: None,
) -> None:
    monkeypatch.setattr(chat_api.settings, "deepseek_api_key", "test-key")

    async def fake_resolve_intent(*args, **kwargs):  # noqa: ANN002, ANN003
        return intent_service.IntentResult(
            category="活动",
            expert="activity",
            confidence=1.0,
            categories=("活动",),
            experts=("activity",),
        )

    async def no_results(db, question, *, category, top_k):  # noqa: ANN001
        return []

    async def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("expert call should be skipped without retrieved context")

    monkeypatch.setattr(chat_api, "resolve_intent", fake_resolve_intent)
    monkeypatch.setattr(chat_api, "search_articles", no_results)
    monkeypatch.setattr(chat_api, "chat_completion", fail_if_called)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"question": "有哪些活动？", "route_mode": "auto"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer_mode"] == "no_context"
    assert payload["retrieved"] == []
    assert payload["warnings"] == ["未检索到可支持回答的资料，本次未调用专家模型。"]


@pytest.mark.asyncio
async def test_chat_api_uses_general_retrieval_for_low_confidence_llm_route(
    monkeypatch: pytest.MonkeyPatch,
    fake_database: None,
) -> None:
    monkeypatch.setattr(chat_api.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(chat_api.settings, "intent_confidence_threshold", 0.72)
    searched_categories: list[str | None] = []

    async def fake_search(db, question, *, category, top_k):  # noqa: ANN001
        searched_categories.append(category)
        return [_article("其他")]

    async def fake_completion(*, system_prompt, user_prompt, **kwargs):  # noqa: ANN003
        if "意图分类器" in system_prompt:
            return '{"categories":["就业"],"confidence":0.4}'
        return "通用助手回答。"

    monkeypatch.setattr(chat_api, "search_articles", fake_search)
    monkeypatch.setattr(chat_api, "chat_completion", fake_completion)
    monkeypatch.setattr(intent_service, "chat_completion", fake_completion)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"question": "毕业后有哪些手续？", "route_mode": "auto"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert searched_categories == [None]
    assert payload["intent"] == "通用助手"
    assert payload["intents"] == []
    assert payload["experts"] == ["general"]
    assert payload["route_source"] == "llm"
    assert payload["confidence"] == 0.4
    assert payload["warnings"] == ["未能可靠识别具体领域，已使用通用助手并检索全领域资料。"]


@pytest.mark.asyncio
async def test_chat_api_warns_when_rules_cannot_identify_a_domain(
    monkeypatch: pytest.MonkeyPatch,
    fake_database: None,
) -> None:
    monkeypatch.setattr(chat_api.settings, "deepseek_api_key", "")
    monkeypatch.setattr(chat_api.settings, "llm_fallback_enabled", True)
    searched_categories: list[str | None] = []

    async def fake_search(db, question, *, category, top_k):  # noqa: ANN001
        searched_categories.append(category)
        return [_article("其他")]

    async def fake_completion(*, system_prompt, user_prompt, **kwargs):  # noqa: ANN003
        return "通用助手回答。"

    monkeypatch.setattr(chat_api, "search_articles", fake_search)
    monkeypatch.setattr(chat_api, "chat_completion", fake_completion)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={"question": "学校附近的天气怎么样？", "route_mode": "auto"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert searched_categories == [None]
    assert payload["intent"] == "通用助手"
    assert payload["intents"] == []
    assert payload["route_source"] == "rules"
    assert payload["warnings"] == ["未能可靠识别具体领域，已使用通用助手并检索全领域资料。"]


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "   ", "route_mode": "auto"},
        {"question": "毕业有哪些要求？", "route_mode": "manual", "agent": "academic"},
    ],
)
@pytest.mark.asyncio
async def test_chat_api_rejects_empty_questions_and_unknown_agents(
    payload: dict[str, str],
    fake_database: None,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post("/api/chat", json=payload)

    assert response.status_code == 422
