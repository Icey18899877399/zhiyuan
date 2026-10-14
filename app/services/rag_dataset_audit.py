"""Coverage and annotation-quality checks for the RAG golden set."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from app.services.rag_eval import EvalCase

SUPPORTED_CATEGORIES = ("学业", "活动", "党团", "就业", "其他")
REQUIRED_QUESTION_TAGS = (
    "direct",
    "paraphrase",
    "multi-article",
    "time-sensitive",
    "ambiguous",
    "out-of-domain",
)


def audit_dataset(
    cases: list[EvalCase],
    *,
    min_cases: int = 30,
    max_cases: int = 50,
    required_categories: tuple[str, ...] = SUPPORTED_CATEGORIES,
    required_tags: tuple[str, ...] = REQUIRED_QUESTION_TAGS,
) -> dict[str, Any]:
    """Return actionable coverage errors and warnings without accessing external systems."""
    if min_cases < 1 or max_cases < min_cases:
        raise ValueError("case-count bounds must satisfy 1 <= min_cases <= max_cases")
    if not cases:
        raise ValueError("dataset must contain at least one case")

    category_counts = Counter(case.category for case in cases if case.category is not None)
    tag_counts = Counter(tag for case in cases for tag in case.tags)
    answerable_count = sum(bool(case.relevant_source_urls) for case in cases)
    unanswerable_count = len(cases) - answerable_count

    errors: list[str] = []
    warnings: list[str] = []
    if not min_cases <= len(cases) <= max_cases:
        errors.append(
            f"case count {len(cases)} is outside the configured range {min_cases}-{max_cases}"
        )

    missing_categories = [
        category for category in required_categories if not category_counts[category]
    ]
    if missing_categories:
        errors.append(f"missing required categories: {', '.join(missing_categories)}")
    unknown_categories = sorted(set(category_counts) - set(required_categories))
    if unknown_categories:
        errors.append(f"unknown categories: {', '.join(unknown_categories)}")

    missing_tags = [tag for tag in required_tags if not tag_counts[tag]]
    if missing_tags:
        errors.append(f"missing required question tags: {', '.join(missing_tags)}")
    if answerable_count == 0:
        errors.append("dataset has no answerable cases")
    if unanswerable_count == 0:
        errors.append("dataset has no unanswerable cases")

    domain_errors = [
        case.case_id for case in cases if "out-of-domain" in case.tags and case.relevant_source_urls
    ]
    if domain_errors:
        errors.append(
            "out-of-domain cases must have no relevant sources: " + ", ".join(domain_errors)
        )
    if tag_counts["out-of-domain"] and not any(
        "out-of-domain" in case.tags and not case.relevant_source_urls for case in cases
    ):
        errors.append("out-of-domain tag must include at least one unanswerable case")

    invalid_multi_article = [
        case.case_id
        for case in cases
        if "multi-article" in case.tags and len(case.relevant_source_urls) < 2
    ]
    if invalid_multi_article:
        errors.append(
            "multi-article cases must label at least two relevant sources: "
            + ", ".join(invalid_multi_article)
        )

    question_cases: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        normalized_question = re.sub(r"\s+", " ", case.question).strip().casefold()
        question_cases[normalized_question].append(case.case_id)
    duplicate_questions = [
        {"case_ids": case_ids, "question": question}
        for question, case_ids in sorted(question_cases.items())
        if len(case_ids) > 1
    ]
    if duplicate_questions:
        errors.append(f"found {len(duplicate_questions)} duplicate normalized questions")

    time_sensitive_missing_grades = [
        {
            "case_id": case.case_id,
            "source_urls": [
                url for url in case.relevant_source_urls if url not in dict(case.relevance_grades)
            ],
        }
        for case in cases
        if "time-sensitive" in case.tags
        and any(url not in dict(case.relevance_grades) for url in case.relevant_source_urls)
    ]
    if time_sensitive_missing_grades:
        errors.append(
            "time-sensitive cases must grade every relevant source: "
            + ", ".join(item["case_id"] for item in time_sensitive_missing_grades)
        )

    sparse_categories = {
        category: count for category, count in sorted(category_counts.items()) if count < 2
    }
    if sparse_categories:
        warnings.append(
            "categories represented by a single case have weak subgroup evidence: "
            + ", ".join(f"{category}={count}" for category, count in sparse_categories.items())
        )

    return {
        "status": "failed" if errors else "passed",
        "case_count": len(cases),
        "answerable_case_count": answerable_count,
        "unanswerable_case_count": unanswerable_count,
        "answerable_case_rate": answerable_count / len(cases),
        "unanswerable_case_rate": unanswerable_count / len(cases),
        "category_coverage_count": len(category_counts),
        "required_category_count": len(required_categories),
        "tag_coverage_count": sum(bool(tag_counts[tag]) for tag in required_tags),
        "required_tag_count": len(required_tags),
        "category_counts": dict(sorted(category_counts.items())),
        "tag_counts": dict(sorted(tag_counts.items())),
        "required_categories": list(required_categories),
        "required_tags": list(required_tags),
        "duplicate_questions": duplicate_questions,
        "time_sensitive_missing_grades": time_sensitive_missing_grades,
        "invalid_multi_article_cases": invalid_multi_article,
        "errors": errors,
        "warnings": warnings,
    }
