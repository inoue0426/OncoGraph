# Research benchmarking & evaluation (Issue #9)

**This is infrastructure, not a result.** Nothing in `oncograph.benchmark` or
`data/benchmarks/` claims that evidence-aware OncoGraph retrieval outperforms any
baseline -- no baseline has been run. What exists is a schema, real (not stubbed)
scoring functions, and a common interface, so that comparison can happen later
without redesigning anything.

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

`task_type` is one of the nine `BenchmarkTaskType` values (`single_hop_factual_retrieval`,
`multi_hop_reasoning`, `drug_target_disease_reasoning`, `pathway_reasoning`, `trial_lookup`,
`publication_evidence_attribution`, `contradiction_detection`, `context_specific_drug_response`,
`provenance_aware_reasoning`).

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
are the shared interface. `oncograph.query.GraphRetriever` is the only one implemented --
`graph_retrieval_to_prediction()` converts its output into a scoreable `Prediction`.
`LLMOnlyRetriever`, `VectorRAGRetriever`, and `VanillaGraphRetriever` in `oncograph.benchmark`
declare the same interface but raise `NotImplementedError` -- they're scaffolding for whoever
builds those baselines later, not a promise that they work.

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

Running this against the real, currently-imported graph and reporting the resulting numbers as a
finding is future work, not something this issue does.
