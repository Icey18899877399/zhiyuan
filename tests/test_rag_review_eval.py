from __future__ import annotations

import json

import pytest

from app.services.rag_eval import AnswerCaseResult, EvalCase
from app.services.rag_review_eval import (
    build_adjudication_template,
    compare_claim_reviews,
    load_adjudicated_reviews,
    load_claim_reviews,
    review_case_to_dict,
    summarize_adjudicated_reviews,
    summarize_claim_reviews,
)


def _answer(case_id: str, category: str | None, tags: tuple[str, ...]) -> AnswerCaseResult:
    return AnswerCaseResult(
        case=EvalCase(
            case_id=case_id,
            question=f"question {case_id}",
            relevant_source_urls=("https://source.test/notice",),
            category=category,
            tags=tags,
        ),
        answer_mode="llm",
        answer="政策见[学业-1]，另见[学业-2]。",
        retrieved=(
            {"source_url": "https://source.test/notice", "citations": ["[学业-1]"]},
            {"source_url": "https://source.test/other", "citations": ["[学业-2]"]},
        ),
    )


def test_claim_review_metrics_validate_and_report_human_judgments(tmp_path) -> None:
    answers = [
        _answer("one", "学业", ("direct",)),
        _answer("two", None, ("paraphrase",)),
    ]
    review_file = tmp_path / "reviews.jsonl"
    review_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "one",
                        "reviewed_all_material_claims": True,
                        "claims": [
                            {
                                "claim_id": "c1",
                                "text": "材料要求见通知。",
                                "citations": ["[学业-1]"],
                                "judgment": "supported",
                            },
                            {
                                "claim_id": "c2",
                                "text": "系统自动开放报名。",
                                "citations": ["[学业-2]"],
                                "judgment": "unsupported",
                            },
                            {
                                "claim_id": "c3",
                                "text": "报名很方便。",
                                "citations": [],
                                "judgment": "uncited",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "two",
                        "reviewed_all_material_claims": True,
                        "claims": [
                            {
                                "claim_id": "c1",
                                "text": "时间安排部分吻合。",
                                "citations": ["[学业-1]"],
                                "judgment": "partially_supported",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    reviews = load_claim_reviews(review_file, answers)
    metrics = summarize_claim_reviews(reviews)
    report = review_case_to_dict(reviews[0])

    assert metrics["material_claim_count"] == 4
    assert metrics["claim_citation_coverage_rate"] == pytest.approx(0.75)
    assert metrics["fully_supported_claim_rate"] == pytest.approx(0.25)
    assert metrics["fully_supported_cited_claim_rate"] == pytest.approx(1 / 3)
    assert metrics["unsupported_claim_rate"] == pytest.approx(0.25)
    assert metrics["uncited_claim_rate"] == pytest.approx(0.25)
    assert metrics["by_category"]["学业"]["case_count"] == 1
    assert metrics["by_tag"]["paraphrase"]["partially_supported_claim_count"] == 1
    assert report["claims"][1]["source_urls"] == ["https://source.test/other"]
    json.dumps(report, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize(
    "line, message",
    [
        (
            '{"id":"one","claims":[],"reviewed_all_material_claims":false}',
            "must be true",
        ),
        (
            '{"id":"one","claims":[{"claim_id":"x","text":"事实","citations":["[学业-9]"],"judgment":"supported"}],"reviewed_all_material_claims":true}',
            "does not appear in the answer",
        ),
        (
            '{"id":"one","claims":[{"claim_id":"x","text":"事实","citations":[],"judgment":"supported"}],"reviewed_all_material_claims":true}',
            "other judgments require citations",
        ),
    ],
)
def test_claim_review_rejects_incomplete_or_invalid_annotations(
    tmp_path, line: str, message: str
) -> None:
    review_file = tmp_path / "reviews.jsonl"
    review_file.write_text(line, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_claim_reviews(review_file, [_answer("one", None, ())])


def test_claim_review_requires_every_answer_case(tmp_path) -> None:
    review_file = tmp_path / "reviews.jsonl"
    review_file.write_text(
        '{"id":"one","reviewed_all_material_claims":true,"claims":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing case ids: two"):
        load_claim_reviews(review_file, [_answer("one", None, ()), _answer("two", None, ())])


def test_independent_review_comparison_reports_kappa_and_disagreements(tmp_path) -> None:
    answers = [_answer("one", "学业", ("direct",))]
    reviews = []
    for file_name, judgments in (
        ("first.jsonl", ["supported", "supported", "unsupported"]),
        ("second.jsonl", ["supported", "unsupported", "unsupported"]),
    ):
        review_file = tmp_path / file_name
        review_file.write_text(
            json.dumps(
                {
                    "id": "one",
                    "reviewed_all_material_claims": True,
                    "claims": [
                        {
                            "claim_id": f"c{index}",
                            "text": f"claim {index}",
                            "citations": ["[学业-1]" if index < 3 else "[学业-2]"],
                            "judgment": judgment,
                        }
                        for index, judgment in enumerate(judgments, start=1)
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        reviews.append(load_claim_reviews(review_file, answers))

    comparison = compare_claim_reviews(reviews[0], reviews[1])

    assert comparison["summary"]["claim_count"] == 3
    assert comparison["summary"]["observed_agreement_rate"] == pytest.approx(2 / 3)
    assert comparison["summary"]["cohens_kappa"] == pytest.approx(0.4)
    assert comparison["summary"]["confusion_matrix"]["supported"]["unsupported"] == 1
    assert comparison["summary"]["by_category"]["学业"]["case_count"] == 1
    assert comparison["disagreements"] == [
        {"id": "one", "claim_id": "c2", "first": "supported", "second": "unsupported"}
    ]


@pytest.mark.parametrize(
    "second_claim, message",
    [
        (
            '{"claim_id":"other","text":"claim 1","citations":["[学业-1]"],"judgment":"supported"}',
            "claim IDs differ",
        ),
        (
            '{"claim_id":"c1","text":"edited claim","citations":["[学业-1]"],"judgment":"supported"}',
            "claim text differs",
        ),
        (
            '{"claim_id":"c1","text":"claim","citations":["[学业-2]"],"judgment":"supported"}',
            "claim citations differ",
        ),
    ],
)
def test_independent_review_comparison_requires_identical_claim_units(
    tmp_path, second_claim: str, message: str
) -> None:
    answers = [_answer("one", None, ())]
    review_paths = [tmp_path / "first.jsonl", tmp_path / "second.jsonl"]
    review_paths[0].write_text(
        '{"id":"one","reviewed_all_material_claims":true,"claims":[{"claim_id":"c1","text":"claim","citations":["[学业-1]"],"judgment":"supported"}]}',
        encoding="utf-8",
    )
    review_paths[1].write_text(
        '{"id":"one","reviewed_all_material_claims":true,"claims":[' + second_claim + "]}",
        encoding="utf-8",
    )
    first, second = [load_claim_reviews(path, answers) for path in review_paths]

    with pytest.raises(ValueError, match=message):
        compare_claim_reviews(first, second)


def test_adjudication_template_prefills_consensus_and_requires_reason_for_disagreement(
    tmp_path,
) -> None:
    answers = [_answer("one", "学业", ("direct",))]
    review_paths = [tmp_path / "first.jsonl", tmp_path / "second.jsonl"]
    review_payloads = [
        [
            {
                "claim_id": "agreed",
                "text": "shared fact",
                "citations": ["[学业-1]"],
                "judgment": "supported",
            },
            {
                "claim_id": "disputed",
                "text": "disputed fact",
                "citations": ["[学业-2]"],
                "judgment": "unsupported",
            },
        ],
        [
            {
                "claim_id": "agreed",
                "text": "shared fact",
                "citations": ["[学业-1]"],
                "judgment": "supported",
            },
            {
                "claim_id": "disputed",
                "text": "disputed fact",
                "citations": ["[学业-2]"],
                "judgment": "partially_supported",
            },
        ],
    ]
    reviews = []
    for path, claims in zip(review_paths, review_payloads, strict=True):
        path.write_text(
            json.dumps(
                {"id": "one", "reviewed_all_material_claims": True, "claims": claims},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        reviews.append(load_claim_reviews(path, answers))
    first, second = reviews

    template = build_adjudication_template(first, second)

    assert template[0]["claims"][0]["adjudicated_judgment"] == "supported"
    assert template[0]["claims"][1]["adjudicated_judgment"] is None
    template[0]["adjudicator"] = "reviewer-c"
    template[0]["claims"][1]["adjudicated_judgment"] = "partially_supported"
    template[0]["claims"][1]["rationale"] = (
        "The source confirms the timing but omits the condition."
    )
    decisions_file = tmp_path / "decisions.jsonl"
    decisions_file.write_text(json.dumps(template[0], ensure_ascii=False), encoding="utf-8")

    adjudicated = load_adjudicated_reviews(decisions_file, first, second)
    metrics = summarize_adjudicated_reviews(adjudicated)

    assert metrics["material_claim_count"] == 2
    assert metrics["fully_supported_claim_rate"] == pytest.approx(0.5)
    assert metrics["partially_supported_claim_rate"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"rationale": ""}, "rationale is required for disagreement"),
        ({"text": "changed text"}, "claim text differs"),
        ({"reviewer_a_judgment": "unsupported"}, "reviewer A judgment was changed"),
    ],
)
def test_adjudication_rejects_missing_rationale_and_changed_review_evidence(
    tmp_path, changes: dict[str, str], message: str
) -> None:
    answers = [_answer("one", None, ())]
    review_paths = [tmp_path / "first.jsonl", tmp_path / "second.jsonl"]
    for path, judgment in zip(review_paths, ("supported", "unsupported"), strict=True):
        path.write_text(
            json.dumps(
                {
                    "id": "one",
                    "reviewed_all_material_claims": True,
                    "claims": [
                        {
                            "claim_id": "c1",
                            "text": "claim",
                            "citations": ["[学业-1]"],
                            "judgment": judgment,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    first, second = [load_claim_reviews(path, answers) for path in review_paths]
    decision = build_adjudication_template(first, second)[0]
    decision["adjudicator"] = "reviewer-c"
    decision_claim = decision["claims"][0]
    decision_claim["adjudicated_judgment"] = "supported"
    decision_claim["rationale"] = "Source text explicitly states the requirement."
    decision_claim.update(changes)
    decision_file = tmp_path / "decision.jsonl"
    decision_file.write_text(json.dumps(decision, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_adjudicated_reviews(decision_file, first, second)
