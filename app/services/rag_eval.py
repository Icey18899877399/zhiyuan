"""Ground-truth loading and deterministic retrieval metrics for RAG evaluation."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CITATION_PATTERN = re.compile(r"\[(?:[^\[\]\r\n]{1,32}-)?\d+\]")


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    question: str
    relevant_source_urls: tuple[str, ...]
    category: str | None = None
    tags: tuple[str, ...] = ()
    relevance_grades: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class RetrievedDocument:
    source_url: str
    category: str | None
    title: str = ""


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    retrieved: tuple[RetrievedDocument, ...]
    latency_ms: float


@dataclass(frozen=True)
class AnswerCaseResult:
    case: EvalCase
    answer_mode: str
    answer: str
    retrieved: tuple[dict[str, Any], ...]


def _parse_case(payload: Any, line_number: int) -> EvalCase:
    if not isinstance(payload, dict):
        raise ValueError(f"line {line_number}: each JSON value must be an object")

    case_id = payload.get("id")
    question = payload.get("question")
    relevant = payload.get("relevant_source_urls")
    category = payload.get("category")
    tags = payload.get("tags", [])
    grades = payload.get("relevance_grades", {})

    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError(f"line {line_number}: id must be a non-empty string")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"line {line_number}: question must be a non-empty string")
    if not isinstance(relevant, list) or any(
        not isinstance(url, str) or not url.strip() for url in relevant
    ):
        raise ValueError(
            f"line {line_number}: relevant_source_urls must be a list of non-empty strings"
        )
    relevant_urls = tuple(url.strip() for url in relevant)
    if len(set(relevant_urls)) != len(relevant_urls):
        raise ValueError(f"line {line_number}: relevant_source_urls must be unique")
    if category is not None and (not isinstance(category, str) or not category.strip()):
        raise ValueError(f"line {line_number}: category must be a non-empty string or null")
    if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags):
        raise ValueError(f"line {line_number}: tags must be a list of non-empty strings")
    normalized_tags = tuple(tag.strip() for tag in tags)
    if any(not tag for tag in normalized_tags) or len(set(normalized_tags)) != len(normalized_tags):
        raise ValueError(f"line {line_number}: tags must be non-empty and unique")
    if not isinstance(grades, dict) or any(
        not isinstance(url, str) or type(grade) is not int or not 1 <= grade <= 3
        for url, grade in grades.items()
    ):
        raise ValueError(
            f"line {line_number}: relevance_grades must map URLs to integer grades 1-3"
        )
    normalized_grades = {url.strip(): grade for url, grade in grades.items()}
    if len(normalized_grades) != len(grades):
        raise ValueError(f"line {line_number}: relevance_grades URLs must be unique")
    if not set(normalized_grades).issubset(relevant_urls):
        raise ValueError(f"line {line_number}: relevance_grades keys must be relevant source URLs")

    return EvalCase(
        case_id=case_id.strip(),
        question=question.strip(),
        relevant_source_urls=relevant_urls,
        category=category.strip() if category else None,
        tags=normalized_tags,
        relevance_grades=tuple(sorted(normalized_grades.items())),
    )


def load_dataset(path: str | Path) -> list[EvalCase]:
    """Load JSONL cases and reject empty datasets or duplicate case IDs."""
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    with Path(path).open(encoding="utf-8") as dataset_file:
        for line_number, line in enumerate(dataset_file, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            case = _parse_case(payload, line_number)
            if case.case_id in seen_ids:
                raise ValueError(f"line {line_number}: duplicate case id {case.case_id!r}")
            seen_ids.add(case.case_id)
            cases.append(case)

    if not cases:
        raise ValueError("evaluation dataset has no cases")
    return cases


def load_answer_dataset(
    path: str | Path,
    cases: list[EvalCase],
) -> list[AnswerCaseResult]:
    """Load saved ChatResponse-like JSONL and require a one-to-one case match."""
    expected = {case.case_id: case for case in cases}
    answers: dict[str, AnswerCaseResult] = {}
    with Path(path).open(encoding="utf-8") as answer_file:
        for line_number, line in enumerate(answer_file, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number}: each JSON value must be an object")

            case_id = payload.get("id")
            answer = payload.get("answer")
            answer_mode = payload.get("answer_mode")
            retrieved = payload.get("retrieved")
            if not isinstance(case_id, str) or case_id not in expected:
                raise ValueError(f"line {line_number}: id must match an evaluation case")
            if case_id in answers:
                raise ValueError(f"line {line_number}: duplicate answer id {case_id!r}")
            if not isinstance(answer, str):
                raise ValueError(f"line {line_number}: answer must be a string")
            if not isinstance(answer_mode, str) or answer_mode not in {
                "llm",
                "retrieval_fallback",
                "no_context",
            }:
                raise ValueError(f"line {line_number}: invalid answer_mode")
            if not isinstance(retrieved, list):
                raise ValueError(f"line {line_number}: retrieved must be a list")

            normalized_retrieved: list[dict[str, Any]] = []
            for item in retrieved:
                if not isinstance(item, dict):
                    raise ValueError(f"line {line_number}: each retrieved item must be an object")
                source_url = item.get("source_url")
                citations = item.get("citations", [])
                if not isinstance(source_url, str) or not source_url.strip():
                    raise ValueError(f"line {line_number}: source_url must be a non-empty string")
                if not isinstance(citations, list) or any(
                    not isinstance(citation, str) or not CITATION_PATTERN.fullmatch(citation)
                    for citation in citations
                ):
                    raise ValueError(f"line {line_number}: citations must be valid citation labels")
                if len(set(citations)) != len(citations):
                    raise ValueError(f"line {line_number}: citations must be unique per source")
                normalized_retrieved.append(
                    {"source_url": source_url.strip(), "citations": list(citations)}
                )

            answers[case_id] = AnswerCaseResult(
                case=expected[case_id],
                answer_mode=answer_mode,
                answer=answer,
                retrieved=tuple(normalized_retrieved),
            )

    missing = sorted(set(expected) - set(answers))
    if missing:
        raise ValueError(f"answer dataset is missing case ids: {', '.join(missing)}")
    return [answers[case.case_id] for case in cases]


def _answer_case_metrics(result: AnswerCaseResult) -> dict[str, Any]:
    cited_labels = list(dict.fromkeys(CITATION_PATTERN.findall(result.answer)))
    label_sources: dict[str, set[str]] = {}
    for item in result.retrieved:
        for citation in item["citations"]:
            label_sources.setdefault(citation, set()).add(item["source_url"])

    mapped_labels = [label for label in cited_labels if len(label_sources.get(label, set())) == 1]
    unmapped_labels = [label for label in cited_labels if not label_sources.get(label)]
    ambiguous_labels = [label for label in cited_labels if len(label_sources.get(label, set())) > 1]
    cited_sources = {
        source_url for label in cited_labels for source_url in label_sources.get(label, set())
    }
    expected_sources = set(result.case.relevant_source_urls)
    relevant_cited_sources = cited_sources & expected_sources
    answerable = bool(expected_sources)
    correct_abstention = result.answer_mode == "no_context" and not result.retrieved

    return {
        "answerable": answerable,
        "citation_label_mapping_rate": (
            len(mapped_labels) / len(cited_labels) if cited_labels else None
        ),
        "cited_source_precision": (
            len(relevant_cited_sources) / len(cited_sources) if cited_sources else None
        ),
        "cited_source_recall": (
            len(relevant_cited_sources) / len(expected_sources) if answerable else None
        ),
        "has_relevant_citation": bool(relevant_cited_sources) if answerable else None,
        "answerable_abstained": result.answer_mode == "no_context" if answerable else None,
        "unanswerable_correct_abstention": correct_abstention if not answerable else None,
        "unanswerable_false_answer": not correct_abstention if not answerable else None,
        "cited_label_count": len(cited_labels),
        "mapped_label_count": len(mapped_labels),
        "unmapped_label_count": len(unmapped_labels),
        "ambiguous_label_count": len(ambiguous_labels),
        "cited_source_count": len(cited_sources),
        "relevant_cited_source_count": len(relevant_cited_sources),
        "cited_citations": cited_labels,
        "unmapped_citations": unmapped_labels,
        "ambiguous_citations": ambiguous_labels,
        "cited_source_urls": sorted(cited_sources),
    }


def _summarize_answers(results: list[AnswerCaseResult]) -> dict[str, Any]:
    per_case = [_answer_case_metrics(result) for result in results]
    answerable = [metrics for metrics in per_case if metrics["answerable"]]
    unanswerable = [metrics for metrics in per_case if not metrics["answerable"]]
    cited_cases = [metrics for metrics in per_case if metrics["cited_source_count"]]
    cited_label_count = sum(int(metrics["cited_label_count"]) for metrics in per_case)
    mapped_label_count = sum(int(metrics["mapped_label_count"]) for metrics in per_case)
    unanswerable_cited = sum(int(metrics["cited_label_count"] > 0) for metrics in unanswerable)

    return {
        "case_count": len(results),
        "answerable_case_count": len(answerable),
        "unanswerable_case_count": len(unanswerable),
        "citation_label_count": cited_label_count,
        "mapped_citation_label_count": mapped_label_count,
        "unmapped_citation_label_count": sum(
            int(metrics["unmapped_label_count"]) for metrics in per_case
        ),
        "ambiguous_citation_label_count": sum(
            int(metrics["ambiguous_label_count"]) for metrics in per_case
        ),
        "citation_label_mapping_rate": (
            mapped_label_count / cited_label_count if cited_label_count else None
        ),
        "cited_source_precision": _mean(
            [float(metrics["cited_source_precision"]) for metrics in cited_cases]
        ),
        "cited_source_recall": _mean(
            [float(metrics["cited_source_recall"]) for metrics in answerable]
        ),
        "answerable_citation_coverage_rate": _mean(
            [float(metrics["has_relevant_citation"]) for metrics in answerable]
        ),
        "answerable_abstention_rate": _mean(
            [float(metrics["answerable_abstained"]) for metrics in answerable]
        ),
        "unanswerable_correct_abstention_rate": _mean(
            [float(metrics["unanswerable_correct_abstention"]) for metrics in unanswerable]
        ),
        "unanswerable_false_answer_rate": _mean(
            [float(metrics["unanswerable_false_answer"]) for metrics in unanswerable]
        ),
        "unanswerable_citation_rate": (
            unanswerable_cited / len(unanswerable) if unanswerable else None
        ),
    }


def summarize_answers(results: list[AnswerCaseResult]) -> dict[str, Any]:
    """Compute citation metrics overall and by labeled category/tag."""
    summary = _summarize_answers(results)
    by_category: dict[str, list[AnswerCaseResult]] = {}
    by_tag: dict[str, list[AnswerCaseResult]] = {}
    for result in results:
        by_category.setdefault(result.case.category or "unfiltered", []).append(result)
        for tag in result.case.tags:
            by_tag.setdefault(tag, []).append(result)

    summary["by_category"] = {
        category: _summarize_answers(group) for category, group in sorted(by_category.items())
    }
    summary["by_tag"] = {tag: _summarize_answers(group) for tag, group in sorted(by_tag.items())}
    return summary


def answer_case_to_dict(result: AnswerCaseResult) -> dict[str, Any]:
    return {
        "id": result.case.case_id,
        "answer_mode": result.answer_mode,
        "relevant_source_urls": list(result.case.relevant_source_urls),
        "retrieved": list(result.retrieved),
        "metrics": _answer_case_metrics(result),
    }


def _case_metrics(result: CaseResult, k: int) -> dict[str, float | int | bool | None]:
    if k <= 0:
        raise ValueError("k must be greater than zero")

    expected = set(result.case.relevant_source_urls)
    relevance_grades = dict(result.case.relevance_grades)
    documents = result.retrieved[:k]
    seen: set[str] = set()
    relevant_rank_grades: list[tuple[int, int]] = []
    category_violations = 0

    for rank, document in enumerate(documents, start=1):
        if document.source_url in expected and document.source_url not in seen:
            grade = relevance_grades.get(document.source_url, 1)
            relevant_rank_grades.append((rank, grade))
            seen.add(document.source_url)
        if result.case.category and document.category != result.case.category:
            category_violations += 1

    is_answerable = bool(expected)
    recall = len(seen) / len(expected) if is_answerable else None
    precision = len(relevant_rank_grades) / k
    reciprocal_rank = 1 / relevant_rank_grades[0][0] if relevant_rank_grades else 0.0
    dcg = sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in relevant_rank_grades)
    ideal_grades = sorted(
        (relevance_grades.get(url, 1) for url in expected),
        reverse=True,
    )[:k]
    ideal_dcg = sum(
        (2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal_grades, start=1)
    )
    ndcg = dcg / ideal_dcg if ideal_dcg else None

    return {
        "answerable": is_answerable,
        "hit": bool(relevant_rank_grades),
        "recall_at_k": recall,
        "precision_at_k": precision,
        "reciprocal_rank_at_k": reciprocal_rank,
        "ndcg_at_k": ndcg,
        "unanswerable_false_positive": not is_answerable and bool(documents),
        "unanswerable_abstained": not is_answerable and not documents,
        "category_violations": category_violations,
        "category_checked_documents": len(documents) if result.case.category else 0,
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _summarize_subset(results: list[CaseResult], k: int) -> dict[str, Any]:
    per_case = [_case_metrics(result, k) for result in results]
    answerable = [metrics for metrics in per_case if metrics["answerable"]]
    unanswerable = [metrics for metrics in per_case if not metrics["answerable"]]
    category_documents = sum(int(m["category_checked_documents"]) for m in per_case)
    category_violations = sum(int(m["category_violations"]) for m in per_case)
    latencies = [result.latency_ms for result in results]

    return {
        "case_count": len(results),
        "answerable_case_count": len(answerable),
        "unanswerable_case_count": len(unanswerable),
        f"recall_at_{k}": _mean([float(m["recall_at_k"]) for m in answerable]),
        f"precision_at_{k}": _mean([float(m["precision_at_k"]) for m in answerable]),
        f"mrr_at_{k}": _mean([float(m["reciprocal_rank_at_k"]) for m in answerable]),
        f"ndcg_at_{k}": _mean([float(m["ndcg_at_k"]) for m in answerable]),
        f"hit_rate_at_{k}": _mean([float(m["hit"]) for m in answerable]),
        "unanswerable_false_positive_rate": _mean(
            [float(m["unanswerable_false_positive"]) for m in unanswerable]
        ),
        "unanswerable_abstention_rate": _mean(
            [float(m["unanswerable_abstained"]) for m in unanswerable]
        ),
        "category_violation_rate": (
            category_violations / category_documents if category_documents else None
        ),
        "category_checked_document_count": category_documents,
        "category_violation_count": category_violations,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
    }


def summarize(results: list[CaseResult], k: int) -> dict[str, Any]:
    """Compute overall scores and category/tag breakdowns."""
    summary = _summarize_subset(results, k)
    by_category: dict[str, list[CaseResult]] = {}
    by_tag: dict[str, list[CaseResult]] = {}
    for result in results:
        by_category.setdefault(result.case.category or "unfiltered", []).append(result)
        for tag in result.case.tags:
            by_tag.setdefault(tag, []).append(result)

    summary["by_category"] = {
        category: _summarize_subset(group, k) for category, group in sorted(by_category.items())
    }
    summary["by_tag"] = {tag: _summarize_subset(group, k) for tag, group in sorted(by_tag.items())}
    return summary


def case_to_dict(result: CaseResult, k: int) -> dict[str, Any]:
    metrics = _case_metrics(result, k)
    return {
        "id": result.case.case_id,
        "question": result.case.question,
        "category": result.case.category,
        "tags": list(result.case.tags),
        "relevant_source_urls": list(result.case.relevant_source_urls),
        "relevance_grades": dict(result.case.relevance_grades),
        "retrieved": [
            {
                "source_url": document.source_url,
                "category": document.category,
                "title": document.title,
            }
            for document in result.retrieved[:k]
        ],
        "latency_ms": result.latency_ms,
        "metrics": metrics,
    }
