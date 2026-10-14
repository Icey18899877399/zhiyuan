"""Run the labeled dynamic-RAG retrieval evaluation against the configured database."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.services import embedding
from app.services.rag_eval import (
    CaseResult,
    RetrievedDocument,
    case_to_dict,
    load_dataset,
    summarize,
)
from app.services.retrieval import search_articles


async def evaluate(dataset: Path, *, top_k: int, mode: str) -> dict[str, Any]:
    cases = load_dataset(dataset)
    if mode == "keyword":
        embedding._singleton = embedding._DisabledClient()

    results: list[CaseResult] = []
    try:
        async with AsyncSessionLocal() as db:
            for case in cases:
                started = time.perf_counter()
                articles = await search_articles(
                    db,
                    case.question,
                    category=case.category,
                    top_k=top_k,
                )
                latency_ms = (time.perf_counter() - started) * 1000
                results.append(
                    CaseResult(
                        case=case,
                        retrieved=tuple(
                            RetrievedDocument(
                                source_url=article.source_url,
                                category=article.category,
                                title=article.title,
                            )
                            for article in articles
                        ),
                        latency_ms=latency_ms,
                    )
                )
    finally:
        await engine.dispose()

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "mode": mode,
        "top_k": top_k,
        "retrieval_config": {
            "embedding_provider": "disabled" if mode == "keyword" else settings.embedding_provider,
            "embedding_model": None if mode == "keyword" else settings.embedding_model,
            "time_decay_lambda": settings.time_decay_lambda,
        },
        "summary": summarize(results, top_k),
        "cases": [case_to_dict(result, top_k) for result in results],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="labeled JSONL evaluation dataset")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--mode",
        choices=("keyword", "configured"),
        default="keyword",
        help="keyword is local/offline; configured may call the configured embedding API",
    )
    parser.add_argument("--output", type=Path, help="optional path for the JSON report")
    parser.add_argument("--min-recall-at-k", type=float)
    parser.add_argument("--max-unanswerable-fpr", type=float)
    parser.add_argument("--max-category-violation-rate", type=float)
    parser.add_argument("--max-p95-ms", type=float)
    return parser


def _check_gates(report: dict[str, Any], args: argparse.Namespace) -> list[str]:
    summary = report["summary"]
    k = args.top_k
    failures: list[str] = []
    gates = (
        (args.min_recall_at_k, f"recall_at_{k}", "minimum Recall@K"),
        (
            args.max_unanswerable_fpr,
            "unanswerable_false_positive_rate",
            "maximum no-result false-positive rate",
        ),
        (
            args.max_category_violation_rate,
            "category_violation_rate",
            "maximum category violation rate",
        ),
        (args.max_p95_ms, "latency_ms.p95", "maximum p95 latency"),
    )
    for threshold, key, label in gates:
        if threshold is None:
            continue
        value: Any = summary
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            failures.append(f"{label}: metric unavailable")
        elif key.startswith("recall_") and value < threshold:
            failures.append(f"{label}: {value:.4f} < {threshold:.4f}")
        elif not key.startswith("recall_") and value > threshold:
            failures.append(f"{label}: {value:.4f} > {threshold:.4f}")
    return failures


async def _main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("--top-k must be greater than zero")
    for option in (
        "min_recall_at_k",
        "max_unanswerable_fpr",
        "max_category_violation_rate",
    ):
        value = getattr(args, option)
        if value is not None and not 0 <= value <= 1:
            parser.error(f"--{option.replace('_', '-')} must be between 0 and 1")
    if args.max_p95_ms is not None and args.max_p95_ms < 0:
        parser.error("--max-p95-ms must not be negative")

    report = await evaluate(args.dataset, top_k=args.top_k, mode=args.mode)
    failures = _check_gates(report, args)
    report["gates"] = {
        "status": "failed"
        if failures
        else "passed"
        if any(
            getattr(args, name) is not None
            for name in (
                "min_recall_at_k",
                "max_unanswerable_fpr",
                "max_category_violation_rate",
                "max_p95_ms",
            )
        )
        else "not_configured",
        "thresholds": {
            "min_recall_at_k": args.min_recall_at_k,
            "max_unanswerable_fpr": args.max_unanswerable_fpr,
            "max_category_violation_rate": args.max_category_violation_rate,
            "max_p95_ms": args.max_p95_ms,
        },
        "failures": failures,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
