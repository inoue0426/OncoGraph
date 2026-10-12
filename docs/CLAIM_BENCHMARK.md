# Controlled 100-question claim and abstention benchmark

## Purpose and scope

GitHub Actions runs `scripts/benchmark_claim_abstention.cjs` against the latest
successful `Refresh data` **search-index artifact**, the same source used by
Pages. This is a **source-consistency stress test** for the question "Do
accepted CIViC records report sensitivity or resistance for gene–variant,
disease and therapy?" It is **not** a test of clinical truth, independent
expert adjudication, recommendation quality, or LLM-generated answer quality.

The script deterministically constructs exactly **100 distinct questions**
from accepted predictive CIViC records with exported variant membership. It
adds counterfactual conditions (another variant, therapy, disease, opposite
effect) and, where available, complex molecular profiles. It checks every
counterfactual against all eligible source records before assigning its
source-derived label, so a swapped condition with genuine matching evidence
is not mistakenly treated as empty. Target quotas are 25 direct, 20 other
variant, 20 other therapy, 15 other cancer, 10 opposite effect and 10 complex
profile questions. If a category has insufficient records, other categories
fill the set; the **actual** mixture appears in the report. If fewer than 100
unique questions exist, CI fails rather than duplicating questions.

The source reference enumerates raw accepted predictive CIViC records by exact
gene, single-variant membership, disease and therapy; a record has a matching
reported effect only when the direction is `SUPPORTS`. A reference question
is marked source-answerable if it has matching support and no supporting
report for the opposite effect or `DOES_NOT_SUPPORT` report of that effect.
This label is derived from the **same CIViC snapshot** as all methods and
is not an independent biomedical gold standard. Conflict and missing evidence
mean abstain **within this snapshot**, not absence of clinical benefit.

## Strategies

| Method | Answer condition | Deliberate limitation |
| --- | --- | --- |
| `context_blind` | Any accepted CIViC record for the gene, drug and disease | Ignores variant, direction and significance |
| `variant_only` | Any accepted CIViC record for the gene, variant/profile, drug and disease | Ignores predictive significance, direction and complex membership |
| `claim_scoped` | The structured claim check returns `supporting_records` | Requires exact reported effect and single-variant profile; abstains on opposing/disputing reports and incomplete input |

The baselines are **ablations of OncoGraph's own retrieval**, not standalone
CIViC MCP, an external clinical service or an LLM. The source reference is
field-defined, so the rules of the proposed method align with it by design:
high scores only show consistency with the frozen source fields. In particular,
they cannot demonstrate a novel clinical conclusion or a performance gain on
an independently labeled question set.

Metrics on the 100 questions: answer rate among source-answerable items;
false-answer rate among source-unanswerable items; answered count/coverage;
and error among answered. A tree with more than 200 matching records is flagged
and excluded from metrics for **all methods**, while remaining in the detailed
question list. There is no claim that a zero error rate generalizes outside
this bounded snapshot.

## Reproduce and inspect

```sh
node tests/test_claim_benchmark.cjs
node scripts/benchmark_claim_abstention.cjs --snapshot web/data --questions 100 --out claim-benchmark
```

`report.json` includes all 100 query texts, question types, source-derived
labels, EIDs per method, coverage, abstention counts and SHA-256 hashes of the
two input JSON files. CI publishes a summary and the report as an Actions
artifact named `claim-abstention-benchmark-report`; failed runs instead put a
brief error hint in the artifact name and upload the console log. The workflow
also runs on pull requests, manually, and after successful data refreshes.
To evaluate scientific novelty, independently review a held-out set of
question/claim/source tuples, evaluate claim-level citations and free-text
answers, and compare with appropriately configured CIViC MCP and LLM baselines.
