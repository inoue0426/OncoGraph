# Benchmark run v2: first real evaluation (2026-09-17)

This is OncoGraph's first *actually executed* benchmark pass. Issue #9's
`oncograph.benchmark` module and the 9-item `data/benchmarks/v1/` file were
infrastructure/schema only -- nothing had been run and no number had been
reported before this. Everything below is a real computation over a real,
frozen graph snapshot. Numbers are reported as observed, including the
metrics that come out low.

## Frozen snapshot

Snapshot identity (from `web/data/stats.json` at the time of this run):

| Field | Value |
|---|---|
| `graph_version` | `2026-09-17T22:32:28Z` |
| Total entities | 94,236 (drug 908, gene 45,054, disease 1,290, trial 8,892, go_term 38,092) |
| Relations | 88,032 |
| Evidence records | 88,032 |
| Distinct sources | 5 (`gene_ontology`, `gtopdb`, `clinicaltrials_gov`, `open_targets`, `open_targets_indications`) |

This is the same artifact produced by GitHub Actions run
[35279742078](https://github.com/inoue0426/OncoGraph/actions/runs/35279742078)
and deployed to the live site by Pages run 35284026794 -- the benchmark ran
against the identical data the public site was serving at the time, not a
separately-fetched copy.

## Item generation (`scripts/generate_benchmark_items.py`)

Deterministic, seeded (`--seed 20260917`), sampled directly from real
relations in the frozen snapshot -- no item was hand-picked or edited after
generation. 90 items across the 6 task types the current deployed schema
can actually back with real data:

| Task type | Count | Real relation(s) used |
|---|---|---|
| `single_hop_factual_retrieval` | 15 | one `targets` edge (drug -> gene) |
| `trial_lookup` | 15 | one `studied_in` edge (drug -> trial) |
| `pathway_reasoning` | 15 | one `part_of` edge (GO term -> GO term) -- see note below |
| `drug_target_disease_reasoning` | 15 | a drug's `targets` + `indicated_for` edges combined |
| `multi_hop_reasoning` | 15 | a genuine 2-hop `is_a` chain (GO term -> parent -> grandparent) |
| `provenance_aware_reasoning` | 15 | one `targets` edge, disjoint sample from the single-hop pool |

**Not generated (no real backing data in this snapshot):**
`contradiction_detection`, `context_specific_drug_response`, and
`publication_evidence_attribution` -- no recorded contradictory evidence,
no drug-response observations, and no Publication entities exist in the
currently deployed graph (all pre-existing, documented gaps; see
`docs/BIOLOGICAL_SOURCES.md` and `docs/DRUG_RESPONSE.md`). These remain
covered only by `data/benchmarks/v1/`'s `illustrative_synthetic` items,
which were not scored in this run.

**`pathway_reasoning` substitution note:** the deployed snapshot has no
Reactome Pathway entities, only GO terms (see `docs/BIOLOGICAL_SOURCES.md`).
GO's `part_of` predicate (a real, standard GO relation for compositional
process membership) is used as the closest real substitute. This is a
deliberate, documented approximation, not a claim that GO terms are
Reactome pathways.

**Dev / held-out split:** stratified per task type, 3 dev + 12 held-out per
type (`data/benchmarks/v2/generated_dev.json`, 18 items;
`data/benchmarks/v2/generated_heldout.json`, 72 items). Dev was used only to
sanity-check the generator and the runner (see "Development iteration"
below); the reported numbers are computed once from held-out and never fed
back into another round of code changes.

## Retrievers run

| Retriever | Status |
|---|---|
| `GraphRetriever` (`oncograph.query`) | Run. Evidence-aware, real, already implemented (Issue #7). |
| `VanillaGraphRetriever` (`oncograph.benchmark`) | Run. Real ablation added for this pass: identical BFS reachability via the same `traverse()`, but every relation's evidence/publication references are stripped before scoring. |
| `LLMOnlyRetriever` | **Not run.** No LLM API is configured/authorized in this environment; reporting a number here would be fabricated. |
| `VectorRAGRetriever` | **Not run.** No embedding/vector-index infrastructure exists in this repository. |

Each item's traversal hop depth is computed automatically from its own
`gold_evidence_path` shape (`run_benchmark._required_hops`): star-shaped
items (e.g. `drug_target_disease_reasoning`, two independent facts about
the same root) use 1 hop; genuine chains (the GO `is_a` items) use 2. This
was fixed *before* the reported run, during development on a separate,
earlier snapshot -- see "Development iteration" below.

## Results (held-out set, n=72, one run, unmodified afterward)

| Metric | GraphRetriever | VanillaGraphRetriever |
|---|---|---|
| answer_correctness | 1.0 | 1.0 |
| citation_correctness | 0.1523 | 0.0 |
| evidence_completeness | 1.0 | 0.0 |
| path_correctness | 0.0139 | 0.0 |
| unsupported_claim_rate | 0.0 | 0.0 |
| contradiction_awareness | 1.0 | 1.0 |
| provenance_coverage | 1.0 | 0.0 |

(Dev set, n=18, for reference only: materially the same shape --
`citation_correctness` 0.1575 vs 0.0, `provenance_coverage` 1.0 vs 0.0 --
so there is no dev/held-out distribution shift worth investigating
further.)

Full per-item scores, per-task-type breakdowns, and the exact `Prediction`
each retriever produced for every item are in
`data/benchmarks/v2/results_v2.json`.

## Reading the results honestly

- **`answer_correctness` = 1.0 for both retrievers on every task type.**
  Every gold answer ID was reachable from the root within the computed hop
  depth, for both a fully evidence-aware and a fully evidence-blind
  traversal. On this snapshot (no contradictions, no low-confidence
  evidence, no missing publications), the graph is "easy" enough that
  answer reachability alone does not distinguish the two retrievers at
  all. This is a property of the current snapshot's data, not evidence
  that evidence-awareness has no reachability benefit in general.
- **`citation_correctness`/`evidence_completeness`/`provenance_coverage`
  are exactly 0 for VanillaGraphRetriever by construction** -- it never
  carries evidence forward, so it structurally cannot cite anything. This
  is the ablation working as designed, not a retrieval failure.
- **`citation_correctness` is low (0.15) for GraphRetriever too**, and
  `path_correctness` (an exact-match metric) is correspondingly near zero.
  This is the one real, informative finding of this run.

## One justified follow-up analysis

Hypothesis: `graph_retrieval_to_prediction()` (Issue #9) converts a
`RetrievalResult` into a `Prediction` by citing *every* relation the BFS
touched, not just the relation(s) relevant to the specific gold answer.
A high-degree root entity (e.g. a drug with many trials, or a GO term with
many `is_a`/`part_of` edges) should therefore drag `citation_correctness`
down even when the retrieved answer itself is correct, because the
precision denominator (all cited evidence) grows with node degree while
the numerator (gold hops actually cited) stays fixed.

Checked directly against the already-computed results and the frozen
snapshot's own relation degree (no code changes, no re-scoring):

- Pearson correlation between a held-out item's root-entity degree (total
  relations touching it in the frozen snapshot) and its
  `citation_correctness`: **-0.53** (n=72).
- Lowest-degree roots (degree 1-2) reach `citation_correctness` up to 1.0;
  highest-degree roots (degree 26-75) sit at 0.01-0.08.

This confirms the hypothesis: the low `citation_correctness` is explained
by `graph_retrieval_to_prediction`'s "cite the whole neighborhood" behavior
interacting with node degree, not by `GraphRetriever` failing to find or
support the right answer. **No code was changed in response to this
finding** -- per the run protocol, this pass stops at recording and
explaining the observed failure mode, not iterating to improve the score.
A narrower, answer-directed evidence-citation strategy (citing only
relations on the shortest path to each answer entity, using `traverse()`'s
own `paths` field) is a reasonable follow-up for a future issue, not
something to retrofit here to raise this run's number.

## Development iteration (not part of the reported result)

While building `scripts/generate_benchmark_items.py` and
`scripts/run_benchmark.py`, both were exercised against a *different*,
earlier snapshot (GitHub Actions run 35267400595, superseded by
35279742078 before this report's numbers were computed) purely to find and
fix real bugs:

1. A labeling bug where three different single-hop predicates (`targets`,
   `studied_in`, `part_of`) were all tagged `single_hop_factual_retrieval`
   instead of their intended task types.
2. A benchmark-harness fairness bug: a fixed `max_hops=3` for every item
   caused single-hop questions to trigger a needlessly wide 3-hop BFS,
   inflating the evidence-set denominator for reasons unrelated to
   retrieval quality. Fixed by computing each item's required hop depth
   from its own `gold_evidence_path` (`_required_hops`) before this run,
   not after seeing this run's numbers.

Both fixes were made and tested against that earlier, discarded snapshot.
The reported run above used the new snapshot end to end, generated once,
scored once, with no further code changes afterward.

## Reproducing this run

```bash
python scripts/generate_benchmark_items.py \
  --snapshot-dir <dir with search-index.json + relations.json> \
  --graph-version <web/data/stats.json's graph_version> \
  --seed 20260917 --per-task 15 \
  --out-dev data/benchmarks/v2/generated_dev.json \
  --out-heldout data/benchmarks/v2/generated_heldout.json

python scripts/run_benchmark.py \
  --snapshot-dir <same dir> \
  --benchmark data/benchmarks/v2/generated_dev.json \
  --benchmark data/benchmarks/v2/generated_heldout.json \
  --retriever graph_retriever --retriever vanilla_graph_retriever \
  --out data/benchmarks/v2/results_v2.json
```
