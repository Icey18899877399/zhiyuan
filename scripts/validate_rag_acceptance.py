"""Validate that all dynamic-RAG acceptance reports belong to one release bundle."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.rag_eval import load_dataset
from app.services.rag_release_eval import sha256_file, validate_acceptance_bundle


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("answers", type=Path)
    parser.add_argument("first_review", type=Path)
    parser.add_argument("second_review", type=Path)
    parser.add_argument("adjudications", type=Path)
    parser.add_argument("--dataset-audit", type=Path, required=True)
    parser.add_argument("--retrieval-keyword-report", type=Path, required=True)
    parser.add_argument("--retrieval-configured-report", type=Path, required=True)
    parser.add_argument("--answer-report", type=Path, required=True)
    parser.add_argument("--agreement-report", type=Path, required=True)
    parser.add_argument("--adjudication-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="optional final acceptance report path")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    artifacts = {
        "dataset": args.dataset,
        "answers": args.answers,
        "first_review": args.first_review,
        "second_review": args.second_review,
        "adjudications": args.adjudications,
    }
    reports = {
        "dataset_audit": args.dataset_audit,
        "retrieval_keyword": args.retrieval_keyword_report,
        "retrieval_configured": args.retrieval_configured_report,
        "answer": args.answer_report,
        "agreement": args.agreement_report,
        "adjudication": args.adjudication_report,
    }

    try:
        cases = load_dataset(args.dataset)
        result = validate_acceptance_bundle(
            artifacts=artifacts,
            reports=reports,
            expected_case_ids=[case.case_id for case in cases],
        )
    except (OSError, ValueError) as exc:
        result = {
            "status": "blocked",
            "case_count": 0,
            "checks": [{"name": "input_validation", "passed": False, "detail": str(exc)}],
            "blockers": [{"name": "input_validation", "passed": False, "detail": str(exc)}],
            "input_sha256": {},
            "stage_summaries": {},
        }

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "offline_metric_bundle",
        "live_end_to_end_status": "not_evaluated_by_this_tool",
        **result,
        "report_sha256": {
            name: sha256_file(path) for name, path in reports.items() if path.is_file()
        },
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
