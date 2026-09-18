# Research benchmarking & evaluation (Issue #9)

This module started as infrastructure only (a schema, real scoring functions, and a
common retrieval-comparison interface -- no run, no reported number). Four real runs
now exist: `docs/BENCHMARK_RUN_v2.md` (`GraphRetriever` vs. an evidence-blind
`VanillaGraphRetriever` ablation on a frozen snapshot, with honest results including
where the metrics came out low), `docs/BENCHMARK_RUN_v3.md` (a rerun on a newer
frozen snapshot -- with real combination-treatment items added and a principled
path-selection fix for the citation-precision failure mode v2 found, on the same
unchanged gold set), `docs/BENCHMARK_RUN_v3_ranked.md` (a fourth retriever,
`oncograph.rank.QueryConditionedRetriever`, evaluated on the *same* v3 gold set and
frozen snapshot -- dev-calibrated, scored once on held-out, with degree-stratified
results and honestly-reported failure cases), and `docs/BENCHMARK_RUN_v3_hybrid.md`
(a fifth retriever, `oncograph.rank.HybridPathRanker`, extending the lexical-only
ranker with semantic (local TF-IDF) and structural signals -- honestly reports that
the full design, as specified and frozen, does *not* beat the simpler lexical-only
version, with an ablation study identifying which components help and which hurt).
`LLMOnlyRetriever` and `VectorRAGRetriever` remain unimplemented scaffolds -- there is
no LLM or embedding infrastructure in this repository to back a real run of either.

## Benchmark item schema

A benchmark file (e.g. `data/benchmarks/v1/oncology_core.json`) is a JSON list of items:

```json
{
  "id": "v1-001",
  "version": "v1",
  "task_type": "single_hop_factual_retrieval",
  "question": "What gene does gefitinib target?",
  "gold_answer_canonical_ids": ["hgnc:HGNC:3236"],
  "gold_evidence_path": [
    {"subject_canonical_id": "gtopdb:4941", "predicate": "targets", "object_canonical_id": "hgnc:HGNC:3236", "source": "gtopdb"}
  ],
  "context": {"grounding": "verified_live_data", "note": "..."}
}
```

`task_type` is one of the ten `BenchmarkTaskType` values (`single_hop_factual_retrieval`,
`multi_hop_reasoning`, `drug_target_disease_reasoning`, `pathway_reasoning`, `trial_lookup`,
`publication_evidence_attribution`, `contradiction_detection`, `context_specific_drug_response`,
`provenance_aware_reasoning`, `combination_treatment_reasoning`). The last was added for Issue
#11's real ClinicalTrials.gov-derived combination treatments; `v1`'s 9 hand-written items predate
it and cover only the original nine.

**Gold references use canonical IDs, never database row UUIDs.** This repository's SQLite
database is regenerated from scratch on every refresh (`docs/HOSTING.md`) -- a UUID from one
import run means nothing in the next. Canonical IDs (`gtopdb:4941`, `hgnc:HGNC:3236`, ...) are
stable across re-imports and are what makes a benchmark file actually versioned/reproducible.

## Versioning

The directory (`data/benchmarks/v1/`) and each item's own `"version"` field both carry the
version, deliberately redundant: a file's items can be checked against the filename, and an item
copied elsewhere still carries its own provenance. Add a new file/version rather than editing
items in place once a version has been used for a real run, so past scores stay reproducible.

## Constructing a new item

1. Pick the closest `task_type`.
2. State `gold_answer_canonical_ids`: the canonical ID(s) a correct answer must include.
3. State `gold_evidence_path`: the specific `(subject, predicate, object, source)` hop(s) a
   correct, well-cited answer should cite. Look these up in the live index or your own SQLite
   snapshot -- don't invent an identifier.
4. If the fact isn't actually present in currently-imported data yet (e.g. Issue #6's drug-response
   schema has no real dataset wired in), still write the item, but set `context.grounding` to
   `"illustrative_synthetic"` and say so in `context.note`. Never mark a fact `"verified_live_data"`
   without having actually checked it. `data/benchmarks/v1/oncology_core.json` follows this
   convention for all 9 example items -- 7 are grounded in facts checked against a real,
   live-fetched source during this project's own development; 2 (`contradiction_detection`,
   `context_specific_drug_response`) are marked illustrative because no such real case exists in
   currently-imported data yet.

## Metrics (`oncograph.benchmark`)

All seven take a `Prediction` (structured: `answer_canonical_ids`, `evidence_refs`, `claims`,
`contradictions_flagged`) and score it against a `BenchmarkItem`'s gold fields:

| Metric | What it measures |
|---|---|
| `answer_correctness` | Recall of gold answer IDs in the prediction. |
| `citation_correctness` | Precision of the prediction's cited evidence against gold. |
| `evidence_completeness` | Recall of gold evidence hops covered by the prediction. |
| `path_correctness` | 1.0 iff the predicted evidence set exactly equals the gold set (set-based, not sequence-based -- traversal can discover the same hops in a different order). |
| `unsupported_claim_rate` | Coarse proxy: were any claims made with zero cited evidence at all. Real claim-level attribution needs a claim/evidence link this schema doesn't have; documented as a proxy in the docstring. |
| `contradiction_awareness` | For items with `context.has_known_contradiction`, did the prediction flag it. |
| `provenance_coverage` | Was an answer given *and* backed by at least one evidence reference. |

`score_prediction(item, prediction)` runs all seven and returns a `BenchmarkScore`. Every function
is a real computation over the structured inputs -- there is nothing to "fabricate" here because
nothing here runs an actual retrieval system against real questions and reports the result.

## Comparing retrieval strategies

`oncograph.query.Retriever` (a `Protocol`) plus `RetrievalQuery`/`RetrievalResult` (from Issue #7)
are the shared interface. `oncograph.query.GraphRetriever` is the evidence-aware system under
test. `oncograph.benchmark.VanillaGraphRetriever` is a real ablation (not a scaffold): identical
BFS reachability via the same `traverse()`, but with every relation's evidence and publication
references stripped before scoring -- it isolates exactly what evidence-awareness contributes
(citation/evidence-completeness/provenance metrics), holding the reachable answer set fixed.
`LLMOnlyRetriever` and `VectorRAGRetriever` in `oncograph.benchmark` declare the same interface but
raise `NotImplementedError` -- there is no LLM or embedding infrastructure in this repository to
back them, so they remain scaffolding rather than a fabricated result.

`graph_retrieval_to_prediction()` uses **principled path selection**: it cites only relations on
the shortest path (`RetrievalResult.paths`, `traverse()`'s own BFS bookkeeping) to each reached
entity, never every relation the neighborhood traversal happened to touch. An earlier version cited
the whole touched neighborhood, which made `citation_correctness`/`path_correctness` degrade sharply
with root-entity degree -- a real, measured failure mode from the v2 run; see
`docs/BENCHMARK_RUN_v3.md` for the fix and its measured effect on the same, unchanged gold set.

```python
from oncograph.benchmark import graph_retrieval_to_prediction, load_benchmark_items, score_prediction
from oncograph.query import GraphRetriever, RetrievalQuery

items = load_benchmark_items("data/benchmarks/v1/oncology_core.json")
retriever = GraphRetriever(session)
for item in items:
    result = retriever.retrieve(RetrievalQuery(root_ref=item.gold_evidence_path[0].subject_canonical_id))
    prediction = graph_retrieval_to_prediction(result)
    print(score_prediction(item, prediction))
```

`docs/BENCHMARK_RUN_v2.md` runs the equivalent of this loop -- via
`scripts/generate_benchmark_items.py` and `scripts/run_benchmark.py`, against a
larger, programmatically-generated item set rather than the 9 hand-written `v1`
items -- and reports the resulting numbers, including a real observed limitation
(`citation_correctness` degrading with root-entity degree).
