# MCP server (Issue #13)

**Research use only.** OncoGraph's MCP server exposes structured oncology
knowledge-graph data -- entities, relations, and their evidence -- to MCP
clients (agents, LLMs, notebooks). It is not a medical-advice layer: every
tool returns provenance-attached facts as stored, never a clinical
recommendation, an efficacy claim, or a synthesized conclusion. See
"Provenance behavior" below before building anything on top of it.

## What this is

A thin [Model Context Protocol](https://modelcontextprotocol.io) layer
(`src/oncograph/mcp/`) over the existing graph API -- `oncograph.query`
(entity resolution, BFS traversal), `oncograph.rank` (ranking strategies),
and `oncograph.stats` (coverage statistics). It does not duplicate
canonicalization, evidence normalization, or traversal logic: every tool
opens a database session and delegates immediately to those modules. It
reads the **live database** (same `ONCOGRAPH_DATABASE_URL` as the FastAPI
app, `oncograph.main`), not a frozen static export.

It is purely additive: it does not modify the public Explorer, GitHub
Pages, the existing FastAPI endpoints, `refresh-data.yml`, or the
benchmark scripts/results (`scripts/run_benchmark.py`, `data/benchmarks/`).

## Installation

```bash
pip install -e '.[mcp]'
# or, if you also want the dev tooling (tests, ruff):
pip install -e '.[dev]'   # dev already includes the mcp extra
```

## Starting the server

The server reads the same database the rest of OncoGraph uses
(`ONCOGRAPH_DATABASE_URL`, default `sqlite:///./oncograph.db`) and the same
versioned benchmark directory (`data/benchmarks/`, for the stored-path
count in `get_graph_stats`) relative to the current working directory --
run it from the repository root, after `oncograph seed` (or a real
`oncograph import-source ...` run) has populated a database.

```bash
oncograph seed   # or import real sources -- see the main README

oncograph-mcp
# or, equivalently:
python -m oncograph.mcp.server
```

### stdio transport

This pass supports **stdio only** (no hosted/remote server, no
Streamable HTTP/SSE) -- the process communicates over stdin/stdout using
the MCP protocol, which is what every point-and-run MCP client (Claude
Desktop/Code, other local agents) expects for a local tool server. There
is no separate "start a listener" step: the client launches
`oncograph-mcp` as a subprocess.

### Example client configuration

Most MCP-compatible clients (Claude Desktop, Claude Code, etc.) take a
JSON block naming the command to launch:

```json
{
  "mcpServers": {
    "oncograph": {
      "command": "oncograph-mcp",
      "env": {
        "ONCOGRAPH_DATABASE_URL": "sqlite:////absolute/path/to/oncograph.db"
      }
    }
  }
}
```

Or, running from a source checkout without installing the console script:

```json
{
  "mcpServers": {
    "oncograph": {
      "command": "python",
      "args": ["-m", "oncograph.mcp.server"],
      "cwd": "/absolute/path/to/OncoGraph",
      "env": {
        "ONCOGRAPH_DATABASE_URL": "sqlite:////absolute/path/to/oncograph.db"
      }
    }
  }
}
```

## Core design principles

- Reuses `oncograph.query.resolve_entity`/`traverse` for every lookup and
  traversal -- entity resolution (UUID, canonical ID, or exact name) and
  BFS semantics are identical to the FastAPI `/query/traverse` endpoint.
- Reuses `oncograph.rank`'s retrievers for ranking (see below).
- Reuses `oncograph.stats.compute_stats` (moved out of
  `scripts/build_static_site.py` into the package specifically so both the
  static-site build and the MCP layer share one counting implementation --
  see that module's docstring) for `get_graph_stats`.
- Every tool returns JSON-compatible `dict`s -- entities/relations/evidence
  keep their original field names and predicate/claim_state/evidence_type
  values exactly as stored.
- Every tool enforces a result-count cap (`limit`, clamped to 200) and,
  for traversal, a hop cap (`max_hops`, clamped to 5) -- no tool can dump
  the whole graph.

## Tools

All 12 tools are registered under these exact names. Every tool validates
its own arguments and raises a clear MCP `ToolError` (visible to the
caller as `is_error=True` with the message, never a raw traceback) for an
unknown entity, an invalid `entity_type`, or an invalid
`retrieval_strategy`.

### `search_entities(query, entity_type=None, limit=20)`

Ranked search by canonical ID, name, or alias/metadata substring. Ranking:
exact canonical_id > exact name > name-prefix > substring, ties broken by
name. Each result: `id`, `type`, `name`, `canonical_id`, `description`,
`aliases`, `metadata`, `relation_count`, `evidence_source_count`.

```
search_entities("gefitinib")
search_entities("EGFR")
```

Because entity resolution is identifier-first (not merged across sources),
searching a well-studied drug name can legitimately return **several**
entities -- one per source's own identifier namespace (e.g. a
GtoPdb-keyed, a ChEMBL-keyed, and a DrugMechDB/MESH-keyed "gefitinib").
This is not a bug: it is the same known cross-adapter identifier-crosswalk
gap documented in `docs/BIOLOGICAL_SOURCES.md`/`docs/MECHANISTIC_SOURCES.md`,
surfaced honestly rather than silently merged.

### `get_entity(entity_id)`

Canonical entity data plus a relation summary (`relation_count`,
`evidence_source_count`, `distinct_predicates`). `entity_id` may be a
UUID, canonical ID, or exact name (`oncograph.query.resolve_entity`).

### `get_neighbors(entity_id, predicate=None, entity_type=None, limit=50)`

Direct (1-hop) neighbors and the exact relations connecting them.

### `get_evidence(relation_id)`

Every evidence record for one relation (by relation UUID -- see
`get_entity`'s `distinct_predicates`/`get_neighbors`' relations for how to
find one), preserving `source`, `source_id`, `source_url`, `source_type`,
`evidence_type`, `license`, `publication_id`, `context`, `confidence`,
`claim_state`, `verification_status`, and `retrieved_at` exactly as
stored -- nothing here is summarized into a single claim.

### `traverse_graph(entity_id, max_hops=2, predicate=None, source=None, min_confidence=None, require_publication=False, limit=100, retrieval_strategy="query_conditioned", question=None)`

Evidence-aware N-hop traversal (`max_hops` capped at 5). Returns reached
entities, the relations connecting them (each with full evidence), the
shortest computed path (relation-id chain, from `oncograph.query.traverse`)
to each entity, and `contradictory_relation_ids` (relations with both
`SUPPORTS` and `CONTRADICTS` evidence). `question` is an optional
natural-language hint (not in the original tool-signature sketch, added
because it is what makes `retrieval_strategy` meaningfully different from
`"graph"` -- see below); omitted, the ranking strategies degrade
gracefully to "keep everything reachable", identical to `"graph"`.

### Domain convenience tools

Thin wrappers, no new query semantics beyond filtering to a real,
already-emitted `evidence_type`/entity-type vocabulary -- never a guessed
predicate list.

- **`find_drugs_for_disease(disease, limit=20)`** -- drugs with any direct
  real relation to the disease (not restricted to one predicate, since
  different sources use different real predicates for a drug-disease
  relationship).
- **`find_trials(query=None, disease=None, drug=None, status=None, limit=20)`**
  -- registered trials matching any combination of filters. Trial
  registration only -- see "Provenance behavior".
- **`find_drug_mechanism(drug, disease=None, max_hops=4, limit=20)`** --
  the drug's mechanism-of-action relations, identified by `evidence_type`
  (ChEMBL, DrugMechDB, SIGNOR, DrugCentral, GtoPdb primary targets, DGIdb --
  see `docs/MECHANISTIC_SOURCES.md`), never by guessing at predicate names
  (DrugMechDB's own predicate text is dynamic).
- **`find_mechanism_paths(drug, disease=None, max_hops=4, limit=20)`** --
  the ordered-path form of the same data; see "Path semantics" below for
  the `path_type` distinction this tool exists to make explicit.
- **`find_combination_treatments(drug=None, disease=None, limit=20)`** --
  real `CombinationTreatment` entities (Issue #11, derived from
  ClinicalTrials.gov trials matched to 2+ drugs) with their component
  drugs and trial(s).
- **`find_contextual_response_evidence(drug, disease=None, model=None, biomarker=None, limit=20)`**
  -- context-specific drug-response evidence (`sources/drug_response.py`).
  **Currently always returns an empty result with an explanatory note**:
  no real drug-response dataset is wired into the scheduled pipeline yet
  (`docs/DRUG_RESPONSE.md`, Issue #6 is schema/adapter-only). This is
  reported honestly rather than fabricated.

### `get_graph_stats()`

Canonical coverage statistics -- entity counts by type, total
entities/relations, evidence-record and distinct-source counts, and (when
present) explicit stored/curated path counts, `graph_version`,
`generated_at`. Identical output to `web/data/stats.json` and the
`oncograph://stats` resource, computed by the same
`oncograph.stats.compute_stats` function against the live database.

## Retrieval-strategy handling

`traverse_graph`'s `retrieval_strategy` selects which `oncograph.rank`/
`oncograph.query` `Retriever` runs the traversal:

| Value | Retriever | Status |
|---|---|---|
| `"graph"` | `GraphRetriever` | Evidence-aware, no ranking -- every relation with evidence is kept. |
| **`"query_conditioned"` (default)** | `QueryConditionedRetriever` | Lexical relevance ranking. Dev-calibrated and held-out-validated (`docs/BENCHMARK_RUN_v3_ranked.md`): citation_correctness 0.28 -> 0.35 on the project's own benchmark, with zero recall regressions. **The safest, currently-recommended strategy.** |
| `"hybrid_experimental"` | `HybridPathRanker` | Semantic + structural ranking. **Experimental.** Its own evaluation (`docs/BENCHMARK_RUN_v3_hybrid.md`) found it does *not* beat `query_conditioned` and regresses answer coverage on some multi-hop items. Offered for comparison, never selected automatically. |

The relative-threshold hyperparameter both ranking strategies use is fixed
at the dev-calibrated, held-out-validated value (`0.3`,
`oncograph.mcp._common.VALIDATED_RELATIVE_THRESHOLD`) -- not the generic
module default.

**Rules enforced by the MCP layer:**
- The default is always `"query_conditioned"` -- never silently upgraded
  or downgraded to something else.
- `"hybrid_experimental"` is used **only** when a caller passes it
  explicitly (`tests/test_mcp_server.py::test_traverse_graph_never_uses_hybrid_experimental_unless_explicitly_requested`
  asserts this directly).
- An unrecognized `retrieval_strategy` string is a validation error
  (`ToolError`), never a silent fallback to any default.
- No benchmark gold label, held-out item, or benchmark-specific scoring
  logic is reachable from any tool -- `oncograph.benchmark`'s
  `score_prediction`/`BenchmarkItem`/gold-answer machinery is not imported
  anywhere in `oncograph.mcp`.

## Path semantics

`find_mechanism_paths` and `traverse_graph` return **two structurally
different kinds of path**, and every path object is tagged with which one
it is:

- **`path_type: "stored_curated"`** -- an explicit, human-curated path
  record that exists in the graph independent of any query (currently:
  DrugMechDB's `implicated_in_mechanism_for` relations, each of which
  carries its *entire* curated drug -> ... -> disease mechanism chain in
  `evidence.context` -- see `sources/drugmechdb.py` and
  `docs/MECHANISTIC_SOURCES.md`). Read back exactly as stored, never
  recomputed.
- **`path_type: "computed_traversal"`** -- a path found by BFS at query
  time (`oncograph.query.traverse`'s own shortest-path bookkeeping). Real
  and evidence-backed, but **never** presented as curated.

A path object always includes ordered `nodes`, the relation chain
(`relation_ids` or, for stored paths, `relation_predicates`), `predicates`,
`length`, and an `evidence_summary`/`source` for provenance. No tool ever
labels an arbitrary computed traversal as a curated path, and no tool
invents a path that isn't backed by a real relation.

(`data/benchmarks/`'s own gold-evidence paths -- Issue #9's benchmark
infrastructure -- are a third, separate notion of "path", used only for
scoring retrieval strategies offline; they are not exposed by any MCP
tool, and `get_graph_stats`'s `paths.benchmark_gold` count is metadata
about the benchmark suite, not something a tool call can retrieve item by
item.)

## MCP resources

Small, read-only, metadata-only resources -- never the graph itself:

- **`oncograph://stats`** -- identical to `get_graph_stats()`.
- **`oncograph://schema`** -- the entity-type vocabulary
  (`oncograph.models.EntityType`) and evidence-quality enums
  (`ClaimState`, `VerificationStatus`). Predicates are an intentionally
  open vocabulary (see `docs/EVIDENCE.md`), not listed as a fixed enum.
- **`oncograph://sources`** -- every registered source adapter's
  license/provenance descriptor (`oncograph.sources.registry`), including
  scaffold-only adapters -- see `docs/SOURCES.md`,
  `docs/BIOLOGICAL_SOURCES.md`, `docs/MECHANISTIC_SOURCES.md`,
  `docs/TREATMENT_RESPONSE_CONTEXT.md`.
- **`oncograph://version`** -- the `oncograph` package version and the
  deployed graph's `graph_version` (see "Graph/data version behavior").

## Provenance behavior

The MCP layer preserves relation semantics **exactly** -- it never
upgrades, infers, or summarizes a claim into something stronger than what
the evidence actually says:

- `studied_in` (a drug was tested in a trial) is never presented as
  "effective for" -- trial registration is not evidence of efficacy.
- `associated_with` is never presented as "causes".
- A trial's registration is never conflated with demonstrated clinical
  efficacy.
- Preclinical/model-system response data (when it exists -- currently it
  does not, see `find_contextual_response_evidence`) is never presented as
  patient response.
- A terminated/withdrawn/suspended trial is never presented as evidence of
  lack of efficacy unless the evidence itself explicitly supports that
  (Issue #11's `sources/clinicaltrials.py` termination-reason
  classification is real-data-driven and rule-based; see
  `docs/TREATMENT_RESPONSE_CONTEXT.md` -- a bare terminated/withdrawn
  status with no reason text is labeled `NOT_REPORTED`, never assumed to
  mean a failed drug).

Every tool that returns claim-like results (relations, mechanism paths,
combination treatments) includes enough provenance (`source`,
`source_type`, `evidence_type`, `claim_state`, `verification_status`,
`retrieved_at`) for the caller to inspect where a fact came from, via
`get_evidence` or the `evidence`/`evidence_summary` fields already
embedded in the response.

## Graph/data version behavior

`get_graph_stats()`/`oncograph://stats`/`oncograph://version` report
`graph_version` -- the latest per-adapter `--release` label recorded on
any evidence row (set to the refresh run's UTC timestamp by
`refresh-data.yml`/`oncograph import-source --release`, the same value
`web/data/stats.json` uses). The MCP server always reflects **whatever
database `ONCOGRAPH_DATABASE_URL` currently points to** -- a local
`oncograph seed` demo DB, a real imported snapshot, or (if you point it at
one) the same SQLite file the FastAPI app uses. It does not read the
frozen `web/data/*.json` static export.

## Example research queries

```
search_entities("gefitinib")
search_entities("EGFR")
find_drugs_for_disease("ovarian cancer")
find_drug_mechanism("gefitinib")
find_combination_treatments(drug="pembrolizumab")
get_graph_stats()
```

## Limits and error handling

- `limit` is clamped to 200 (`oncograph.mcp._common.MAX_RESULT_LIMIT`) on
  every tool that accepts one; a non-positive `limit` is a `ToolError`.
- `max_hops` is clamped to 5 (`MAX_HOPS`) on every traversal-based tool; a
  non-positive `max_hops` is a `ToolError`.
- An unknown `entity_type` is a `ToolError` naming every valid value.
- An unknown `retrieval_strategy` is a `ToolError` naming every valid
  value -- never a silent fallback.
- An unresolvable `entity_id`/`relation_id` is a `ToolError`, not an empty
  success or a crash.
- Result ordering is deterministic (name/rank-based sort, never raw
  database/dict iteration order) so repeated identical calls return
  identical results.
- Missing optional metadata (no aliases, no trial status, no publication)
  is represented as `null`/an empty list, never fabricated.

## Testing

```bash
pytest tests/test_mcp_common.py tests/test_mcp_tools.py tests/test_mcp_server.py
pytest        # full suite
ruff check .
```

All MCP tests use local, in-memory (or temp-file) SQLite fixtures -- no
live external API calls.
