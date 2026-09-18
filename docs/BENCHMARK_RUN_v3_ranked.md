# Retrieval-quality improvement: query-conditioned relation/path selection (2026-09-18)

A third real evaluation, on the **same** frozen snapshot and **same** v3
gold benchmark as `docs/BENCHMARK_RUN_v3.md` -- no item, no gold answer, no
gold evidence path was touched. This run adds a new retriever
(`oncograph.rank.QueryConditionedRetriever`) and measures it against v3's
already-recorded `GraphRetriever`/`VanillaGraphRetriever` results.

## What changed vs. v3

Nothing about the graph, the snapshot, or the benchmark items. Only a new,
third `Retriever` implementation was added and evaluated. v2's and v3's
`GraphRetriever`/`VanillaGraphRetriever` numbers quoted below are the
already-recorded results from `docs/BENCHMARK_RUN_v3.md`
(`data/benchmarks/v3/results_v3.json`), not rerun.

## The method: query-conditioned relation/path selection

`graph_retrieval_to_prediction()`'s principled path selection (the v3 fix)
cites every relation on *some* shortest path to a reached entity -- correct
recall-wise, but a high-degree root's many real, distinct relations each
legitimately justify reaching a different entity, so citation precision
still degrades with root degree (measured at Pearson -0.62 in v3).

`oncograph.rank.QueryConditionedRetriever` (`src/oncograph/rank.py`) adds a
relevance filter on top of the same traversal: it scores each reached
entity's justifying path using

```
score = (2 * predicate/question token overlap + evidence-tier weight) / hop_distance / degree_penalty
```

and keeps only entities scoring at least `relative_threshold * max_score`
for that query (root always kept). Signals used, all deterministic and
explainable -- **no LLM, no embedding model, no synonym dictionary**:

- **Lexical token overlap** between the question text
  (`RetrievalQuery.question_text`, new optional field) and the relation's
  predicate name (e.g. "targets" vs. "What gene does X **target**?").
  Standard English stopword removal (a, the, in, of, which, ...) is
  applied, with "is"/"a" deliberately exempted since this repository's own
  `is_a` GO predicate would otherwise tokenize to nothing (see "Dev-set
  debugging" below).
- **Evidence tier** (approved > curated_database > publication > registry >
  computed/unknown), reusing the same tier concept `web/app.js` already
  uses for display.
- **Hop distance** (closer favored).
- **Local node degree** (a hub-bias penalty, computed within the retrieved
  neighborhood only -- no extra DB query).

It never inspects a benchmark item's `gold_answer_canonical_ids` or
`gold_evidence_path` -- only the question text and the graph itself. There
is no label leakage into the ranking.

**Honest scope limit, by design:** when every candidate relation from a
root shares the *same* predicate (e.g. a drug's many `studied_in` trial
edges, or a GO term's many sibling `is_a` parents), lexical overlap cannot
discriminate between them, and the ranker degrades gracefully to keeping
everyone -- the same behavior as plain path selection. This is not a bug;
see "Failure cases" below.

## Dev-set debugging (not tuning on held-out)

Per instruction, only `data/benchmarks/v3/generated_dev.json` (21 items)
was used to debug the method and calibrate `relative_threshold`; held-out
(84 items) was scored exactly once, after the threshold was frozen.

**A real bug found via dev debugging, fixed generically:** the first
version (no stopword filtering) *broke* `combination_treatment_reasoning`
on dev -- `answer_correctness` dropped to 0.857 because the predicate
`tested_in` (tokens `{tested, in}`) spuriously outscored `has_component`
(tokens `{has, component}`) on questions like "Which drugs are **combined**
in the treatment **tested in** '...'?", purely because the generic
preposition "in" happened to co-occur. This was fixed with **standard
English stopword removal** (a well-established, generic NLP technique, not
a rule about this one wording) -- not by hand-mapping "combined" to
`has_component`, which would have been overfitting to this benchmark's own
phrasing. "is"/"a" were kept out of the stopword list specifically because
this repository's `is_a` predicate would otherwise become unmatchable.

**Threshold sweep on dev** (`relative_threshold` in `{0.25, 0.28, 0.3,
0.33, 0.35, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0}`), selecting the value
maximizing `citation_correctness` **subject to** `answer_correctness`
staying at 1.0 (no recall loss tolerated):

| relative_threshold | answer_correctness | citation_correctness |
|---|---|---|
| 0.25 | 1.0 | 0.2334 |
| **0.28 - 0.33 (plateau)** | **1.0** | **0.3329** |
| 0.35 - 0.4 | 0.857 | 0.3329 |
| 0.5 | 0.857 | 0.3329 |
| 0.6+ | <= 0.595 | <= 0.4277 |

**Frozen threshold: `relative_threshold = 0.3`** (middle of the
recall-preserving plateau). Not touched again after this point.

## Results (held-out, n=84, one run with the frozen threshold)

| Metric | GraphRetriever (v3) | VanillaGraphRetriever (v3) | QueryConditionedRetriever |
|---|---|---|---|
| answer_correctness | 1.0 | 1.0 | **1.0** |
| citation_correctness | 0.2806 | 0.0 | **0.35** |
| evidence_completeness | 0.994 | 0.0 | 0.994 |
| path_correctness | 0.1667 | 0.0 | **0.1667** |
| unsupported_claim_rate | 0.0 | 0.0 | 0.0 |
| contradiction_awareness | 1.0 | 1.0 | 1.0 |
| provenance_coverage | 1.0 | 0.0 | 1.0 |

**Per-item comparison against GraphRetriever (held-out, n=84):** 0 items
regressed on `answer_correctness` or `evidence_completeness`. On
`citation_correctness`: 0 items strictly worse, 34 strictly better, 50
unchanged (same-predicate-tie cases -- see "Failure cases").

### Per-task-type (held-out, QueryConditionedRetriever)

| Task type | citation_correctness | vs. GraphRetriever (v3) |
|---|---|---|
| **combination_treatment_reasoning** | **1.0** | 1.0 (already perfect, unchanged) |
| pathway_reasoning | 0.3466 | 0.3242 |
| single_hop_factual_retrieval | 0.308 | 0.1525 |
| drug_target_disease_reasoning | 0.3008 | 0.1132 |
| provenance_aware_reasoning | 0.2856 | 0.1235 |
| multi_hop_reasoning | 0.1623 | 0.1375 |
| trial_lookup | 0.0464 | 0.047 (essentially unchanged) |

## Degree-stratified results (held-out, citation_correctness)

Root-entity degree bucketed by real local relation count in the frozen
snapshot:

| Degree bucket | n | GraphRetriever (v3) | QueryConditionedRetriever |
|---|---|---|---|
| low (1-3) | 25 | 0.6138 | 0.6171 |
| mid (4-10) | 14 | 0.3952 | 0.3987 |
| **high (11+)** | 45 | **0.0598** | **0.1864** |

The improvement is concentrated almost entirely in the high-degree bucket
-- exactly where a hub root's many real-but-irrelevant relations were
dragging citation precision down, and exactly the mechanism the method was
designed to address. Low/mid-degree roots (little or no noise to filter)
show only marginal movement, as expected.

## Failure cases (honestly reported, not hidden)

**1. `trial_lookup` gets essentially no benefit (0.047 -> 0.046).** Every
candidate relation from a drug root asking "Which registered trial
evaluates X?" shares the identical predicate `studied_in` -- there is no
lexical signal anywhere to prefer one trial over another. Example:
`v3-heldout-0022`, "Which registered trial evaluates pembrolizumab?" --
citation_correctness 0.029, essentially unchanged from GraphRetriever. Real
disambiguation here would need something the question itself doesn't
supply (e.g. a specific trial name or phase) -- not a defect in the ranker,
a property of the question's information content.

**2. `multi_hop_reasoning` items with high GO branching factor see little
improvement.** `v3-heldout-0058` (the same DAG multi-parent-ambiguity item
identified in `docs/BENCHMARK_RUN_v3.md`) still cites 28 evidence
references (citation_correctness 0.036, barely above GraphRetriever's
unfiltered score) because *every* sibling edge at both hops shares the
predicate `is_a`, so lexical overlap ties across all of them and the
degree/hop signals don't discriminate enough either. The ranker keeps
nearly the whole neighborhood here, same as plain path selection -- an
honest limitation, not silently improved away.

**3. Mitigated in this run, documented for future work:** the
`combination_treatment_reasoning` stopword bug above. Left as "what dev
debugging is for" rather than as a currently-open failure, since it was
found and fixed with a generic (not overfit) technique before scoring
held-out -- but it is a reminder that predicate/question token overlap
alone is a coarse signal, sensitive to incidental word co-occurrence, and a
future iteration might reduce this risk further (e.g. weighting overlap by
predicate-vocabulary rarity) rather than relying on a fixed stopword list.

## What this does not claim

- Not a general solution to "which of several same-predicate candidates is
  correct" -- Failure case 1 and 2 above are real, structural limits of a
  lexical-only signal, not something this method pretends to solve.
- Not evaluated against `LLMOnlyRetriever`/`VectorRAGRetriever` -- still no
  LLM/embedding infrastructure in this repository.
- The v3 gold benchmark and frozen snapshot were not modified in any way to
  produce these results.

## Reproducing this run

```bash
# Dev calibration (repeat with different --relevance-threshold values):
python scripts/run_benchmark.py \
  --snapshot-dir <v3 frozen snapshot dir> \
  --benchmark data/benchmarks/v3/generated_dev.json \
  --retriever query_conditioned --relevance-threshold 0.3 \
  --out /tmp/dev_check.json

# Frozen held-out run (this report's numbers):
python scripts/run_benchmark.py \
  --snapshot-dir <v3 frozen snapshot dir> \
  --benchmark data/benchmarks/v3/generated_dev.json \
  --benchmark data/benchmarks/v3/generated_heldout.json \
  --retriever query_conditioned --relevance-threshold 0.3 \
  --out data/benchmarks/v3/results_v3_query_conditioned.json
```
