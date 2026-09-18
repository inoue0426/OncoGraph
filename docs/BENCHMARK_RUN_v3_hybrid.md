# Semantic + structural hybrid ranking: does it beat lexical-only? (2026-09-18)

A fourth real evaluation, on the **same** frozen snapshot and **same** v3
gold benchmark as `docs/BENCHMARK_RUN_v3.md`/`docs/BENCHMARK_RUN_v3_ranked.md`
-- confirmed unmodified (`git diff` empty on both gold files throughout this
work). This extends `QueryConditionedRetriever` (lexical-only) into
`HybridPathRanker` (lexical + semantic + structural + provenance, with a
hub/branch penalty), and honestly reports whether the extension helps.

**Headline finding, stated up front:** the full 5-component hybrid, at
equal (1.0) weights, **does not outperform** the simpler lexical-only
`QueryConditionedRetriever` on this benchmark, and regresses answer
coverage on two task types. A post-hoc ablation found that a *strict
subset* (lexical + structural, no provenance/semantic/hub penalty)
substantially outperforms everything tested -- but per the stopping rule,
this is reported as a diagnostic finding for future work, not adopted as a
new frozen result in this pass (see "What this is not" below).

## Method

### Semantic signal: local TF-IDF, not a neural embedding

This repository has no ML/embedding dependency (`pyproject.toml`: FastAPI/
SQLModel/uvicorn/typer only). Per the preferred hierarchy (reuse existing
infra -> minimal local option -> avoid heavy runtime cost), a classical,
dependency-free TF-IDF + cosine similarity vector space
(`src/oncograph/semantic.py`, pure Python stdlib) was added instead of a
neural embedding. It is fit **fresh per query**, over that query's own
local candidate-path documents plus the question text -- never a persisted
global model, so there is no separate "model version" to track beyond this
module's source. Semantic text per candidate (`oncograph.rank.relation_document`/
`path_document`) is built from real graph content only: subject/object
name+aliases, the predicate, and evidence context (e.g. a trial edge's
`matched_intervention`/`overall_status`/`phases`, a ChEMBL edge's
`mechanism_of_action`) -- never a gold answer or gold evidence field.

This never runs at site/API runtime -- like every other Retriever in
`oncograph.benchmark`/`oncograph.rank`, it is used only by
`scripts/run_benchmark.py`, never by `main.py`'s `/query/traverse` API or
the public GitHub Pages site.

### Structural + provenance signals

- **Structural**: entity-type/question compatibility (a small, generic
  type-keyword vocabulary, the same kind `web/app.js`'s `FACET_KEYWORDS`
  already uses -- not tuned to this benchmark) averaged with an
  inverse-hop-distance preference.
- **Provenance**: evidence tier (reusing `QueryConditionedRetriever`'s tier
  concept, but *separately* normalized to ~[0,1] -- see "Dev-set debugging"
  below), a verification/publication bonus, and (Issue #11 trial context)
  a small bonus for an exact `matched_intervention` match and a known
  `overall_status` -- real fields, never a preference correlated with any
  specific benchmark item's gold trial.
- **Hub/branch penalty**: local-degree penalty (as in `QueryConditionedRetriever`)
  plus an *additional* penalty for GO terms with a high local branching
  factor (`oncograph.rank.go_branch_factor`: how many locally-reached
  entities `is_a`-point to this one). Computed only from relations already
  touched by this query's own traversal -- GO's `is_root`/`child_count`
  metadata (computed by `sources/gene_ontology.py` at import time) is not
  carried into the frozen public snapshot this benchmark reads
  (`scripts/build_static_site.py` only exports metadata for PAPER/GENE
  types), and the frozen snapshot must not be modified to add it
  retroactively -- so this is a local, snapshot-safe proxy instead.

Every component is a named, inspectable field on `oncograph.rank.ComponentScores`
(`lexical`, `semantic`, `structural`, `provenance`, `hub_branch_penalty`,
`combined`) -- `HybridPathRanker.score_candidates()` returns them directly,
so nothing is opaque.

### Model: `oncograph.rank.HybridPathRanker`

`combined = (w_lex*lexical + w_sem*semantic + w_struct*structural + w_prov*provenance) / (1 + w_hub*hub_branch_penalty)`,
then the same relative-threshold keep/drop rule as `QueryConditionedRetriever`
(entities scoring below `relative_threshold * max_combined` are dropped;
the degenerate all-zero case keeps everyone). `HybridWeights` lets any
component be zeroed for a clean ablation without a separate code path.

`QueryConditionedRetriever` itself (and its already-reported
`docs/BENCHMARK_RUN_v3_ranked.md` result) is completely unmodified.

## Dev-set debugging (one documented calibration phase)

Only `data/benchmarks/v3/generated_dev.json` (21 items) was used for
debugging/calibration; held-out (84 items) was scored exactly once per
configuration, after freezing.

**A real scale bug found and fixed (not a rule about a specific item):**
the first version combined `provenance` (raw tier weight, 0.5-3.0 scale)
at equal nominal weight to `lexical` (0-2ish per hop), which let
provenance's larger absolute magnitude dilute a lexical signal that was
working well. Fixed by normalizing the tier-weight term to ~[0,1] inside
`provenance_component` specifically for the hybrid ranker (leaving
`QueryConditionedRetriever`'s own, already-frozen tier usage untouched).

**A second scale issue found the same way:** the trial-context specificity
bonus (added for Issue #4's trial_lookup requirement) was initially large
enough (+0.5/+0.25) to make a `studied_in` trial edge's provenance score
*exceed* a `targets` gene edge's, actively hurting `single_hop_factual_retrieval`
instead of only helping disambiguate among trials. Reduced to +0.15/+0.1
(a tie-breaker magnitude, not a dominant one).

**Threshold sweep on dev**, full hybrid (all weights 1.0), selecting the
value maximizing `citation_correctness` subject to `answer_correctness`
staying at 1.0:

| relative_threshold | answer_correctness | citation_correctness |
|---|---|---|
| **0.2 - 0.3 (plateau)** | **1.0** | **0.2335** |
| 0.35 | 0.944 | 0.2309 |
| 0.4 | 0.929 | 0.2343 |
| 0.45 | 0.929 | 0.3875 |
| 0.5 - 0.6 | <= 0.881 | 0.37 - 0.39 |

**Frozen configuration: `relative_threshold = 0.3`, `HybridWeights(lexical=1, semantic=1, structural=1, provenance=1, hub=1)`** -- the plain, unweighted combination of all four positive signals with the hub penalty active, chosen because it sat on dev's recall-safe plateau, not because it produced the best dev citation_correctness (0.2335 was in fact the *lowest* citation_correctness on the recall-safe plateau; a higher threshold traded recall for precision, which the "no recall loss" criterion rejected, consistent with the same rule used for `QueryConditionedRetriever`). Not touched again after this point.

## Held-out results (n=84, one run per configuration, frozen configuration)

| Metric | GraphRetriever (v3) | QueryConditionedRetriever (v3, lexical) | HybridPathRanker (full) |
|---|---|---|---|
| answer_correctness | 1.0 | 1.0 | **0.9881** |
| citation_correctness | 0.2806 | **0.35** | 0.2816 |
| evidence_completeness | 0.994 | 0.994 | 0.9702 |
| path_correctness | 0.1667 | 0.1667 | 0.1667 |
| provenance_coverage | 1.0 | 1.0 | 0.9881 |
| unsupported_claim_rate | 0.0 | 0.0 | 0.0 |

**The full hybrid does not beat lexical-only, and its `relative_threshold`
generalized slightly worse from dev to held-out than `QueryConditionedRetriever`'s
did**: dev showed `answer_correctness = 1.0`, but held-out shows `0.9881`
(1 of 84 items -- a real, disclosed dev/held-out generalization gap, not
corrected after the fact, since doing so would mean tuning against
held-out).

### Per-task-type citation_correctness (held-out)

| Task type | GraphRetriever | QueryConditioned | Hybrid (full) |
|---|---|---|---|
| combination_treatment_reasoning | 1.0 | 1.0 | 1.0 |
| pathway_reasoning | 0.347 | 0.347 | 0.347 |
| single_hop_factual_retrieval | 0.180 | 0.308 | 0.180 |
| trial_lookup | 0.046 | 0.046 | 0.046 |
| provenance_aware_reasoning | 0.143 | 0.286 | 0.143 |
| **drug_target_disease_reasoning** | **0.092** | **0.301** | **0.092** |
| multi_hop_reasoning | 0.155 | 0.162 | 0.163 |

On `single_hop_factual_retrieval`, `provenance_aware_reasoning`, and
`drug_target_disease_reasoning`, the full hybrid's citation_correctness
falls back to *exactly* GraphRetriever's level -- the extra components
neutralize the gain `QueryConditionedRetriever` achieved with lexical
overlap alone on these task types.

### Degree-stratified citation_correctness (held-out)

| Degree bucket | n | GraphRetriever | QueryConditioned | Hybrid (full) |
|---|---|---|---|---|
| low (1-3) | 25 | 0.6138 | 0.6171 | 0.6159 |
| mid (4-10) | 14 | 0.3952 | 0.3987 | 0.3982 |
| **high (11+)** | 45 | **0.0598** | **0.1864** | **0.0596** |

The full hybrid's high-degree gain **disappears entirely** -- 0.0596,
statistically indistinguishable from GraphRetriever's unfiltered 0.0598,
and far below `QueryConditionedRetriever`'s 0.1864. This is the single
clearest sign that adding semantic/provenance/hub-penalty on top of
lexical, at equal weight, cancels out exactly the mechanism that made the
lexical-only version work.

### Hop-count-stratified citation_correctness (held-out)

| Hops | GraphRetriever | QueryConditioned | Hybrid (full) |
|---|---|---|---|
| 1 | 0.3015 | 0.3812 | 0.3015 |
| 2 | 0.1551 | 0.1623 | 0.1625 |

### trial_lookup subset (held-out, n=12)

Identical across all three retrievers (`citation_correctness = 0.0464-0.0470`,
`answer_correctness = 1.0`). The trial-context specificity signal (exact
`matched_intervention` match, known `overall_status`) was implemented and
is real, but **every candidate trial in this task's items is an equally
valid, precisely-matched, well-attested record** -- the benchmark's own
`trial_lookup` question template ("Which registered trial evaluates
{drug}?") never names a disease, phase, or status to match against, so
there is no signal in the *question* for any context field to discriminate
on. This is an information-availability limit of the benchmark item design,
not a defect in the scoring machinery -- confirmed, not newly discovered,
by this run.

### multi_hop_reasoning subset (held-out, n=12)

| Metric | GraphRetriever | QueryConditioned | Hybrid (full) |
|---|---|---|---|
| answer_correctness | 1.0 | 1.0 | **0.9167** |
| evidence_completeness | 0.9583 | 0.9583 | **0.7917** |
| citation_correctness | 0.1551 | 0.1623 | 0.1625 |

The hub/branch penalty designed to suppress generic GO terms instead
**dropped a legitimate first-hop gold parent** on one item (see Failure
case 2 below) -- a real regression this task type's own structure
(high-branching DAGs) makes the branch penalty risky to apply uniformly.

## Ablations (diagnostic, run once each at the frozen threshold=0.3; not separately dev-calibrated)

| Configuration | answer_correctness | citation_correctness | evidence_completeness | path_correctness |
|---|---|---|---|---|
| lexical only (hub=0) | 0.786 | 0.530 | 0.820 | 0.107 |
| semantic only | 0.857 | 0.348 | 0.891 | 0.048 |
| structural only | **1.0** | 0.281 | 0.994 | 0.167 |
| lexical + semantic | 0.786 | 0.532 | 0.820 | 0.107 |
| **lexical + structural** | 0.929 | **0.528** | 0.923 | **0.25** |
| full hybrid (frozen) | 0.988 | 0.282 | 0.970 | 0.167 |

Full raw results: `data/benchmarks/v3/results_ranked_hybrid_ablations.json`.

**Reading this honestly:** every ablation that includes `provenance` and/or
`hub` performs worse on citation/path precision than the ones that don't.
`structural only` is the single safest configuration (perfect recall,
citation_correctness matching GraphRetriever) -- structural signals alone
neither help nor hurt much. `lexical + structural` (no provenance, no
semantic, no hub penalty) is the standout: citation_correctness 0.528 (vs.
lexical-only `QueryConditionedRetriever`'s already-reported 0.35),
path_correctness 0.25 (the best of any configuration tested across all
four benchmark runs), and per the degree/hop breakdown script, its
high-degree-bucket citation_correctness reaches 0.513 -- roughly 8.6x
GraphRetriever's 0.0598, far beyond `QueryConditionedRetriever`'s already
large 3x gain. Its recall (0.929) is below the two frozen, dev-calibrated
retrievers' 1.0, an honest cost of not having separately calibrated a
recall-safe threshold for this specific weight combination.

### Why this ablation result is *not* adopted as this pass's result

This was discovered by looking at **held-out** numbers across the ablation
matrix -- exactly the kind of held-out-informed selection this task's own
stopping rule prohibits ("Do not repeatedly tune until headline metrics
improve"). Treating `lexical + structural` as the new frozen answer now
would mean picking the winning configuration *because* it scored best on
held-out, which is the same failure mode as tuning against the test set
one level up (choosing among several pre-registered configurations by
their held-out score, rather than choosing one via dev and reporting its
held-out score once). It is reported here as a legitimate, valuable
**diagnostic finding for a future, separate calibration pass** -- with its
own dev-only threshold sweep, scored once on held-out on its own -- not as
a result of this one.

## Failure analysis (concrete, categorized, not patched)

1. **Generic predicate collision (`trial_lookup`, unresolved).** "Which
   registered trial evaluates pembrolizumab?" -- every candidate shares the
   predicate `studied_in`; no context field in the *question* to match
   against. `v3-heldout-0022`: citation_correctness 0.029-0.046 across
   every retriever tested in this project so far. Category: **insufficient
   trial metadata in the question**, not the graph -- the graph *does*
   carry `matched_intervention`/`overall_status`/`phases`, there's simply
   nothing in the question to compare them to.

2. **GO DAG ambiguity, now with a hub-penalty-induced regression.**
   `v3-heldout-0053` ("Through which successive parent GO terms does
   'taxadiene synthase activity' chain?", gold
   `[GO:0016838, GO:0016835]`): the full hybrid's prediction includes
   `GO:0016835` (the second hop) but **never reaches `GO:0016838`** (the
   first hop) at all, while keeping ~60 other GO terms from a
   high-branching neighborhood. The `go_branch_factor` penalty, applied
   uniformly, suppressed a legitimate direct parent while a flatter,
   noisier set of distant terms cleared the (now much lower, because
   `max_combined` itself is depressed in a high-branching neighborhood)
   relative threshold. Category: **GO DAG ambiguity** compounded by
   **structural penalty over-correction** -- not patched; the branch
   penalty is a real, principled signal in general, but this shows it can
   misfire on specific high-branching local topologies.

3. **Semantic ambiguity / weak topical signal (`multi_hop_reasoning`, GO
   `is_a` chains generally).** TF-IDF cosine similarity between a question
   like "...chain (is_a x2)?" and a candidate path's document offers only
   a marginal signal once many siblings share the identical `is_a`
   predicate and similarly generic GO term names -- semantic-only's
   citation_correctness (0.155, matching GraphRetriever) confirms this
   component alone contributes essentially nothing extra here. Category:
   **semantic ambiguity** -- the signal exists but is too weak to
   discriminate at this granularity.

4. **Coverage gap example (`drug_target_disease_reasoning`).**
   `v3-heldout-0036` ("What disease is miglitol approved for, and via
   which target?"): `lexical_structural` correctly narrows to 2 cited
   relations (citation_correctness 0.5); the full hybrid cites 11
   (citation_correctness 0.18) because provenance/semantic/hub-adjusted
   scores for several unrelated `indicated_for`/associated-disease edges
   cleared the relative threshold. Category: **generic predicate
   collision** again, but this time specifically caused by the *added*
   components raising the score floor for irrelevant candidates, not by a
   lack of lexical signal (lexical alone handled this item correctly).

No entity-resolution-issue or coverage-gap-in-the-graph-itself case was
found in this batch of failures -- every failure here is about *ranking*
among real, correctly-retrieved candidates, not about missing or
unresolvable graph data.

## What this is not

- Not a claim that semantic/structural signals are useless -- the ablation
  results show real, substantial value in specific combinations
  (`lexical + structural`). It is a claim that the specific,
  equal-weighted, all-five-components-at-once design proposed and frozen
  in this pass underperforms a simpler one, honestly measured.
- Not re-tuned after seeing held-out numbers. The frozen full-hybrid
  configuration's held-out result is reported as-is, including its
  recall regression.
- Not a change to `QueryConditionedRetriever`, the v3 gold benchmark, or
  the frozen graph snapshot.
- `lexical + structural`'s strong ablation numbers are not claimed as this
  pass's delivered result -- see "Why this ablation result is not adopted"
  above.

## Reproducibility

| Field | Value |
|---|---|
| Graph snapshot | `graph_version 2026-09-18T01:07:18Z`, refresh-data run [35289068710](https://github.com/inoue0426/OncoGraph/actions/runs/35289068710) |
| Benchmark version | v3 (`data/benchmarks/v3/generated_dev.json` + `generated_heldout.json`, seed `20260918`, unmodified) |
| Semantic "embedding" | `oncograph.semantic.TfidfSpace` -- no external model; deterministic given the module's own source and each query's local corpus |
| Frozen hyperparameters | `relative_threshold=0.3`, `HybridWeights(lexical=1.0, semantic=1.0, structural=1.0, provenance=1.0, hub=1.0)` |
| Dev sweep | Table above; full per-threshold JSON logs were scratch (`/tmp/bench_scratch/hybrid_dev_*.json`), not committed -- the sweep table here is the durable record |
| Held-out results | `data/benchmarks/v3/results_ranked_hybrid.json` (full hybrid), `data/benchmarks/v3/results_ranked_hybrid_ablations.json` (5 ablations) |

## Reproducing this run

```bash
# Dev calibration (repeat with different --relevance-threshold values):
python scripts/run_benchmark.py \
  --snapshot-dir <v3 frozen snapshot dir> \
  --benchmark data/benchmarks/v3/generated_dev.json \
  --retriever hybrid --relevance-threshold 0.3 \
  --out /tmp/dev_check.json

# Frozen held-out run (this report's headline numbers):
python scripts/run_benchmark.py \
  --snapshot-dir <v3 frozen snapshot dir> \
  --benchmark data/benchmarks/v3/generated_dev.json \
  --benchmark data/benchmarks/v3/generated_heldout.json \
  --retriever hybrid --relevance-threshold 0.3 \
  --out data/benchmarks/v3/results_ranked_hybrid.json

# One ablation (repeat with the other weight combinations in the table above):
python scripts/run_benchmark.py \
  --snapshot-dir <v3 frozen snapshot dir> \
  --benchmark data/benchmarks/v3/generated_dev.json \
  --benchmark data/benchmarks/v3/generated_heldout.json \
  --retriever hybrid --relevance-threshold 0.3 \
  --weight-lexical 1 --weight-semantic 0 --weight-structural 1 --weight-provenance 0 --weight-hub 0 \
  --out /tmp/ablation_lexical_structural.json
```
