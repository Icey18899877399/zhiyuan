from __future__ import annotations

import hashlib
import json

from app.services.rag_dataset_audit import REQUIRED_QUESTION_TAGS, SUPPORTED_CATEGORIES
from app.services.rag_release_eval import validate_acceptance_bundle


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_bundle(tmp_path):
    case_ids = [f"case-{index:02d}" for index in range(30)]
    artifacts = {}
    for name in ("dataset", "answers", "first_review", "second_review", "adjudications"):
        path = tmp_path / f"{name}.jsonl"
        path.write_text(f"{name}\n", encoding="utf-8")
        artifacts[name] = path
    hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in artifacts.items()
    }

    gates = {
        "retrieval_keyword": {
            "min_recall_at_k": 0.8,
            "max_unanswerable_fpr": 0,
            "max_category_violation_rate": 0,
            "max_p95_ms": 1000,
        },
        "retrieval_configured": {
            "min_recall_at_k": 0.8,
            "max_unanswerable_fpr": 0,
            "max_category_violation_rate": 0,
            "max_p95_ms": 1000,
        },
        "answer": {
            "min_citation_label_mapping_rate": 1,
            "min_cited_source_precision": 0.9,
            "min_cited_source_recall": 0.9,
            "min_answerable_citation_coverage": 0.9,
            "max_answerable_abstention_rate": 0,
            "min_unanswerable_abstention_rate": 1,
            "max_unanswerable_citation_rate": 0,
        },
        "agreement": {"min_observed_agreement": 0.9, "min_cohens_kappa": 0.8},
        "adjudication": {
            "min_fully_supported_claim_rate": 0.9,
            "max_unsupported_claim_rate": 0,
            "max_uncited_claim_rate": 0,
        },
    }
    common_gates = {
        name: {"status": "passed", "thresholds": thresholds, "failures": []}
        for name, thresholds in gates.items()
    }
    retrieved_cases = [{"id": case_id} for case_id in case_ids]
    reports_payload = {
        "dataset_audit": {
            "schema_version": 1,
            "dataset_sha256": hashes["dataset"],
            "status": "passed",
            "case_count": 30,
            "answerable_case_count": 24,
            "unanswerable_case_count": 6,
            "category_counts": {category: 6 for category in SUPPORTED_CATEGORIES},
            "tag_counts": {tag: 5 for tag in REQUIRED_QUESTION_TAGS},
            "required_categories": list(SUPPORTED_CATEGORIES),
            "required_tags": list(REQUIRED_QUESTION_TAGS),
        },
        "retrieval_keyword": {
            "schema_version": 1,
            "dataset_sha256": hashes["dataset"],
            "mode": "keyword",
            "summary": {"recall_at_5": 0.95},
            "cases": retrieved_cases,
            "gates": common_gates["retrieval_keyword"],
        },
        "retrieval_configured": {
            "schema_version": 1,
            "dataset_sha256": hashes["dataset"],
            "mode": "configured",
            "summary": {"recall_at_5": 0.95},
            "cases": retrieved_cases,
            "gates": common_gates["retrieval_configured"],
        },
        "answer": {
            "schema_version": 1,
            "dataset_sha256": hashes["dataset"],
            "answers_sha256": hashes["answers"],
            "summary": {"answerable_citation_coverage_rate": 0.95},
            "cases": retrieved_cases,
            "gates": common_gates["answer"],
        },
        "agreement": {
            "schema_version": 1,
            "dataset_sha256": hashes["dataset"],
            "answers_sha256": hashes["answers"],
            "first_review_sha256": hashes["first_review"],
            "second_review_sha256": hashes["second_review"],
            "summary": {
                "case_count": 30,
                "claim_count": 60,
                "cohens_kappa": 0.9,
                "observed_agreement_rate": 0.95,
            },
            "gates": common_gates["agreement"],
        },
        "adjudication": {
            "schema_version": 1,
            "dataset_sha256": hashes["dataset"],
            "answers_sha256": hashes["answers"],
            "first_review_sha256": hashes["first_review"],
            "second_review_sha256": hashes["second_review"],
            "adjudications_sha256": hashes["adjudications"],
            "summary": {"material_claim_count": 60, "fully_supported_claim_rate": 0.95},
            "cases": retrieved_cases,
            "gates": common_gates["adjudication"],
        },
    }
    reports = {}
    for name, payload in reports_payload.items():
        path = tmp_path / f"{name}-report.json"
        _write_json(path, payload)
        reports[name] = path
    return artifacts, reports, case_ids, reports_payload


def test_acceptance_bundle_is_ready_when_reports_are_gated_and_provenance_matches(tmp_path) -> None:
    artifacts, reports, case_ids, _ = _make_bundle(tmp_path)

    result = validate_acceptance_bundle(
        artifacts=artifacts,
        reports=reports,
        expected_case_ids=case_ids,
    )

    assert result["status"] == "ready"
    assert result["case_count"] == 30
    assert result["blockers"] == []
    assert result["stage_summaries"]["reviewer_agreement"]["cohens_kappa"] == 0.9
    assert "retrieval_keyword" in result["stage_summaries"]
    assert "retrieval_configured" in result["stage_summaries"]


def test_acceptance_bundle_blocks_stale_input_and_unconfigured_gates(tmp_path) -> None:
    artifacts, reports, case_ids, payloads = _make_bundle(tmp_path)
    artifacts["answers"].write_text("changed after evaluation\n", encoding="utf-8")
    payloads["agreement"]["gates"]["status"] = "not_configured"
    _write_json(reports["agreement"], payloads["agreement"])

    result = validate_acceptance_bundle(
        artifacts=artifacts,
        reports=reports,
        expected_case_ids=case_ids,
    )

    failed_names = {item["name"] for item in result["blockers"]}
    assert result["status"] == "blocked"
    assert "answer_answers_sha256_matches" in failed_names
    assert "agreement_gate_passed" in failed_names


def test_acceptance_bundle_requires_all_configured_release_thresholds(tmp_path) -> None:
    artifacts, reports, case_ids, payloads = _make_bundle(tmp_path)
    del payloads["answer"]["gates"]["thresholds"]["min_cited_source_recall"]
    _write_json(reports["answer"], payloads["answer"])

    result = validate_acceptance_bundle(
        artifacts=artifacts,
        reports=reports,
        expected_case_ids=case_ids,
    )

    assert result["status"] == "blocked"
    threshold_check = next(
        item
        for item in result["blockers"]
        if item["name"] == "answer_required_thresholds_configured"
    )
    assert "min_cited_source_recall" in threshold_check["detail"]


def test_acceptance_bundle_rejects_wrong_retrieval_mode_and_incomplete_ids(tmp_path) -> None:
    artifacts, reports, case_ids, payloads = _make_bundle(tmp_path)
    payloads["retrieval_configured"]["mode"] = "keyword"
    payloads["retrieval_keyword"]["cases"].pop()
    _write_json(reports["retrieval_configured"], payloads["retrieval_configured"])
    _write_json(reports["retrieval_keyword"], payloads["retrieval_keyword"])

    result = validate_acceptance_bundle(
        artifacts=artifacts,
        reports=reports,
        expected_case_ids=case_ids,
    )

    failed_names = {item["name"] for item in result["blockers"]}
    assert "retrieval_configured_mode_matches" in failed_names
    assert "retrieval_keyword_case_coverage_matches" in failed_names


def test_acceptance_bundle_requires_audit_case_count_to_match_dataset(tmp_path) -> None:
    artifacts, reports, case_ids, payloads = _make_bundle(tmp_path)
    payloads["dataset_audit"]["case_count"] = 29
    _write_json(reports["dataset_audit"], payloads["dataset_audit"])

    result = validate_acceptance_bundle(
        artifacts=artifacts,
        reports=reports,
        expected_case_ids=case_ids,
    )

    assert result["status"] == "blocked"
    assert "dataset_audit_case_count_matches" in {item["name"] for item in result["blockers"]}
