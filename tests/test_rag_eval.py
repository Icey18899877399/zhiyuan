from __future__ import annotations

import json
import math

import pytest

from app.services.rag_eval import (
    AnswerCaseResult,
    CaseResult,
    EvalCase,
    RetrievedDocument,
    answer_case_to_dict,
    case_to_dict,
    load_answer_dataset,
    load_dataset,
    summarize,
    summarize_answers,
)


def _case(
    case_id: str,
    relevant: tuple[str, ...],
    category: str | None = None,
    tags: tuple[str, ...] = (),
) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        question=f"question {case_id}",
        relevant_source_urls=relevant,
        category=category,
        tags=tags,
    )


def test_load_dataset_parses_answerable_and_unanswerable_cases(tmp_path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "known",
                        "question": "招生流程是什么？",
                        "category": "学业",
                        "relevant_source_urls": ["https://example.test/a"],
                        "relevance_grades": {"https://example.test/a": 3},
                        "tags": ["direct"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "unknown",
                        "question": "校外无关问题",
                        "relevant_source_urls": [],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    cases = load_dataset(dataset)

    assert len(cases) == 2
    assert cases[0].category == "学业"
    assert cases[0].tags == ("direct",)
    assert cases[0].relevance_grades == (("https://example.test/a", 3),)
    assert cases[1].relevant_source_urls == ()


@pytest.mark.parametrize(
    "lines, message",
    [
        ('{"id":"x","question":"q","relevant_source_urls":[]}', "duplicate case id"),
        ('{"id":"x","question":"q","relevant_source_urls":[""]}', "non-empty strings"),
        ('{"id":"x","question":"q","relevant_source_urls":[]\n', "invalid JSON"),
        (
            '{"id":"x","question":"q","relevant_source_urls":["u"],"relevance_grades":{"u":4}}',
            "integer grades 1-3",
        ),
    ],
)
def test_load_dataset_rejects_invalid_cases(tmp_path, lines: str, message: str) -> None:
    dataset = tmp_path / "invalid.jsonl"
    if message == "duplicate case id":
        lines = lines + "\n" + lines
    dataset.write_text(lines, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_dataset(dataset)


def test_summary_computes_ranking_abstention_category_and_latency_metrics() -> None:
    answerable = CaseResult(
        case=_case("answerable", ("a", "b"), category="学业", tags=("direct",)),
        retrieved=(
            RetrievedDocument("wrong", "活动"),
            RetrievedDocument("a", "学业"),
            RetrievedDocument("b", "学业"),
        ),
        latency_ms=10,
    )
    false_positive = CaseResult(
        case=_case("false-positive", ()),
        retrieved=(RetrievedDocument("unrelated", "其他"),),
        latency_ms=20,
    )
    abstained = CaseResult(
        case=_case("abstained", ()),
        retrieved=(),
        latency_ms=30,
    )

    metrics = summarize([answerable, false_positive, abstained], k=2)

    assert metrics["recall_at_2"] == pytest.approx(0.5)
    assert metrics["precision_at_2"] == pytest.approx(0.5)
    assert metrics["mrr_at_2"] == pytest.approx(0.5)
    ideal_second_gain = 1 / math.log2(3)
    assert metrics["ndcg_at_2"] == pytest.approx(ideal_second_gain / (1 + ideal_second_gain))
    assert metrics["hit_rate_at_2"] == pytest.approx(1.0)
    assert metrics["unanswerable_false_positive_rate"] == pytest.approx(0.5)
    assert metrics["unanswerable_abstention_rate"] == pytest.approx(0.5)
    assert metrics["category_violation_rate"] == pytest.approx(0.5)
    assert metrics["latency_ms"]["p50"] == pytest.approx(20)
    assert metrics["latency_ms"]["p95"] == pytest.approx(29)
    assert metrics["by_category"]["学业"]["case_count"] == 1
    assert metrics["by_tag"]["direct"]["case_count"] == 1


def test_case_report_keeps_stable_source_url_labels() -> None:
    result = CaseResult(
        case=_case("one", ("https://example.test/a",)),
        retrieved=(RetrievedDocument("https://example.test/a", "学业", "通知"),),
        latency_ms=3.5,
    )

    report = case_to_dict(result, k=5)

    assert report["relevant_source_urls"] == ["https://example.test/a"]
    assert report["retrieved"][0]["source_url"] == "https://example.test/a"


def test_unanswerable_case_report_is_strict_json() -> None:
    result = CaseResult(case=_case("none", ()), retrieved=(), latency_ms=1)

    report = case_to_dict(result, k=5)

    assert report["metrics"]["recall_at_k"] is None
    assert report["metrics"]["ndcg_at_k"] is None
    json.dumps(report, allow_nan=False)


def test_ndcg_respects_higher_relevance_for_fresher_source() -> None:
    case = EvalCase(
        case_id="freshness",
        question="最新政策是什么？",
        relevant_source_urls=("old", "fresh"),
        tags=("time-sensitive",),
        relevance_grades=(("old", 1), ("fresh", 3)),
    )
    result = CaseResult(
        case=case,
        retrieved=(RetrievedDocument("old", "学业"), RetrievedDocument("fresh", "学业")),
        latency_ms=5,
    )

    metrics = summarize([result], k=2)

    assert metrics["ndcg_at_2"] < 1
    assert metrics["recall_at_2"] == pytest.approx(1)


def test_answer_metrics_score_citation_mapping_relevance_and_abstention(tmp_path) -> None:
    cases = [
        _case("supported", ("a", "b")),
        _case("unsupported", ()),
    ]
    answers_file = tmp_path / "answers.jsonl"
    answers_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "supported",
                        "answer_mode": "llm",
                        "answer": "通知见[学业-1]，补充信息见[学业-2]。错误标签[学业-9]。",
                        "retrieved": [
                            {"source_url": "a", "citations": ["[学业-1]"]},
                            {"source_url": "wrong", "citations": ["[学业-2]"]},
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "unsupported",
                        "answer_mode": "no_context",
                        "answer": "知识库没有相关资料。",
                        "retrieved": [],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    results = load_answer_dataset(answers_file, cases)
    metrics = summarize_answers(results)
    supported_report = answer_case_to_dict(results[0])

    assert metrics["citation_label_mapping_rate"] == pytest.approx(2 / 3)
    assert metrics["cited_source_precision"] == pytest.approx(0.5)
    assert metrics["cited_source_recall"] == pytest.approx(0.5)
    assert metrics["answerable_citation_coverage_rate"] == pytest.approx(1)
    assert metrics["unanswerable_correct_abstention_rate"] == pytest.approx(1)
    assert metrics["unanswerable_false_answer_rate"] == pytest.approx(0)
    assert supported_report["metrics"]["unmapped_citations"] == ["[学业-9]"]
    assert "answer" not in supported_report
    json.dumps(supported_report, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize(
    "answer_lines, message",
    [
        (
            '{"id":"unknown","answer":"x","answer_mode":"llm","retrieved":[]}',
            "match an evaluation case",
        ),
        (
            '{"id":"supported","answer":"x","answer_mode":"unknown","retrieved":[]}',
            "invalid answer_mode",
        ),
        (
            '{"id":"supported","answer":"x","answer_mode":"llm","retrieved":[{"source_url":"a","citations":["[bad]"]}]}',
            "valid citation labels",
        ),
    ],
)
def test_load_answer_dataset_rejects_invalid_answers(
    tmp_path, answer_lines: str, message: str
) -> None:
    answer_file = tmp_path / "answers.jsonl"
    answer_file.write_text(answer_lines, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_answer_dataset(answer_file, [_case("supported", ("a",))])


def test_load_answer_dataset_requires_exact_case_coverage(tmp_path) -> None:
    answer_file = tmp_path / "answers.jsonl"
    answer_file.write_text(
        '{"id":"supported","answer":"x","answer_mode":"llm","retrieved":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing case ids: unsupported"):
        load_answer_dataset(
            answer_file,
            [_case("supported", ("a",)), _case("unsupported", ())],
        )


def test_answer_metrics_treat_missing_citations_and_nonempty_unanswerable_context_as_failures() -> (
    None
):
    answerable = AnswerCaseResult(
        case=_case("answerable", ("source",)),
        answer_mode="no_context",
        answer="暂无资料。",
        retrieved=(),
    )
    unanswerable = AnswerCaseResult(
        case=_case("unanswerable", ()),
        answer_mode="no_context",
        answer="暂无资料。",
        retrieved=({"source_url": "unrelated", "citations": []},),
    )

    metrics = summarize_answers([answerable, unanswerable])

    assert metrics["cited_source_recall"] == pytest.approx(0)
    assert metrics["answerable_citation_coverage_rate"] == pytest.approx(0)
    assert metrics["answerable_abstention_rate"] == pytest.approx(1)
    assert metrics["unanswerable_correct_abstention_rate"] == pytest.approx(0)
    assert metrics["unanswerable_false_answer_rate"] == pytest.approx(1)
