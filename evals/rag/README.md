# Dynamic RAG Evaluation

The evaluator measures retrieval against human-labeled `source_url` values. Database article IDs are intentionally not used because IDs can differ between restored databases.

## Dataset

Create `golden_set.jsonl` with one JSON object per line:

```json
{"id":"academic-001","question":"辅修报名什么时候开始？","category":"学业","relevant_source_urls":["https://source.example/article"],"relevance_grades":{"https://source.example/article":3},"tags":["direct","time-sensitive"]}
{"id":"none-001","question":"推荐一款与校园通知无关的相机？","category":null,"relevant_source_urls":[],"tags":["out-of-domain"]}
```

`relevant_source_urls` is the complete set of articles judged relevant to the question. Use an empty list only when the corpus has no answer. `relevance_grades` is optional and assigns relevant sources an integer grade from 1 (partially useful/older) to 3 (direct, current, authoritative); nDCG uses these grades. This supports explicit ranking checks for time-sensitive questions. `category` is an optional retrieval filter; `tags` support metric breakdowns. Keep the set stable between runs and update it through review when the corpus or product scope changes.

The first acceptance set should contain 30–50 questions, cover every supported category, and include direct lookups, paraphrases, multi-article questions, time-sensitive questions, ambiguous requests, and unanswerable/out-of-domain questions. Labels must be checked against article content, not generated from article titles alone.

Before running retrieval or answer evaluation, audit the dataset locally:

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_rag_dataset evals/rag/golden_set.jsonl --output outputs/rag-dataset-audit.json
```

The default audit requires 30–50 cases, all five categories (`学业`, `活动`, `党团`, `就业`, `其他`), and tags `direct`, `paraphrase`, `multi-article`, `time-sensitive`, `ambiguous`, and `out-of-domain`. It also requires both answerable and unanswerable cases, rejects duplicate normalized questions and invalid category labels, requires out-of-domain cases to have no relevant source, multi-article cases to label at least two relevant sources, and every relevant source in a time-sensitive case to have a relevance grade. Category coverage with only one case is reported as a warning because it provides weak subgroup evidence. Adjust the case range or coverage lists explicitly for a smaller pilot; a passing pilot audit does not satisfy the 30–50-case release dataset requirement.

## Run

From the repository root, keyword mode is deterministic and makes no embedding API calls:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag evals/rag/golden_set.jsonl --top-k 5 --mode keyword
```

`--mode configured` uses the configured embedding provider and may send one remote embedding request per query. Use it only when that external call is intended and the provider is available:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag evals/rag/golden_set.jsonl --top-k 5 --mode configured --output outputs/rag-evaluation.json
```

Optional gates make the command return a non-zero exit code on failure:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag evals/rag/golden_set.jsonl --top-k 5 --min-recall-at-k 0.80 --max-unanswerable-fpr 0 --max-category-violation-rate 0 --max-p95-ms 1500
```

## Metrics

- Recall@K, Precision@K, MRR@K, graded nDCG@K, and hit rate over answerable questions (macro-averaged by question, with category/tag breakdowns).
- False-positive and abstention rates over questions labeled unanswerable.
- Category violation rate over returned documents for category-filtered questions.
- p50, p95, and maximum retrieval latency, including embedding latency in `configured` mode.

The thresholds in the command above are initial acceptance proposals, not a measured baseline. Review them against the first labeled run before treating them as a release gate. Retrieval relevance does not prove answer faithfulness: final end-to-end acceptance must separately inspect generated answers, citation-to-source mapping, no-context behavior, and database/model failure paths.

## Offline Answer And Citation Evaluation

The answer evaluator consumes saved API response samples and never calls the chat API, database, or model. Each JSONL line must contain the evaluation case `id`, `answer`, `answer_mode`, and `retrieved` entries with `source_url` and the `citations` returned by the API:

```json
{"id":"academic-001","answer":"报名时间见[学业-1]。","answer_mode":"llm","retrieved":[{"source_url":"https://source.example/article","citations":["[学业-1]"]}]}
```

Every labeled case must have exactly one answer record. The evaluator rejects missing, duplicate, or unknown IDs. It emits no answer text in the report; the answer file itself remains local. Run it with:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag_answers evals/rag/golden_set.jsonl evals/rag/answers.jsonl --output outputs/rag-answer-evaluation.json
```

Optional gates can be set after establishing a reviewed baseline:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag_answers evals/rag/golden_set.jsonl evals/rag/answers.jsonl --min-citation-label-mapping-rate 1 --min-cited-source-precision 0.9 --min-answerable-citation-coverage 0.9 --min-unanswerable-abstention-rate 1 --max-unanswerable-citation-rate 0
```

Answer-side measures include citation-label mapping rate (labels map to exactly one returned source), cited-source precision/recall against human labels, answerable-question citation coverage, answerable abstention rate, and strict unanswerable abstention (mode is `no_context` and the returned source list is empty). Metrics are also split by labeled category and tag. These are structural and relevance measures, not semantic faithfulness: whether cited text actually supports each claim still requires human review or a separately validated evaluator.

## Human Claim-Grounding Review

For a reviewed answer set, create `claim_reviews.jsonl` with exactly one record for each answer ID. Review every material factual claim in the answer against the cited source content. Do not judge truth from outside knowledge alone. Use `supported`, `partially_supported`, or `unsupported` only when at least one citation label appears in the answer and maps to one returned source; use `uncited` when the claim has no citation. The completeness flag must be true only after all material claims were inspected:

```json
{"id":"academic-001","reviewed_all_material_claims":true,"claims":[{"claim_id":"c1","text":"报名需提交申请表。","citations":["[学业-1]"],"judgment":"supported"},{"claim_id":"c2","text":"报名无需导师审批。","citations":["[学业-2]"],"judgment":"unsupported"},{"claim_id":"c3","text":"流程十分简单。","citations":[],"judgment":"uncited"}]}
```

Run the deterministic scoring tool; it reads local files only and makes no database or model calls:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag_claims evals/rag/golden_set.jsonl evals/rag/answers.jsonl evals/rag/claim_reviews.jsonl --output outputs/rag-claim-review.json
```

The report includes claim text for audit, citation labels, mapped source URLs, and aggregate rates. Protect the report like the source answer data. Metrics include claim citation coverage, fully supported claim rate, partial/unsupported rates, and uncited rate, with category/tag breakdowns. Optional gates (`--min-claim-citation-coverage`, `--min-fully-supported-claim-rate`, `--min-fully-supported-cited-claim-rate`, `--max-partially-supported-claim-rate`, `--max-unsupported-claim-rate`, `--max-uncited-claim-rate`) should be configured only after reviewers establish a baseline. This is a human-labeled measure, not an automatic semantic judge; the tool computes scores but does not validate reviewer correctness.

### Independent Reviewer Agreement

For reliability checks, have two reviewers annotate the same answer set independently in separate JSONL files using the schema above. They must use identical case IDs, claim IDs, claim text, and citation labels; only the judgment may differ. Compare the files with:

```powershell
.\.venv\Scripts\python.exe -m scripts.compare_rag_reviews evals/rag/golden_set.jsonl evals/rag/answers.jsonl evals/rag/reviewer-a.jsonl evals/rag/reviewer-b.jsonl --output outputs/rag-review-agreement.json
```

The report includes exact observed agreement, unweighted Cohen's kappa, a four-class confusion matrix, and category/tag breakdowns. Optional gates are `--min-observed-agreement` (0 to 1) and `--min-cohens-kappa` (-1 to 1). Kappa is `null` when the marginal distributions make its denominator zero (for example, both reviewers use only one class); treat that as insufficient evidence for a kappa gate, not as perfect reliability. Review disagreement records identify the case, claim, and two judgments without repeating the claim text. Establish thresholds from a pilot set and reconcile disagreements before interpreting support metrics.

### Adjudicated Grounding Score

Generate a template from the two independent reviews. Consensus labels are prefilled; disagreements are left blank:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_rag_adjudication evals/rag/golden_set.jsonl evals/rag/answers.jsonl evals/rag/reviewer-a.jsonl evals/rag/reviewer-b.jsonl --output evals/rag/adjudication.jsonl
```

An adjudicator records their name, chooses `adjudicated_judgment` for every claim, and provides a rationale for each disagreement or override. Do not change claim IDs, text, citations, or the original reviewers' labels. Score only the completed adjudication file:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag_adjudication evals/rag/golden_set.jsonl evals/rag/answers.jsonl evals/rag/reviewer-a.jsonl evals/rag/reviewer-b.jsonl evals/rag/adjudication.jsonl --output outputs/rag-adjudicated-review.json
```

This report keeps final adjudicated claim rates separate from reviewer agreement and includes the two original judgments, adjudicated judgment, rationale, and input SHA-256 hashes for auditability. Optional final-score gates are `--min-fully-supported-claim-rate`, `--max-unsupported-claim-rate`, and `--max-uncited-claim-rate`. The report contains claim text and review rationales; protect it as sensitive evaluation data.

## Release Bundle Validation

After every input has been reviewed and all stage reports have been generated with explicit gates, validate that they belong to the same release set. The final validator requires both keyword and configured retrieval reports, checks their declared modes, verifies report hashes against the current dataset/answers/reviews/adjudications, enforces 30–50 cases and required dataset coverage, and compares case IDs wherever the stage report includes them. It also blocks missing thresholds, failed gates, and inconsistent reviewer/adjudication counts.

For example, generate retrieval reports with all retrieval gates configured (use the agreed baseline thresholds):

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag evals/rag/golden_set.jsonl --top-k 5 --mode keyword --min-recall-at-k 0.80 --max-unanswerable-fpr 0 --max-category-violation-rate 0 --max-p95-ms 1500 --output outputs/rag-keyword.json
.\.venv\Scripts\python.exe -m scripts.evaluate_rag evals/rag/golden_set.jsonl --top-k 5 --mode configured --min-recall-at-k 0.80 --max-unanswerable-fpr 0 --max-category-violation-rate 0 --max-p95-ms 1500 --output outputs/rag-configured.json
```

The configured run may make external embedding API calls. The answer, agreement, and adjudication reports also need their full gate sets configured; for example, include `--min-cited-source-recall` and `--max-answerable-abstention-rate` when scoring answers, and both reviewer-agreement gates when comparing reviewers. Threshold values above are proposals, not established performance baselines.

Then pass all original JSONL inputs and generated reports to the bundle validator:

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_rag_acceptance `
  evals/rag/golden_set.jsonl evals/rag/answers.jsonl `
  evals/rag/reviewer-a.jsonl evals/rag/reviewer-b.jsonl evals/rag/adjudication.jsonl `
  --dataset-audit outputs/rag-dataset-audit.json `
  --retrieval-keyword-report outputs/rag-keyword.json `
  --retrieval-configured-report outputs/rag-configured.json `
  --answer-report outputs/rag-answer-evaluation.json `
  --agreement-report outputs/rag-review-agreement.json `
  --adjudication-report outputs/rag-adjudicated-review.json `
  --output outputs/rag-acceptance-bundle.json
```

`ready` means only that the optional offline metric bundle is complete, internally consistent, and passed its configured gates. The output explicitly marks live PostgreSQL + real-model functional smoke acceptance as `not_evaluated_by_this_tool`. Under the current M3 plan, a golden-set score run and human claim review are optional and do not block completion; the small live functional smoke check remains separate.

## Current status

The retrieval, citation, claim-review, reviewer-agreement, adjudication, and release-bundle validation implementations and deterministic unit tests are available. The labeled dataset, saved answer samples, human claim reviews, adjudication decisions, reviewer-agreement report, and database-backed retrieval reports are not yet complete; these are optional quality-measurement artifacts under the current M3 scope. Do not treat the example questions above as a scored dataset; replace their example URLs with reviewed source URLs before using them for a scored run.
