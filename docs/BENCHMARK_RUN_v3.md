# Benchmark run v3: rerun after Issues #10/#11, with the path-selection fix (2026-09-18)

A second real evaluation, on a newer frozen snapshot that includes Issues
#10 and #11's real data, using the same protocol as `docs/BENCHMARK_RUN_v2.md`
(seeded generation, dev/held-out split, one unmodified scoring pass). This
run also measures the effect of `graph_retrieval_to_prediction()`'s
principled-path-selection fix on the exact same kind of gold set v2 used
(generated fresh for this snapshot, but by the same unmodified generator/
methodology) -- **the fix was made before this run, not in response to it**.

## What the user asked for vs. what turned out to be real

The request was to add contradiction, drug-response, publication-attribution,
and combination-treatment benchmark tasks "where supported." After
Issues #10/#11, only **one** of those four is actually backed by real data
in the deployed graph:

| Requested task | Backed by real data after #10/#11? |
|---|---|
| combination-treatment | **Yes** -- 725 real `CombinationTreatment` entities from ClinicalTrials.gov cross-drug matches (Issue #11). Generated for real, see below. |
| contradiction | No. No adapter in this repository has ever produced two evidence rows with opposing `claim_state` (SUPPORTS vs CONTRADICTS) on the same relation. Still only covered by `v1`'s one `illustrative_synthetic` item. |
| drug-response | No. `sources/drug_response.py` (Issue #6) is still schema/adapter-only; no real drug-response dataset is wired into any pipeline. Still only covered by `v1`'s one `illustrative_synthetic` item. |
| publication-attribution | No. No Publication (`paper`) entities exist in the deployed graph (Europe PMC isn't wired into the scheduled refresh). `v1`'s one item for this task type is `verified_live_data` from a separate curated citation file, not the deployed graph itself. |

Generating real items for the other three would mean fabricating data --
not done. This is reported as a finding, not papered over.

## Frozen snapshot

| Field | Value |
|---|---|
| `graph_version` | `2026-09-18T01:07:18Z` |
| Total entities | 98,547 (drug 3,012, gene 45,104, disease 2,034, trial 8,892, go_term 38,092, protein 635, tissue 53, **combination_treatment 725**) |
| Relations | 109,098 (up from v2's 88,032) |
| Distinct sources | 9 (v2's 5, plus `drugmechdb`, `chembl`, `trrust`, `gtex`) |
| `paths.mechanistic` | 4,502 (DrugMechDB curated paths, new this run) |
| `paths.benchmark_gold` | 97 |

From GitHub Actions run [35289068710](https://github.com/inoue0426/OncoGraph/actions/runs/35289068710), deployed by Pages run 35295400667 -- the same artifact the public site was serving when this benchmark ran.

## Item generation

105 items (seed `20260918`), same 6 task types as v2 plus the new one:

| Task type | Count |
|---|---|
| single_hop_factual_retrieval | 15 |
| trial_lookup | 15 |
| pathway_reasoning | 15 |
| drug_target_disease_reasoning | 15 |
| multi_hop_reasoning | 15 |
| **combination_treatment_reasoning** (new) | 15 |
| provenance_aware_reasoning | 15 |

Split 21 dev / 84 held-out (stratified, 3/12 per task type). `combination_treatment_reasoning`
items ask which drugs are combined in a real trial, with gold answers/evidence
drawn directly from real `has_component`/`tested_in` edges (`generate_combination_treatment_items`).

## The path-selection fix (made before this run)

`graph_retrieval_to_prediction()` previously cited every relation a BFS
neighborhood traversal touched. Fixed to cite only relations on the
shortest path (`RetrievalResult.paths`) to each reached entity -- see the
commit that changed `src/oncograph/benchmark.py` and
`docs/BENCHMARKING.md`. The fix and its test
(`test_graph_retrieval_to_prediction_uses_principled_path_selection_not_whole_neighborhood`)
were written and merged **before** this run; this run measures its real
effect, it did not motivate ad hoc changes after seeing v3's numbers.

## Results (held-out set, n=84, one run, unmodified afterward)

| Metric | GraphRetriever (v3) | GraphRetriever (v2) | VanillaGraphRetriever (v3) |
|---|---|---|---|
| answer_correctness | 1.0 | 1.0 | 1.0 |
| citation_correctness | **0.2806** | 0.1523 | 0.0 |
| evidence_completeness | 0.994 | 1.0 | 0.0 |
| path_correctness | **0.1667** | 0.0139 | 0.0 |
| unsupported_claim_rate | 0.0 | 0.0 | 0.0 |
| contradiction_awareness | 1.0 | 1.0 | 1.0 |
| provenance_coverage | 1.0 | 1.0 | 0.0 |

citation_correctness nearly doubled (0.15 -> 0.28) and path_correctness
increased more than 10x (0.014 -> 0.167). These are not directly the same
items as v2 (a new seed, on a new snapshot, plus a new task type), so this
is not a strict before/after A-B test of the fix in isolation -- but the
per-task-type breakdown below shows exactly where the improvement is real
and where it structurally cannot help, which is the actual, honest
attribution.

### Per-task-type (held-out, GraphRetriever)

| Task type | citation_correctness | path_correctness | evidence_completeness |
|---|---|---|---|
| **combination_treatment_reasoning** | **1.0** | **1.0** | 1.0 |
| pathway_reasoning | 0.3242 | 0.0 | 1.0 |
| single_hop_factual_retrieval | 0.1525 | 0.0667 | 1.0 |
| multi_hop_reasoning | 0.1375 | 0.0 | 0.9333 |
| drug_target_disease_reasoning | 0.1132 | 0.0 | 1.0 |
| provenance_aware_reasoning | 0.1235 | 0.0667 | 1.0 |
| trial_lookup | 0.047 | 0.0 | 1.0 |

## Two justified follow-up analyses (no further code changes)

**1. The fix perfectly solves star-shaped tasks with no extraneous edges,
and only partially helps star-shaped tasks with many extraneous edges.**
`combination_treatment_reasoning` scores a clean 1.0 on every citation/path
metric: a `CombinationTreatment` entity's *only* relations are exactly its
`has_component`/`tested_in` edges, so "the shortest path to each reached
entity" is exactly the gold set, with nothing extra. `trial_lookup`/
`drug_target_disease_reasoning`/`single_hop_factual_retrieval` are also
star-shaped (root -> several directly-owned facts) but the root (a drug or
GO term) legitimately owns many *other* real relations too (many trials,
many GO edges) -- each of those is *itself* a valid shortest path to a real,
different entity, so principled path selection correctly keeps citing them.
Checked directly: root-entity degree still correlates with
`citation_correctness` at Pearson **-0.62** (n=84, slightly stronger than
v2's -0.53, expected since the fix removed the *other* source of bloat --
touched-but-unreached back-edges -- leaving the degree effect as the
dominant remaining one). Fixing this further needs *answer-directed*
evidence selection (cite only evidence for entities actually named in
`answer_canonical_ids` relevant to the question), which is a different,
larger change than a path-selection fix and is not made here.

**2. `evidence_completeness` < 1.0 on one `multi_hop_reasoning` item is a
real DAG multi-parent ambiguity, not a retrieval bug.** Item `v3-heldout-0058`
asks for the chain `GO:0006622 -is_a-> GO:0007041 -is_a-> GO:0007034`. The
first hop is correctly cited; the second is not, because `GO:0007034` has
*more than one* real `is_a` parent in the deployed graph (both `GO:0007041`
and `GO:0006623` point to it), and `traverse()`'s BFS recorded whichever
equally-short path it discovered first (`GO:0006623`'s), not the curator's
chosen one. The retrieved fact and its citation are both real and correct
-- the benchmark item's single designated "the" gold chain is just one of
several equally valid ones through a DAG, not a tree. Not treated as a bug
to patch (that would mean picking a path to match one specific gold item,
which generalizes to nothing) -- documented as an inherent property of
GO's parent structure instead.

## Retrievers run (same as v2)

`GraphRetriever` and `VanillaGraphRetriever` (real). `LLMOnlyRetriever`/
`VectorRAGRetriever`: **not run** -- still no LLM/embedding infrastructure
in this repository.

## Reproducing this run

```bash
python scripts/generate_benchmark_items.py \
  --snapshot-dir <dir with search-index.json + relations.json> \
  --graph-version 2026-09-18T01:07:18Z --seed 20260918 --per-task 15 --version v3 \
  --out-dev data/benchmarks/v3/generated_dev.json \
  --out-heldout data/benchmarks/v3/generated_heldout.json

python scripts/run_benchmark.py \
  --snapshot-dir <same dir> \
  --benchmark data/benchmarks/v3/generated_dev.json \
  --benchmark data/benchmarks/v3/generated_heldout.json \
  --retriever graph_retriever --retriever vanilla_graph_retriever \
  --out data/benchmarks/v3/results_v3.json
```
