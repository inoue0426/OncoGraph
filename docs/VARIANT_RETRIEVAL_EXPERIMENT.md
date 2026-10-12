# Variant-conditioned retrieval experiment

This is a reproducible **retrieval** experiment, not a drug response study or an
evaluation of LLM-generated clinical advice. It compares the public v1 Evidence
Tree's variant-conditioned lookup with a context-blind CIViC ablation. Both use
the same frozen snapshot, exact drug/disease/gene strings and accepted CIViC
evidence IDs; the ablation ignores the variant. The question is whether keeping
the molecular-profile constraint avoids returning unrelated evidence IDs.

## Run

From the repository root, with Node.js 22 or later:

```sh
python scripts/download_public_snapshot.py
node scripts/evaluate_variant_questions.cjs \
  --snapshot web/data \
  --queue data/benchmarks/variant_review_queue.json \
  --gold data/benchmarks/variant_gold_adjudicated.json \
  --out variant-evaluation
```

`report.json` contains SHA-256 hashes of the original `search-index.json` and
`relations.json`, per-question EID predictions by both retrieval strategies,
and metrics **only for independently reviewed cases**. `review_candidates.json`
contains up to 20 additional distinct questions sampled deterministically
from accepted CIViC drug–disease–molecular-profile relations in the same
snapshot. The 20 hand-written pending questions and up to 20 generated questions
form a 20–40 case **review queue**, not 40 labeled test cases. The run records
the actual count; a snapshot with fewer eligible relations may yield fewer.
Generated `source_evidence_hint` and URL are starting points for review, not
ground truth. The generator rounds across genes and excludes duplicates from
the prewritten queue. A complete report can be downloaded from the
**Variant retrieval evaluation** GitHub Actions run after a refresh or manually
from Actions; the workflow uses the same refresh artifact as GitHub Pages.

## Adjudication before publication claims

`data/benchmarks/variant_gold_adjudicated.json` is intentionally empty. For each
reviewed item, independently inspect its original CIViC Evidence Item(s) and
the underlying publication(s) to check disease, gene, *entire molecular
profile*, therapy, evidence direction, review state, and primary citation.
Two domain reviewers should label the item independently and adjudicate
disagreements. The following is the schema for a positive case (illustrative
placeholders; **not** a verified label):

```json
{
  "id": "variant-review-01",
  "review_status": "adjudicated",
  "reviewed_by": ["reviewer-A", "reviewer-B"],
  "snapshot_sha256": {
    "search-index.json": "<sha256 from report>",
    "relations.json": "<sha256 from report>"
  },
  "verified_evidence_ids": ["<verified CIViC EID>"],
  "primary_publications": ["<verified PMID or DOI URL>"]
}
```

For an adjudicated *no-match in this snapshot* case, use an empty ID list and
`"negative_checked_in_snapshot": true`. It does not assert absence in CIViC
or the biomedical literature as a whole. The script refuses labels with
mismatched snapshot hashes, fewer than two distinct reviewer names, missing
primary citations for positive labels, or unconfirmed empty labels. Do not
copy the retrieved prediction or candidate EID hint into the gold file as its
own validation. Keep a held-out set separate from any parameter tuning.

## Reported quantities and limitations

For adjudicated cases only, the script reports macro precision, recall, F1,
and exact EID-set match per strategy. It returns `null` for these metrics when
there are no reviewed cases; per-question predictions on pending cases are
diagnostics only. Variant scope is checked at the molecular-profile level:
membership in a multi-variant profile is **not** evidence for the member alone.
The comparison is deliberately between two retrievers on the same CIViC
records, **not** against a literature search, standalone LLM, or independent
clinical ground truth. It does not evaluate free-text answers, claim-level
citations, patient benefit, drug efficacy, FDA approval, or novelty of a drug.
Exact-name therapy/disease matching, the 200-item Evidence Tree cap, and
availability of variant membership can reduce coverage; truncated scoped
results are flagged and excluded from its scores. Report the number and mix of
gold cases before interpreting any aggregate metric.
