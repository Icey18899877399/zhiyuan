"""Measure agreement between two independent RAG claim-review sets."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.services.rag_eval import load_answer_dataset, load_dataset
from app.services.rag_review_eval import compare_claim_reviews, load_claim_reviews


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="labeled retrieval evaluation JSONL")
    parser.add_argument("answers", type=Path, help="saved ChatResponse-like answers JSONL")
    parser.add_argument("first_review", type=Path, help="first reviewer's JSONL")
    parser.add_argument("second_review", type=Path, help="second reviewer's JSONL")
    parser.add_argument("--output", type=Path, help="optional path for the JSON report")
    parser.add_argument("--min-observed-agreement", type=float)
    parser.add_argument("--min-cohens-kappa", type=float)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.min_observed_agreement is not None and not 0 <= args.min_observed_agreement <= 1:
        parser.error("--min-observed-agreement must be between 0 and 1")
    if args.min_cohens_kappa is not None and not -1 <= args.min_cohens_kappa <= 1:
        parser.error("--min-cohens-kappa must be between -1 and 1")

    cases = load_dataset(args.dataset)
    answers = load_answer_dataset(args.answers, cases)
    first = load_claim_reviews(args.first_review, answers)
    second = load_claim_reviews(args.second_review, answers)
    comparison = compare_claim_reviews(first, second)
    summary = comparison["summary"]
    failures: list[str] = []
    for key, threshold, label in (
        ("observed_agreement_rate", args.min_observed_agreement, "minimum observed agreement"),
        ("cohens_kappa", args.min_cohens_kappa, "minimum Cohen's kappa"),
    ):
        if threshold is None:
            continue
        value = summary[key]
        if value is None:
            failures.append(f"{label}: metric unavailable")
        elif value < threshold:
            failures.append(f"{label}: {value:.4f} < {threshold:.4f}")

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "answers_sha256": hashlib.sha256(args.answers.read_bytes()).hexdigest(),
        "first_review_sha256": hashlib.sha256(args.first_review.read_bytes()).hexdigest(),
        "second_review_sha256": hashlib.sha256(args.second_review.read_bytes()).hexdigest(),
        **comparison,
        "gates": {
            "status": "failed"
            if failures
            else "passed"
            if args.min_observed_agreement is not None or args.min_cohens_kappa is not None
            else "not_configured",
            "thresholds": {
                "min_observed_agreement": args.min_observed_agreement,
                "min_cohens_kappa": args.min_cohens_kappa,
            },
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
