"""Human-reviewed, claim-level grounding metrics for saved RAG answers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.rag_eval import CITATION_PATTERN, AnswerCaseResult

JUDGMENTS = {"supported", "partially_supported", "unsupported", "uncited"}


@dataclass(frozen=True)
class ReviewedClaim:
    claim_id: str
    text: str
    citations: tuple[str, ...]
    source_urls: tuple[str, ...]
    judgment: str


@dataclass(frozen=True)
class CaseReview:
    answer: AnswerCaseResult
    claims: tuple[ReviewedClaim, ...]


@dataclass(frozen=True)
class AdjudicatedClaim:
    claim: ReviewedClaim
    first_judgment: str
    second_judgment: str
    rationale: str


@dataclass(frozen=True)
class AdjudicatedCaseReview:
    answer: AnswerCaseResult
    adjudicator: str
    claims: tuple[AdjudicatedClaim, ...]


def load_claim_reviews(path: str | Path, answers: list[AnswerCaseResult]) -> list[CaseReview]:
    """Load complete human claim reviews and validate citations against saved responses."""
    expected = {answer.case.case_id: answer for answer in answers}
    reviews: dict[str, CaseReview] = {}
    with Path(path).open(encoding="utf-8") as review_file:
        for line_number, line in enumerate(review_file, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number}: each JSON value must be an object")

            case_id = payload.get("id")
            if not isinstance(case_id, str) or case_id not in expected:
                raise ValueError(f"line {line_number}: id must match an answer case")
            if case_id in reviews:
                raise ValueError(f"line {line_number}: duplicate review id {case_id!r}")
            if payload.get("reviewed_all_material_claims") is not True:
                raise ValueError(f"line {line_number}: reviewed_all_material_claims must be true")
            claims_payload = payload.get("claims")
            if not isinstance(claims_payload, list):
                raise ValueError(f"line {line_number}: claims must be a list")

            answer = expected[case_id]
            answer_labels = set(CITATION_PATTERN.findall(answer.answer))
            label_sources: dict[str, set[str]] = {}
            for item in answer.retrieved:
                for citation in item["citations"]:
                    label_sources.setdefault(citation, set()).add(item["source_url"])

            claims: list[ReviewedClaim] = []
            seen_claim_ids: set[str] = set()
            for claim_payload in claims_payload:
                if not isinstance(claim_payload, dict):
                    raise ValueError(f"line {line_number}: each claim must be an object")
                claim_id = claim_payload.get("claim_id")
                text = claim_payload.get("text")
                citations = claim_payload.get("citations")
                judgment = claim_payload.get("judgment")
                if not isinstance(claim_id, str) or not claim_id.strip():
                    raise ValueError(f"line {line_number}: claim_id must be a non-empty string")
                claim_id = claim_id.strip()
                if claim_id in seen_claim_ids:
                    raise ValueError(f"line {line_number}: duplicate claim_id {claim_id!r}")
                seen_claim_ids.add(claim_id)
                if not isinstance(text, str) or not text.strip():
                    raise ValueError(f"line {line_number}: claim text must be a non-empty string")
                if not isinstance(citations, list) or any(
                    not isinstance(citation, str) or not CITATION_PATTERN.fullmatch(citation)
                    for citation in citations
                ):
                    raise ValueError(f"line {line_number}: citations must be valid citation labels")
                if len(set(citations)) != len(citations):
                    raise ValueError(f"line {line_number}: claim citations must be unique")
                if not isinstance(judgment, str) or judgment not in JUDGMENTS:
                    raise ValueError(
                        f"line {line_number}: judgment must be one of {', '.join(sorted(JUDGMENTS))}"
                    )
                if (judgment == "uncited") != (len(citations) == 0):
                    raise ValueError(
                        f"line {line_number}: uncited claims must have no citations; other judgments require citations"
                    )

                source_urls: set[str] = set()
                for citation in citations:
                    if citation not in answer_labels:
                        raise ValueError(
                            f"line {line_number}: claim citation {citation} does not appear in the answer"
                        )
                    mapped_sources = label_sources.get(citation, set())
                    if len(mapped_sources) != 1:
                        raise ValueError(
                            f"line {line_number}: claim citation {citation} must map to exactly one source"
                        )
                    source_urls.update(mapped_sources)

                claims.append(
                    ReviewedClaim(
                        claim_id=claim_id,
                        text=text.strip(),
                        citations=tuple(citations),
                        source_urls=tuple(sorted(source_urls)),
                        judgment=judgment,
                    )
                )

            reviews[case_id] = CaseReview(answer=answer, claims=tuple(claims))

    missing = sorted(set(expected) - set(reviews))
    if missing:
        raise ValueError(f"review dataset is missing case ids: {', '.join(missing)}")
    return [reviews[answer.case.case_id] for answer in answers]


def _summarize_subset(reviews: list[CaseReview]) -> dict[str, Any]:
    claims = [claim for review in reviews for claim in review.claims]
    cited = [claim for claim in claims if claim.judgment != "uncited"]
    count = len(claims)
    cited_count = len(cited)
    counts = {
        judgment: sum(claim.judgment == judgment for claim in claims) for judgment in JUDGMENTS
    }
    return {
        "case_count": len(reviews),
        "material_claim_count": count,
        "cited_claim_count": cited_count,
        "supported_claim_count": counts["supported"],
        "partially_supported_claim_count": counts["partially_supported"],
        "unsupported_claim_count": counts["unsupported"],
        "uncited_claim_count": counts["uncited"],
        "claim_citation_coverage_rate": cited_count / count if count else None,
        "fully_supported_claim_rate": counts["supported"] / count if count else None,
        "fully_supported_cited_claim_rate": (
            counts["supported"] / cited_count if cited_count else None
        ),
        "partially_supported_claim_rate": counts["partially_supported"] / count if count else None,
        "unsupported_claim_rate": counts["unsupported"] / count if count else None,
        "uncited_claim_rate": counts["uncited"] / count if count else None,
    }


def summarize_claim_reviews(reviews: list[CaseReview]) -> dict[str, Any]:
    """Summarize adjudicated claim grounding and split by category/tag."""
    summary = _summarize_subset(reviews)
    by_category: dict[str, list[CaseReview]] = {}
    by_tag: dict[str, list[CaseReview]] = {}
    for review in reviews:
        by_category.setdefault(review.answer.case.category or "unfiltered", []).append(review)
        for tag in review.answer.case.tags:
            by_tag.setdefault(tag, []).append(review)
    summary["by_category"] = {
        category: _summarize_subset(group) for category, group in sorted(by_category.items())
    }
    summary["by_tag"] = {tag: _summarize_subset(group) for tag, group in sorted(by_tag.items())}
    return summary


def review_case_to_dict(review: CaseReview) -> dict[str, Any]:
    return {
        "id": review.answer.case.case_id,
        "category": review.answer.case.category,
        "tags": list(review.answer.case.tags),
        "reviewed_all_material_claims": True,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "text": claim.text,
                "citations": list(claim.citations),
                "source_urls": list(claim.source_urls),
                "judgment": claim.judgment,
            }
            for claim in review.claims
        ],
    }


def _agreement_summary(
    pairs: list[tuple[str, str | None, tuple[str, ...], str, str, str]],
) -> dict[str, Any]:
    judgments = ("supported", "partially_supported", "unsupported", "uncited")
    matrix = {left: {right: 0 for right in judgments} for left in judgments}
    left_counts = {judgment: 0 for judgment in judgments}
    right_counts = {judgment: 0 for judgment in judgments}
    for _, _, _, _, left, right in pairs:
        matrix[left][right] += 1
        left_counts[left] += 1
        right_counts[right] += 1

    claim_count = len(pairs)
    agreement_count = sum(matrix[judgment][judgment] for judgment in judgments)
    observed = agreement_count / claim_count if claim_count else None
    expected = (
        sum(left_counts[label] * right_counts[label] for label in judgments) / claim_count**2
        if claim_count
        else None
    )
    kappa = (
        (observed - expected) / (1 - expected)
        if observed is not None and expected is not None and expected < 1
        else None
    )
    return {
        "case_count": len({pair[0] for pair in pairs}),
        "claim_count": claim_count,
        "agreement_count": agreement_count,
        "observed_agreement_rate": observed,
        "cohens_kappa": kappa,
        "confusion_matrix": matrix,
    }


def compare_claim_reviews(first: list[CaseReview], second: list[CaseReview]) -> dict[str, Any]:
    """Compare independent reviews after enforcing identical claim units and citations."""
    first_by_case = {review.answer.case.case_id: review for review in first}
    second_by_case = {review.answer.case.case_id: review for review in second}
    if first_by_case.keys() != second_by_case.keys():
        missing_first = sorted(second_by_case.keys() - first_by_case.keys())
        missing_second = sorted(first_by_case.keys() - second_by_case.keys())
        raise ValueError(
            "review case IDs differ; "
            f"missing from first: {', '.join(missing_first) or 'none'}; "
            f"missing from second: {', '.join(missing_second) or 'none'}"
        )

    pairs: list[tuple[str, str | None, tuple[str, ...], str, str, str]] = []
    for case_id in first_by_case:
        first_review = first_by_case[case_id]
        second_review = second_by_case[case_id]
        first_claims = {claim.claim_id: claim for claim in first_review.claims}
        second_claims = {claim.claim_id: claim for claim in second_review.claims}
        if first_claims.keys() != second_claims.keys():
            raise ValueError(f"claim IDs differ for case {case_id!r}")
        for claim_id, first_claim in first_claims.items():
            second_claim = second_claims[claim_id]
            if first_claim.text != second_claim.text:
                raise ValueError(f"claim text differs for {case_id!r}/{claim_id!r}")
            if first_claim.citations != second_claim.citations:
                raise ValueError(f"claim citations differ for {case_id!r}/{claim_id!r}")
            pairs.append(
                (
                    case_id,
                    first_review.answer.case.category,
                    first_review.answer.case.tags,
                    claim_id,
                    first_claim.judgment,
                    second_claim.judgment,
                )
            )

    by_category: dict[str, list[tuple[str, str | None, tuple[str, ...], str, str, str]]] = {}
    by_tag: dict[str, list[tuple[str, str | None, tuple[str, ...], str, str, str]]] = {}
    for pair in pairs:
        case_id, category, tags, *_ = pair
        by_category.setdefault(category or "unfiltered", []).append(pair)
        for tag in tags:
            by_tag.setdefault(tag, []).append(pair)

    disagreements = [
        {"id": case_id, "claim_id": claim_id, "first": first_judgment, "second": second_judgment}
        for case_id, _, _, claim_id, first_judgment, second_judgment in pairs
        if first_judgment != second_judgment
    ]
    return {
        "summary": {
            **_agreement_summary(pairs),
            "by_category": {
                category: _agreement_summary(group)
                for category, group in sorted(by_category.items())
            },
            "by_tag": {tag: _agreement_summary(group) for tag, group in sorted(by_tag.items())},
        },
        "disagreements": disagreements,
    }


def build_adjudication_template(
    first: list[CaseReview], second: list[CaseReview]
) -> list[dict[str, Any]]:
    """Create a JSONL-ready template prefilled with both reviewers' judgments."""
    compare_claim_reviews(first, second)
    second_by_case = {review.answer.case.case_id: review for review in second}
    template: list[dict[str, Any]] = []
    for first_review in first:
        case_id = first_review.answer.case.case_id
        second_claims = {claim.claim_id: claim for claim in second_by_case[case_id].claims}
        claims = []
        for first_claim in first_review.claims:
            second_claim = second_claims[first_claim.claim_id]
            agreed = first_claim.judgment == second_claim.judgment
            claims.append(
                {
                    "claim_id": first_claim.claim_id,
                    "text": first_claim.text,
                    "citations": list(first_claim.citations),
                    "source_urls": list(first_claim.source_urls),
                    "reviewer_a_judgment": first_claim.judgment,
                    "reviewer_b_judgment": second_claim.judgment,
                    "adjudicated_judgment": first_claim.judgment if agreed else None,
                    "rationale": "" if agreed else "",
                }
            )
        template.append(
            {
                "id": case_id,
                "adjudicator": "",
                "reviewed_all_material_claims": True,
                "claims": claims,
            }
        )
    return template


def load_adjudicated_reviews(
    path: str | Path,
    first: list[CaseReview],
    second: list[CaseReview],
) -> list[AdjudicatedCaseReview]:
    """Load final judgments and require reasons for any decision overriding reviewers."""
    compare_claim_reviews(first, second)
    first_by_case = {review.answer.case.case_id: review for review in first}
    second_by_case = {review.answer.case.case_id: review for review in second}
    decisions: dict[str, tuple[str, dict[str, dict[str, Any]]]] = {}

    with Path(path).open(encoding="utf-8") as decision_file:
        for line_number, line in enumerate(decision_file, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"line {line_number}: each JSON value must be an object")
            case_id = payload.get("id")
            if not isinstance(case_id, str) or case_id not in first_by_case:
                raise ValueError(f"line {line_number}: id must match a reviewed case")
            if case_id in decisions:
                raise ValueError(f"line {line_number}: duplicate adjudication id {case_id!r}")
            adjudicator = payload.get("adjudicator")
            if not isinstance(adjudicator, str) or not adjudicator.strip():
                raise ValueError(f"line {line_number}: adjudicator must be a non-empty string")
            if payload.get("reviewed_all_material_claims") is not True:
                raise ValueError(f"line {line_number}: reviewed_all_material_claims must be true")
            claim_payloads = payload.get("claims")
            if not isinstance(claim_payloads, list):
                raise ValueError(f"line {line_number}: claims must be a list")
            claim_map: dict[str, dict[str, Any]] = {}
            for claim_payload in claim_payloads:
                if not isinstance(claim_payload, dict):
                    raise ValueError(f"line {line_number}: each claim must be an object")
                claim_id = claim_payload.get("claim_id")
                if not isinstance(claim_id, str) or not claim_id.strip():
                    raise ValueError(f"line {line_number}: claim_id must be a non-empty string")
                claim_id = claim_id.strip()
                if claim_id in claim_map:
                    raise ValueError(f"line {line_number}: duplicate claim_id {claim_id!r}")
                claim_map[claim_id] = claim_payload
            decisions[case_id] = (adjudicator.strip(), claim_map)

    missing_cases = sorted(first_by_case.keys() - decisions.keys())
    extra_claims = sorted(decisions.keys() - first_by_case.keys())
    if missing_cases or extra_claims:
        raise ValueError(
            "adjudication case IDs do not match; "
            f"missing: {', '.join(missing_cases) or 'none'}; "
            f"unexpected: {', '.join(extra_claims) or 'none'}"
        )

    adjudicated: list[AdjudicatedCaseReview] = []
    for case_id, first_review in first_by_case.items():
        adjudicator, claim_map = decisions[case_id]
        first_claims = {claim.claim_id: claim for claim in first_review.claims}
        second_claims = {claim.claim_id: claim for claim in second_by_case[case_id].claims}
        missing_claims = sorted(first_claims.keys() - claim_map.keys())
        unexpected_claims = sorted(claim_map.keys() - first_claims.keys())
        if missing_claims or unexpected_claims:
            raise ValueError(
                f"adjudication claim IDs do not match for case {case_id!r}; "
                f"missing: {', '.join(missing_claims) or 'none'}; "
                f"unexpected: {', '.join(unexpected_claims) or 'none'}"
            )

        claims: list[AdjudicatedClaim] = []
        for claim_id, first_claim in first_claims.items():
            second_claim = second_claims[claim_id]
            decision = claim_map[claim_id]
            if decision.get("text") != first_claim.text:
                raise ValueError(f"adjudicated claim text differs for {case_id!r}/{claim_id!r}")
            if decision.get("citations") != list(first_claim.citations):
                raise ValueError(f"adjudicated claim citations differ for {case_id!r}/{claim_id!r}")
            if decision.get("reviewer_a_judgment") != first_claim.judgment:
                raise ValueError(f"reviewer A judgment was changed for {case_id!r}/{claim_id!r}")
            if decision.get("reviewer_b_judgment") != second_claim.judgment:
                raise ValueError(f"reviewer B judgment was changed for {case_id!r}/{claim_id!r}")
            judgment = decision.get("adjudicated_judgment")
            if not isinstance(judgment, str) or judgment not in JUDGMENTS:
                raise ValueError(
                    f"adjudicated judgment must be one of {', '.join(sorted(JUDGMENTS))}"
                )
            if (judgment == "uncited") != (len(first_claim.citations) == 0):
                raise ValueError(
                    f"adjudicated judgment uncited status conflicts with citations for {case_id!r}/{claim_id!r}"
                )
            rationale = decision.get("rationale")
            if not isinstance(rationale, str):
                raise ValueError(
                    f"adjudication rationale must be a string for {case_id!r}/{claim_id!r}"
                )
            if (
                judgment not in {first_claim.judgment, second_claim.judgment}
                and not rationale.strip()
            ):
                raise ValueError(
                    f"adjudication rationale is required when overriding both reviewers for {case_id!r}/{claim_id!r}"
                )
            if first_claim.judgment != second_claim.judgment and not rationale.strip():
                raise ValueError(
                    f"adjudication rationale is required for disagreement {case_id!r}/{claim_id!r}"
                )
            claims.append(
                AdjudicatedClaim(
                    claim=ReviewedClaim(
                        claim_id=claim_id,
                        text=first_claim.text,
                        citations=first_claim.citations,
                        source_urls=first_claim.source_urls,
                        judgment=judgment,
                    ),
                    first_judgment=first_claim.judgment,
                    second_judgment=second_claim.judgment,
                    rationale=rationale.strip(),
                )
            )
        adjudicated.append(
            AdjudicatedCaseReview(
                answer=first_review.answer,
                adjudicator=adjudicator,
                claims=tuple(claims),
            )
        )
    return adjudicated


def summarize_adjudicated_reviews(
    reviews: list[AdjudicatedCaseReview],
) -> dict[str, Any]:
    final_reviews = [
        CaseReview(
            answer=review.answer,
            claims=tuple(claim.claim for claim in review.claims),
        )
        for review in reviews
    ]
    return summarize_claim_reviews(final_reviews)


def adjudicated_case_to_dict(review: AdjudicatedCaseReview) -> dict[str, Any]:
    return {
        "id": review.answer.case.case_id,
        "category": review.answer.case.category,
        "tags": list(review.answer.case.tags),
        "adjudicator": review.adjudicator,
        "claims": [
            {
                "claim_id": item.claim.claim_id,
                "text": item.claim.text,
                "citations": list(item.claim.citations),
                "source_urls": list(item.claim.source_urls),
                "reviewer_a_judgment": item.first_judgment,
                "reviewer_b_judgment": item.second_judgment,
                "adjudicated_judgment": item.claim.judgment,
                "rationale": item.rationale,
            }
            for item in review.claims
        ],
    }
