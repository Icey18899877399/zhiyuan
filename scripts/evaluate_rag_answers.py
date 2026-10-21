"""Evaluate saved RAG answers and citations without calling the chat API."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.rag_eval import (
    answer_case_to_dict,
    load_answer_dataset,
    load_dataset,
    summarize_answers,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="labeled retrieval evaluation JSONL")
    parser.add_argument("answers", type=Path, help="saved ChatResponse-like answers JSONL")
    parser.add_argument("--output", type=Path, help="optional path for the JSON report")
    parser.add_argument("--min-citation-label-mapping-rate", type=float)
    parser.add_argument("--min-cited-source-precision", type=float)
    parser.add_argument("--min-cited-source-recall", type=float)
    parser.add_argument("--min-answerable-citation-coverage", type=float)
    parser.add_argument("--max-answerable-abstention-rate", type=float)
    parser.add_argument("--min-unanswerable-abstention-rate", type=float)
    parser.add_argument("--max-unanswerable-citation-rate", type=float)
    return parser


def _check_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[str]:
    gates = (
        (
            args.min_citation_label_mapping_rate,
            "citation_label_mapping_rate",
            "minimum citation label mapping rate",
            True,
        ),
        (
            args.min_cited_source_precision,
            "cited_source_precision",
            "minimum cited-source precision",
            True,
        ),
        (args.min_cited_source_recall, "cited_source_recall", "minimum cited-source recall", True),
        (
            args.min_answerable_citation_coverage,
            "answerable_citation_coverage_rate",
            "minimum answerable citation coverage",
            True,
        ),
        (
            args.max_answerable_abstention_rate,
            "answerable_abstention_rate",
            "maximum answerable abstention rate",
            False,
        ),
        (
            args.min_unanswerable_abstention_rate,
            "unanswerable_correct_abstention_rate",
            "minimum unanswerable abstention rate",
            True,
        ),
        (
            args.max_unanswerable_citation_rate,
            "unanswerable_citation_rate",
            "maximum unanswerable citation rate",
            False,
        ),
    )
    failures: list[str] = []
    for threshold, key, label, minimum in gates:
        if threshold is None:
            continue
        value = summary[key]
        if value is None:
            failures.append(f"{label}: metric unavailable")
        elif minimum and value < threshold:
            failures.append(f"{label}: {value:.4f} < {threshold:.4f}")
        elif not minimum and value > threshold:
            failures.append(f"{label}: {value:.4f} > {threshold:.4f}")
    return failures


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    gate_options = (
        "min_citation_label_mapping_rate",
        "min_cited_source_precision",
        "min_cited_source_recall",
        "min_answerable_citation_coverage",
        "max_answerable_abstention_rate",
        "min_unanswerable_abstention_rate",
        "max_unanswerable_citation_rate",
    )
    for option in gate_options:
        value = getattr(args, option)
        if value is not None and not 0 <= value <= 1:
            parser.error(f"--{option.replace('_', '-')} must be between 0 and 1")

    cases = load_dataset(args.dataset)
    results = load_answer_dataset(args.answers, cases)
    summary = summarize_answers(results)
    failures = _check_gates(summary, args)
    thresholds = {option: getattr(args, option) for option in gate_options}
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(args.dataset),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "answers": str(args.answers),
        "answers_sha256": hashlib.sha256(args.answers.read_bytes()).hexdigest(),
        "summary": summary,
        "cases": [answer_case_to_dict(result) for result in results],
        "gates": {
            "status": "failed"
            if failures
            else "passed"
            if any(getattr(args, option) is not None for option in gate_options)
            else "not_configured",
            "thresholds": thresholds,
            "failures": failures,
        },
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
