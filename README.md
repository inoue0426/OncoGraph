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

See `docs/SOURCES.md` for the provenance and source policy.

## Public explorer and hosting

The MVP in `web/` is deployed with GitHub Pages and searches a generated public entity index.
A single scheduled/manual/push workflow fetches open data, imports it into a throwaway SQLite
database, and rebuilds the index; raw files and the database never reach git. See `docs/HOSTING.md`.

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
