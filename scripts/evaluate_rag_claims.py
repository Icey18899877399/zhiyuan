"""Score human claim-level grounding reviews for saved RAG answers."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.rag_eval import load_answer_dataset, load_dataset
from app.services.rag_review_eval import (
    load_claim_reviews,
    review_case_to_dict,
    summarize_claim_reviews,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="labeled retrieval evaluation JSONL")
    parser.add_argument("answers", type=Path, help="saved ChatResponse-like answers JSONL")
    parser.add_argument("reviews", type=Path, help="human-reviewed claim judgments JSONL")
    parser.add_argument("--output", type=Path, help="optional path for the JSON report")
    parser.add_argument("--min-claim-citation-coverage", type=float)
    parser.add_argument("--min-fully-supported-claim-rate", type=float)
    parser.add_argument("--min-fully-supported-cited-claim-rate", type=float)
    parser.add_argument("--max-partially-supported-claim-rate", type=float)
    parser.add_argument("--max-unsupported-claim-rate", type=float)
    parser.add_argument("--max-uncited-claim-rate", type=float)
    return parser


def _check_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[str]:
    gates = (
        (
            args.min_claim_citation_coverage,
            "claim_citation_coverage_rate",
            "minimum claim citation coverage",
            True,
        ),
        (
            args.min_fully_supported_claim_rate,
            "fully_supported_claim_rate",
            "minimum fully supported claim rate",
            True,
        ),
        (
            args.min_fully_supported_cited_claim_rate,
            "fully_supported_cited_claim_rate",
            "minimum fully supported cited-claim rate",
            True,
        ),
        (
            args.max_partially_supported_claim_rate,
            "partially_supported_claim_rate",
            "maximum partially supported claim rate",
            False,
        ),
        (
            args.max_unsupported_claim_rate,
            "unsupported_claim_rate",
            "maximum unsupported claim rate",
            False,
        ),
        (args.max_uncited_claim_rate, "uncited_claim_rate", "maximum uncited claim rate", False),
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
        "min_claim_citation_coverage",
        "min_fully_supported_claim_rate",
        "min_fully_supported_cited_claim_rate",
        "max_partially_supported_claim_rate",
        "max_unsupported_claim_rate",
        "max_uncited_claim_rate",
    )
    for option in gate_options:
        value = getattr(args, option)
        if value is not None and not 0 <= value <= 1:
            parser.error(f"--{option.replace('_', '-')} must be between 0 and 1")

    cases = load_dataset(args.dataset)
    answers = load_answer_dataset(args.answers, cases)
    reviews = load_claim_reviews(args.reviews, answers)
    summary = summarize_claim_reviews(reviews)
    failures = _check_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "answers_sha256": hashlib.sha256(args.answers.read_bytes()).hexdigest(),
        "reviews_sha256": hashlib.sha256(args.reviews.read_bytes()).hexdigest(),
        "summary": summary,
        "cases": [review_case_to_dict(review) for review in reviews],
        "gates": {
            "status": "failed"
            if failures
            else "passed"
            if any(getattr(args, option) is not None for option in gate_options)
            else "not_configured",
            "thresholds": {option: getattr(args, option) for option in gate_options},
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
