"""意图识别与专家路由的纯逻辑测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import intent


@pytest.mark.parametrize("threshold", [0.0, -0.01, 1.01])
def test_intent_confidence_threshold_rejects_out_of_range_values(
    threshold: float,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://localhost/test",
            database_url_sync="postgresql://localhost/test",
            intent_confidence_threshold=threshold,
        )


@pytest.mark.parametrize("threshold", [0.01, 1.0])
def test_intent_confidence_threshold_accepts_probability_values(
    threshold: float,
) -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://localhost/test",
        database_url_sync="postgresql://localhost/test",
        intent_confidence_threshold=threshold,
    )

    assert settings.intent_confidence_threshold == threshold


def test_rule_classifier_returns_single_category() -> None:
    result = intent.classify_intent("本学期考试和学分要求是什么？")

    assert result.categories == ("学业",)
    assert result.experts == ("academic",)
    assert result.confidence > 0.72


def test_rule_classifier_recognises_generic_activity_question() -> None:
    result = intent.classify_intent("十月份学院有什么活动？")

    assert result.categories == ("活动",)
    assert result.experts == ("activity",)


def test_rule_classifier_returns_all_categories_for_compound_question() -> None:
    result = intent.classify_intent("毕业和就业有哪些通知？")

    assert result.categories == ("学业", "就业")
    assert result.experts == ("academic", "career")


@pytest.mark.parametrize(
    "question,expected",
    [
        ("奖学金申请条件是什么？", ("学业",)),
        ("绩点如何计算？", ("学业",)),
        ("如何办理休学？", ("其他",)),
        ("毕业论文答辩安排在哪看？", ("学业",)),
        ("参加学院讲座需要报名吗？", ("活动",)),
        ("校园运动会什么时候举行？", ("活动",)),
        ("志愿服务活动在哪里报名？", ("活动",)),
        ("党支部换届有什么流程？", ("党团",)),
        ("入党积极分子如何确定？", ("党团",)),
        ("团员证丢了怎么补办？", ("党团",)),
        ("校招三方协议怎么签？", ("就业",)),
        ("毕业后档案和户口怎么处理？", ("就业", "学业")),
        ("实习岗位的网申截止时间是什么？", ("就业",)),
        ("宿舍报修从哪里提交？", ("其他",)),
        ("校园卡丢失如何补办？", ("其他",)),
        ("请假需要哪些材料？", ("其他",)),
        ("毕业和就业有哪些通知？", ("学业", "就业")),
        ("党团活动报名流程是什么？", ("活动", "党团")),
        ("今天天气怎么样？", ()),
        ("附近有什么好吃的？", ()),
    ],
)
def test_rule_classifier_covers_common_campus_queries(
    question: str,
    expected: tuple[str, ...],
) -> None:
    assert intent.classify_intent(question).categories == expected


def test_rule_classifier_returns_general_for_unknown_question() -> None:
    result = intent.classify_intent("今天天气怎么样？")

    assert result.category is None
    assert result.expert == "general"
    assert result.categories == ()
    assert result.confidence == 0.0


def test_llm_parser_filters_invalid_categories_and_deduplicates() -> None:
    result = intent._parse_llm_result(
        '{"categories":["就业","未知","就业","学业"],"confidence":1.4}'
    )

    assert result is not None
    assert result.categories == ("就业", "学业")
    assert result.experts == ("career", "academic")
    assert result.confidence == 1.0


@pytest.mark.parametrize(
    "raw",
    [
        "null",
        "[]",
        "{}",
        '{"confidence":0.9}',
        '{"categories":["活动"]}',
        '{"categories":["活动"],"confidence":"0.9"}',
        '{"categories":["活动"],"confidence":true}',
        '{"categories":[],"confidence":null}',
        '{"categories":[{"bad":"category"}],"confidence":0.9}',
        '{"categories":["未知"],"confidence":0.9}',
    ],
)
def test_llm_parser_rejects_malformed_or_unusable_payloads(raw: str) -> None:
    assert intent._parse_llm_result(raw) is None


def test_llm_parser_accepts_explicit_empty_categories_and_sanitizes_nan() -> None:
    result = intent._parse_llm_result('{"categories":[],"confidence":NaN}')

    assert result is not None
    assert result.categories == ()
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_auto_route_uses_rule_result_when_llm_output_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent.settings, "deepseek_api_key", "test-key")

    async def invalid_llm_result(question: str):
        return intent._parse_llm_result('{"categories":["活动"],"confidence":"0.9"}')

    monkeypatch.setattr(intent, "_classify_by_llm", invalid_llm_result)
    result = await intent.resolve_intent(
        "学院最近有什么活动？",
        selected_category=None,
        route_mode="auto",
    )

    assert result.categories == ("活动",)
    assert result.experts == ("activity",)
    assert result.warnings == ("大模型意图识别未能提供有效结果，已按关键词规则路由。",)


@pytest.mark.asyncio
async def test_auto_route_uses_llm_for_low_confidence_rule_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(intent.settings, "intent_confidence_threshold", 0.9)
    calls: list[str] = []

    async def classify_by_llm(question: str) -> intent.IntentResult:
        calls.append(question)
        return intent._parse_llm_result('{"categories":["活动"],"confidence":0.91}')

    monkeypatch.setattr(intent, "_classify_by_llm", classify_by_llm)
    result = await intent.resolve_intent(
        "学院最近有什么活动？",
        selected_category=None,
        route_mode="auto",
    )

    assert calls == ["学院最近有什么活动？"]
    assert result.categories == ("活动",)
    assert result.confidence == 0.91
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_auto_route_uses_general_when_llm_confidence_is_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(intent.settings, "intent_confidence_threshold", 0.72)

    async def classify_by_llm(question: str) -> intent.IntentResult:
        return intent._parse_llm_result('{"categories":["就业"],"confidence":0.4}')

    monkeypatch.setattr(intent, "_classify_by_llm", classify_by_llm)
    result = await intent.resolve_intent(
        "毕业后有哪些手续？",
        selected_category=None,
        route_mode="auto",
    )

    assert result.categories == ()
    assert result.expert == "general"
    assert result.confidence == 0.4
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_auto_route_skips_llm_for_high_confidence_rule_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent.settings, "deepseek_api_key", "test-key")
    calls = 0

    async def fail_if_called(question: str):
        nonlocal calls
        calls += 1
        raise AssertionError("high-confidence route should not call the LLM")

    monkeypatch.setattr(intent, "_classify_by_llm", fail_if_called)
    result = await intent.resolve_intent(
        "本学期考试和学分要求是什么？",
        selected_category=None,
        route_mode="auto",
    )

    assert calls == 0
    assert result.categories == ("学业",)
    assert result.confidence >= intent.settings.intent_confidence_threshold
    assert result.source == "rules"


@pytest.mark.asyncio
async def test_manual_route_does_not_call_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("manual route should not call the LLM")

    monkeypatch.setattr(intent, "_classify_by_llm", fail_if_called)
    result = await intent.resolve_intent(
        "毕业和就业有哪些通知？",
        selected_category="就业",
        route_mode="manual",
    )

    assert result.categories == ("就业",)
    assert result.experts == ("career",)
    assert result.confidence == 1.0
    assert result.source == "manual"


@pytest.mark.asyncio
async def test_auto_route_keeps_rule_compound_result_when_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intent.settings, "deepseek_api_key", "")
    result = await intent.resolve_intent(
        "毕业和就业有哪些通知？",
        selected_category=None,
        route_mode="auto",
    )

    assert result.categories == ("学业", "就业")
