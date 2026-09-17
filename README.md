# OncoGraph

Evidence-first, machine-readable knowledge graph for oncology research.

OncoGraph connects biomedical entities to the evidence supporting each relationship. The core design principle is **provenance first**: a relation is not just an edge; it carries source, context, extraction method, confidence, and verification state.

> Research software. OncoGraph is not intended for diagnosis, treatment selection, or other clinical decision-making.

## v0.2 scope

Core entities remain `Drug`, `Target`, `Disease`, `Paper`, and `Trial`, with generic directed relations and edge-level evidence. v0.2 adds a source-adapter layer so public ingestion code can be developed independently from upstream data and licensing constraints.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
oncograph seed
uvicorn oncograph.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API documentation.

## Source adapters

The adapter contract lives in `oncograph.sources`. Adapters emit normalized entity and edge candidates without directly mutating the database. `oncograph.importing` validates records before persistence, and `oncograph.normalization` canonicalizes external identifier namespaces.

The source catalog documents intended integration points for PubMed, ClinicalTrials.gov, CTD, and DrugBank. **No restricted upstream data, credentials, or copied source text is included in this repository.** DrugBank is explicitly marked restricted; CTD is conservative/unknown until its current terms are verified for the intended use.

See `docs/SOURCES.md` for the provenance and source policy, `docs/EVIDENCE.md` for the Evidence
field contract new adapters should populate, `docs/PUBLICATIONS.md` for how Publications and
literature evidence fit in, `docs/BIOLOGICAL_SOURCES.md` for the pathway/clinical-evidence source
investigation (Reactome, CIViC, DGIdb, OncoKB, and others), `docs/DRUG_RESPONSE.md` for the
drug-response/experimental-model schema, and `docs/MECHANISTIC_SOURCES.md` for the mechanism-of-action/
functional-evidence source investigation (DrugMechDB, ChEMBL, TRRUST, GTEx, SIGNOR, DrugCentral, DepMap,
BindingDB). DrugMechDB, ChEMBL, TRRUST, and GTEx are wired into the scheduled refresh; the drug-response
schema and the remaining biological/mechanistic sources documented above are not yet part of it. See
`docs/QUERY_API.md` for the evidence-aware graph traversal API
(`/query/traverse` and representative query helpers), `docs/BENCHMARKING.md` for the
benchmark-item schema and metrics infrastructure, `docs/BENCHMARK_RUN_v2.md` for the first real
(non-fabricated) evaluation of `GraphRetriever` against an evidence-blind ablation on a frozen
snapshot, and `docs/STATS.md` for the homepage coverage-statistics artifact (`web/data/stats.json`)
and its path-count semantics.

## Public explorer and hosting

**Live site:** https://inoue0426.github.io/OncoGraph/

The MVP in `web/` is deployed with GitHub Pages and searches a generated public entity index.
Selecting a drug shows its known targets, clinical trials, and diseases associated with those
targets. Data refresh and deployment are two separate workflows: a scheduled/manual
`refresh-data.yml` fetches open data (HGNC, GtoPdb approved drugs and primary targets, Gene
Ontology, ClinicalTrials.gov trial metadata, Open Targets target-disease associations, DrugMechDB
mechanism paths, ChEMBL mechanism of action, TRRUST TF-target regulation, GTEx tissue expression),
imports it into a throwaway SQLite database, and publishes the rebuilt index as a build artifact (raw files
and the database never reach git); a lightweight `pages.yml`, triggered on every push to `main`,
just grabs the latest such artifact and deploys `web/`, without refetching anything. See
`docs/HOSTING.md`.

Includes approved-drug/primary-target data from the IUPHAR/BPS Guide to PHARMACOLOGY (GtoPdb):
database licensed under ODbL, content licensed under CC BY-SA 4.0; trial registry metadata from
ClinicalTrials.gov; target-disease association scores from the Open Targets Platform (CC0); curated
drug-mechanism paths from DrugMechDB (CC0); mechanism-of-action data from ChEMBL (CC BY-SA 3.0);
transcription-factor-target regulation from TRRUST (CC BY-SA 4.0); and normal-tissue gene-expression
summaries from the GTEx Portal (open access, aggregate median expression only). See `docs/SOURCES.md`
and `docs/MECHANISTIC_SOURCES.md`.

## Data model

```text
Entity ──< Relation >── Entity
              │
              └──< Evidence
```

Every imported edge should preserve source identity, upstream record ID, URL when permitted, context, extraction method, and retrieval time. Prefer stable external identifiers to name matching.

## Roadmap

1. Implement source-specific adapters against user-provided/permitted inputs.
2. Add persistent external-identifier and source-snapshot tables.
3. Add deterministic entity resolution and conflict tracking.
4. Add evidence extraction with human-verifiable provenance.
5. Add interactive graph UI and agent-facing query API.
6. Add reproducible snapshots and source-specific licensing metadata.

## Development

```bash
pytest
ruff check .
```

## License

MIT. Individual upstream datasets and sources retain their own licenses and terms. Ingestion code must preserve source attribution and licensing metadata.
