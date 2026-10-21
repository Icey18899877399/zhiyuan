"""Audit golden-set size, category/tag coverage, and annotation quality."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.rag_dataset_audit import (
    REQUIRED_QUESTION_TAGS,
    SUPPORTED_CATEGORIES,
    audit_dataset,
)
from app.services.rag_eval import load_dataset


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="labeled evaluation JSONL")
    parser.add_argument("--min-cases", type=int, default=30)
    parser.add_argument("--max-cases", type=int, default=50)
    parser.add_argument(
        "--required-categories",
        nargs="*",
        default=list(SUPPORTED_CATEGORIES),
    )
    parser.add_argument(
        "--required-tags",
        nargs="*",
        default=list(REQUIRED_QUESTION_TAGS),
    )
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.min_cases < 1 or args.max_cases < args.min_cases:
        parser.error("case-count bounds must satisfy 1 <= --min-cases <= --max-cases")
    if len(set(args.required_categories)) != len(args.required_categories):
        parser.error("--required-categories must not contain duplicates")
    if len(set(args.required_tags)) != len(args.required_tags):
        parser.error("--required-tags must not contain duplicates")

    cases = load_dataset(args.dataset)
    audit = audit_dataset(
        cases,
        min_cases=args.min_cases,
        max_cases=args.max_cases,
        required_categories=tuple(args.required_categories),
        required_tags=tuple(args.required_tags),
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "dataset": str(args.dataset),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        **audit,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 1 if audit["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
