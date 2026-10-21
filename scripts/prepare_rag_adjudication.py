"""Create a claim adjudication template from two independent RAG reviews."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.rag_eval import load_answer_dataset, load_dataset
from app.services.rag_review_eval import build_adjudication_template, load_claim_reviews


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("answers", type=Path)
    parser.add_argument("first_review", type=Path)
    parser.add_argument("second_review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cases = load_dataset(args.dataset)
    answers = load_answer_dataset(args.answers, cases)
    first = load_claim_reviews(args.first_review, answers)
    second = load_claim_reviews(args.second_review, answers)
    template = build_adjudication_template(first, second)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in template) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(template)} adjudication cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
