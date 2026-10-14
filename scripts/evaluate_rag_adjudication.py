"""Score final human-adjudicated RAG claim grounding."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.rag_eval import load_answer_dataset, load_dataset
from app.services.rag_review_eval import (
    adjudicated_case_to_dict,
    compare_claim_reviews,
    load_adjudicated_reviews,
    load_claim_reviews,
    summarize_adjudicated_reviews,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("answers", type=Path)
    parser.add_argument("first_review", type=Path)
    parser.add_argument("second_review", type=Path)
    parser.add_argument("adjudications", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-fully-supported-claim-rate", type=float)
    parser.add_argument("--max-unsupported-claim-rate", type=float)
    parser.add_argument("--max-uncited-claim-rate", type=float)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    gate_options = (
        "min_fully_supported_claim_rate",
        "max_unsupported_claim_rate",
        "max_uncited_claim_rate",
    )
    for option in gate_options:
        value = getattr(args, option)
        if value is not None and not 0 <= value <= 1:
            parser.error(f"--{option.replace('_', '-')} must be between 0 and 1")

    cases = load_dataset(args.dataset)
    answers = load_answer_dataset(args.answers, cases)
    first = load_claim_reviews(args.first_review, answers)
    second = load_claim_reviews(args.second_review, answers)
    agreement = compare_claim_reviews(first, second)
    adjudicated = load_adjudicated_reviews(args.adjudications, first, second)
    summary = summarize_adjudicated_reviews(adjudicated)

    failures: list[str] = []
    gates = (
        (
            args.min_fully_supported_claim_rate,
            "fully_supported_claim_rate",
            "minimum fully supported claim rate",
            True,
        ),
        (
            args.max_unsupported_claim_rate,
            "unsupported_claim_rate",
            "maximum unsupported claim rate",
            False,
        ),
        (args.max_uncited_claim_rate, "uncited_claim_rate", "maximum uncited claim rate", False),
    )
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

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "answers_sha256": hashlib.sha256(args.answers.read_bytes()).hexdigest(),
        "first_review_sha256": hashlib.sha256(args.first_review.read_bytes()).hexdigest(),
        "second_review_sha256": hashlib.sha256(args.second_review.read_bytes()).hexdigest(),
        "adjudications_sha256": hashlib.sha256(args.adjudications.read_bytes()).hexdigest(),
        "reviewer_agreement": agreement["summary"],
        "review_disagreements": agreement["disagreements"],
        "summary": summary,
        "cases": [adjudicated_case_to_dict(review) for review in adjudicated],
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
