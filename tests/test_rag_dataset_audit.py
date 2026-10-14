from __future__ import annotations

import json
import sys

import pytest

from app.services.rag_dataset_audit import audit_dataset
from app.services.rag_eval import EvalCase
from scripts.audit_rag_dataset import main


def _case(
    case_id: str,
    *,
    category: str | None,
    tags: tuple[str, ...],
    relevant: tuple[str, ...] = ("https://source.test/a",),
    grades: tuple[tuple[str, int], ...] = (),
    question: str | None = None,
) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        question=question or f"question {case_id}",
        relevant_source_urls=relevant,
        category=category,
        tags=tags,
        relevance_grades=grades,
    )


def test_audit_passes_when_required_coverage_and_time_grades_are_present() -> None:
    categories = ("学业", "活动", "党团", "就业", "其他")
    tags = ("direct", "paraphrase", "multi-article", "time-sensitive", "ambiguous")
    cases = [
        _case(
            f"case-{index}",
            category=categories[index % len(categories)],
            tags=(tags[index % len(tags)],),
            relevant=(
                ("https://source.test/a", "https://source.test/b")
                if index % len(tags) == 2
                else ("https://source.test/a",)
            ),
            grades=(("https://source.test/a", 3),) if index % len(tags) == 3 else (),
        )
        for index in range(29)
    ]
    cases.append(
        _case(
            "out-of-domain-case",
            category=None,
            tags=("out-of-domain",),
            relevant=(),
        )
    )

    report = audit_dataset(cases)

    assert report["status"] == "passed"
    assert report["case_count"] == 30
    assert report["answerable_case_count"] == 29
    assert report["unanswerable_case_count"] == 1
    assert report["answerable_case_rate"] == pytest.approx(29 / 30)
    assert report["unanswerable_case_rate"] == pytest.approx(1 / 30)
    assert not report["errors"]


def test_audit_reports_missing_coverage_and_invalid_out_of_domain_labels() -> None:
    cases = [
        _case(
            "duplicate-a",
            category="未知分类",
            tags=("out-of-domain", "time-sensitive"),
            question="相同的 问题",
        ),
        _case(
            "duplicate-b",
            category="学业",
            tags=("direct", "multi-article"),
            question="  相同的   问题 ",
        ),
    ]

    report = audit_dataset(cases, min_cases=1, max_cases=50)

    assert report["status"] == "failed"
    assert any("unknown categories" in error for error in report["errors"])
    assert any("duplicate normalized questions" in error for error in report["errors"])
    assert any(
        "out-of-domain cases must have no relevant sources" in error for error in report["errors"]
    )
    assert any(
        "time-sensitive cases must grade every relevant source" in error
        for error in report["errors"]
    )
    assert any("multi-article cases must label at least two" in error for error in report["errors"])


def test_audit_validates_bounds_and_nonempty_input() -> None:
    with pytest.raises(ValueError, match="case-count bounds"):
        audit_dataset([_case("one", category=None, tags=())], min_cases=2, max_cases=1)
    with pytest.raises(ValueError, match="at least one case"):
        audit_dataset([])


def test_audit_cli_supports_explicit_pilot_scope_and_writes_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "pilot.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "answerable",
                        "question": "校园通知有什么安排？",
                        "category": "学业",
                        "relevant_source_urls": ["https://source.test/a"],
                        "tags": ["direct"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "unanswerable",
                        "question": "校外领域问题？",
                        "category": None,
                        "relevant_source_urls": [],
                        "tags": ["out-of-domain"],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "audit.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_rag_dataset",
            str(dataset),
            "--min-cases",
            "2",
            "--max-cases",
            "2",
            "--required-categories",
            "学业",
            "--required-tags",
            "direct",
            "out-of-domain",
            "--output",
            str(output),
        ],
    )

    assert main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed"
