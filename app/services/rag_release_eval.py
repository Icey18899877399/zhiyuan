"""Cross-check RAG evaluation artifacts before declaring acceptance readiness."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.services.rag_dataset_audit import REQUIRED_QUESTION_TAGS, SUPPORTED_CATEGORIES

REQUIRED_REPORT_GATES = {
    "retrieval_keyword": (
        "min_recall_at_k",
        "max_unanswerable_fpr",
        "max_category_violation_rate",
        "max_p95_ms",
    ),
    "retrieval_configured": (
        "min_recall_at_k",
        "max_unanswerable_fpr",
        "max_category_violation_rate",
        "max_p95_ms",
    ),
    "answer": (
        "min_citation_label_mapping_rate",
        "min_cited_source_precision",
        "min_cited_source_recall",
        "min_answerable_citation_coverage",
        "max_answerable_abstention_rate",
        "min_unanswerable_abstention_rate",
        "max_unanswerable_citation_rate",
    ),
    "agreement": ("min_observed_agreement", "min_cohens_kappa"),
    "adjudication": (
        "min_fully_supported_claim_rate",
        "max_unsupported_claim_rate",
        "max_uncited_claim_rate",
    ),
}


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_report(path: Path, name: str, checks: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        checks.append({"name": f"{name}_report_readable", "passed": False, "detail": str(exc)})
        return None
    if not isinstance(payload, dict):
        checks.append(
            {
                "name": f"{name}_report_object",
                "passed": False,
                "detail": "report root must be an object",
            }
        )
        return None
    checks.append({"name": f"{name}_report_readable", "passed": True})
    if payload.get("schema_version") != 1:
        checks.append(
            {
                "name": f"{name}_schema_version",
                "passed": False,
                "detail": f"expected schema_version 1, got {payload.get('schema_version')!r}",
            }
        )
    else:
        checks.append({"name": f"{name}_schema_version", "passed": True})
    return payload


def _add_check(
    checks: list[dict[str, Any]], name: str, passed: bool, detail: str | None = None
) -> None:
    item: dict[str, Any] = {"name": name, "passed": passed}
    if detail:
        item["detail"] = detail
    checks.append(item)


def _is_positive_count(value: Any) -> bool:
    return type(value) is int and value > 0


def _valid_threshold(name: str, value: Any) -> bool:
    if type(value) not in (int, float) or not math.isfinite(value):
        return False
    if name == "max_p95_ms":
        return value >= 0
    if name == "min_cohens_kappa":
        return -1 <= value <= 1
    return 0 <= value <= 1


def validate_acceptance_bundle(
    *,
    artifacts: dict[str, Path],
    reports: dict[str, Path],
    expected_case_ids: list[str],
) -> dict[str, Any]:
    """Validate provenance, required quality gates, and complete release-set coverage."""
    required_artifacts = {"dataset", "answers", "first_review", "second_review", "adjudications"}
    required_reports = {
        "dataset_audit",
        "retrieval_keyword",
        "retrieval_configured",
        "answer",
        "agreement",
        "adjudication",
    }
    checks: list[dict[str, Any]] = []

    missing_artifacts = sorted(required_artifacts - artifacts.keys())
    missing_reports = sorted(required_reports - reports.keys())
    _add_check(
        checks,
        "required_artifacts_present",
        not missing_artifacts,
        f"missing: {', '.join(missing_artifacts)}" if missing_artifacts else None,
    )
    _add_check(
        checks,
        "required_reports_present",
        not missing_reports,
        f"missing: {', '.join(missing_reports)}" if missing_reports else None,
    )
    if missing_artifacts or missing_reports:
        return {
            "status": "blocked",
            "case_count": len(expected_case_ids),
            "checks": checks,
            "blockers": [item for item in checks if not item["passed"]],
            "input_sha256": {},
            "stage_summaries": {},
        }

    input_hashes: dict[str, str] = {}
    unreadable_artifacts: list[str] = []
    for name, path in artifacts.items():
        try:
            input_hashes[name] = sha256_file(path)
        except OSError as exc:
            unreadable_artifacts.append(f"{name}: {exc}")
    _add_check(
        checks,
        "input_artifacts_readable",
        not unreadable_artifacts,
        "; ".join(unreadable_artifacts) if unreadable_artifacts else None,
    )
    if unreadable_artifacts:
        return {
            "status": "blocked",
            "case_count": len(expected_case_ids),
            "checks": checks,
            "blockers": [item for item in checks if not item["passed"]],
            "input_sha256": input_hashes,
            "stage_summaries": {},
        }

    loaded = {
        name: _read_report(path, name, checks)
        for name, path in reports.items()
        if name in required_reports
    }
    if any(loaded.get(name) is None for name in required_reports):
        return {
            "status": "blocked",
            "case_count": len(expected_case_ids),
            "checks": checks,
            "blockers": [item for item in checks if not item["passed"]],
            "input_sha256": input_hashes,
            "stage_summaries": {},
        }

    audit = loaded["dataset_audit"]
    retrieval_keyword = loaded["retrieval_keyword"]
    retrieval_configured = loaded["retrieval_configured"]
    answer = loaded["answer"]
    agreement = loaded["agreement"]
    adjudication = loaded["adjudication"]

    expected_hashes = {
        "dataset_audit": {"dataset_sha256": input_hashes["dataset"]},
        "retrieval_keyword": {"dataset_sha256": input_hashes["dataset"]},
        "retrieval_configured": {"dataset_sha256": input_hashes["dataset"]},
        "answer": {
            "dataset_sha256": input_hashes["dataset"],
            "answers_sha256": input_hashes["answers"],
        },
        "agreement": {
            "dataset_sha256": input_hashes["dataset"],
            "answers_sha256": input_hashes["answers"],
            "first_review_sha256": input_hashes["first_review"],
            "second_review_sha256": input_hashes["second_review"],
        },
        "adjudication": {
            "dataset_sha256": input_hashes["dataset"],
            "answers_sha256": input_hashes["answers"],
            "first_review_sha256": input_hashes["first_review"],
            "second_review_sha256": input_hashes["second_review"],
            "adjudications_sha256": input_hashes["adjudications"],
        },
    }
    for report_name, fields in expected_hashes.items():
        report = loaded[report_name]
        for field, expected_hash in fields.items():
            actual_hash = report.get(field)
            _add_check(
                checks,
                f"{report_name}_{field}_matches",
                actual_hash == expected_hash,
                None
                if actual_hash == expected_hash
                else f"expected current input hash {expected_hash}, got {actual_hash!r}",
            )

    for report_name, report, expected_mode in (
        ("retrieval_keyword", retrieval_keyword, "keyword"),
        ("retrieval_configured", retrieval_configured, "configured"),
    ):
        _add_check(
            checks,
            f"{report_name}_mode_matches",
            report.get("mode") == expected_mode,
            f"expected mode {expected_mode!r}, got {report.get('mode')!r}",
        )

    case_count = len(expected_case_ids)
    release_size_ok = 30 <= case_count <= 50
    _add_check(
        checks,
        "release_dataset_size_30_to_50",
        release_size_ok,
        f"expected 30-50 reviewed cases, got {case_count}",
    )
    expected_ids_are_valid = all(isinstance(case_id, str) for case_id in expected_case_ids)
    expected_ids_unique = expected_ids_are_valid and len(set(expected_case_ids)) == case_count
    _add_check(checks, "case_ids_unique", expected_ids_unique)
    _add_check(
        checks,
        "dataset_audit_case_count_matches",
        audit.get("case_count") == case_count,
        f"expected audit count {case_count}, got {audit.get('case_count')!r}",
    )

    category_counts = audit.get("category_counts", {})
    category_counts = category_counts if isinstance(category_counts, dict) else {}
    audit_categories = audit.get("required_categories", [])
    audit_categories = audit_categories if isinstance(audit_categories, list) else []
    missing_categories = [
        category
        for category in SUPPORTED_CATEGORIES
        if not _is_positive_count(category_counts.get(category))
    ]
    _add_check(
        checks,
        "dataset_audit_required_categories",
        not missing_categories and tuple(audit_categories) == SUPPORTED_CATEGORIES,
        f"missing or nonstandard category coverage: {', '.join(missing_categories) or 'required list differs'}"
        if missing_categories or tuple(audit_categories) != SUPPORTED_CATEGORIES
        else None,
    )
    tag_counts = audit.get("tag_counts", {})
    tag_counts = tag_counts if isinstance(tag_counts, dict) else {}
    missing_tags = [
        tag for tag in REQUIRED_QUESTION_TAGS if not _is_positive_count(tag_counts.get(tag))
    ]
    audit_required_tags = audit.get("required_tags", [])
    _add_check(
        checks,
        "dataset_audit_required_tags",
        not missing_tags
        and isinstance(audit_required_tags, list)
        and tuple(audit_required_tags) == REQUIRED_QUESTION_TAGS,
        f"missing or nonstandard tag coverage: {', '.join(missing_tags) or 'required list differs'}"
        if missing_tags
        or not isinstance(audit_required_tags, list)
        or tuple(audit_required_tags) != REQUIRED_QUESTION_TAGS
        else None,
    )
    _add_check(checks, "dataset_audit_passed", audit.get("status") == "passed")
    _add_check(
        checks,
        "dataset_contains_answerable_and_unanswerable",
        _is_positive_count(audit.get("answerable_case_count"))
        and _is_positive_count(audit.get("unanswerable_case_count")),
    )

    for report_name, report in (
        ("retrieval_keyword", retrieval_keyword),
        ("retrieval_configured", retrieval_configured),
        ("answer", answer),
        ("agreement", agreement),
        ("adjudication", adjudication),
    ):
        gates = report.get("gates")
        _add_check(
            checks,
            f"{report_name}_gate_passed",
            isinstance(gates, dict) and gates.get("status") == "passed",
            None
            if isinstance(gates, dict) and gates.get("status") == "passed"
            else f"gate status is {gates.get('status')!r}"
            if isinstance(gates, dict)
            else "gates object is missing",
        )
        thresholds = gates.get("thresholds", {}) if isinstance(gates, dict) else {}
        thresholds = thresholds if isinstance(thresholds, dict) else {}
        required_thresholds = REQUIRED_REPORT_GATES[report_name]
        missing_thresholds = [key for key in required_thresholds if thresholds.get(key) is None]
        _add_check(
            checks,
            f"{report_name}_required_thresholds_configured",
            not missing_thresholds,
            f"missing thresholds: {', '.join(missing_thresholds)}" if missing_thresholds else None,
        )
        invalid_thresholds = [
            key
            for key in required_thresholds
            if thresholds.get(key) is not None and not _valid_threshold(key, thresholds[key])
        ]
        _add_check(
            checks,
            f"{report_name}_thresholds_valid",
            not invalid_thresholds,
            f"invalid thresholds: {', '.join(invalid_thresholds)}" if invalid_thresholds else None,
        )
        gate_failures = gates.get("failures") if isinstance(gates, dict) else None
        _add_check(
            checks,
            f"{report_name}_has_no_gate_failures",
            isinstance(gate_failures, list) and not gate_failures,
            "gate failures must be an empty list"
            if not isinstance(gate_failures, list) or gate_failures
            else None,
        )

    for report_name, report in (
        ("retrieval_keyword", retrieval_keyword),
        ("retrieval_configured", retrieval_configured),
        ("answer", answer),
        ("adjudication", adjudication),
    ):
        report_cases = report.get("cases")
        report_ids = (
            [case.get("id") for case in report_cases if isinstance(case, dict)]
            if isinstance(report_cases, list)
            else []
        )
        report_ids_are_valid = all(isinstance(case_id, str) for case_id in report_ids)
        _add_check(
            checks,
            f"{report_name}_case_coverage_matches",
            report_ids_are_valid
            and expected_ids_unique
            and len(report_ids) == case_count
            and len(set(report_ids)) == case_count
            and set(report_ids) == set(expected_case_ids),
            f"expected {case_count} unique matching case IDs, got {len(report_ids)} records",
        )

    agreement_summary = agreement.get("summary", {})
    agreement_summary = agreement_summary if isinstance(agreement_summary, dict) else {}
    _add_check(
        checks,
        "agreement_case_count_matches",
        agreement_summary.get("case_count") == case_count,
        f"expected {case_count}, got {agreement_summary.get('case_count')!r}",
    )
    adjudication_summary = adjudication.get("summary", {})
    adjudication_summary = adjudication_summary if isinstance(adjudication_summary, dict) else {}
    _add_check(
        checks,
        "agreement_claim_count_matches_adjudication",
        agreement_summary.get("claim_count") == adjudication_summary.get("material_claim_count")
        and _is_positive_count(agreement_summary.get("claim_count")),
        "reviewer agreement and adjudication material claim counts differ or are empty",
    )
    _add_check(
        checks,
        "reviewer_agreement_kappa_available",
        type(agreement_summary.get("cohens_kappa")) in (int, float)
        and math.isfinite(agreement_summary.get("cohens_kappa")),
        "Cohen's kappa is unavailable",
    )
    _add_check(
        checks,
        "reviewer_claims_reviewed",
        _is_positive_count(agreement_summary.get("claim_count"))
        and _is_positive_count(adjudication_summary.get("material_claim_count")),
        "no reviewed material claims found",
    )

    stage_summaries = {
        "retrieval_keyword": retrieval_keyword.get("summary", {}),
        "retrieval_configured": retrieval_configured.get("summary", {}),
        "answer": answer.get("summary", {}),
        "reviewer_agreement": agreement_summary,
        "adjudication": adjudication.get("summary", {}),
    }
    blockers = [item for item in checks if not item["passed"]]
    return {
        "status": "blocked" if blockers else "ready",
        "case_count": case_count,
        "checks": checks,
        "blockers": blockers,
        "input_sha256": input_hashes,
        "stage_summaries": stage_summaries,
    }
