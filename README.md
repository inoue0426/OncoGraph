# OncoGraph

Evidence-first, machine-readable knowledge graph for oncology research.

OncoGraph connects biomedical entities to the evidence supporting each relationship. The core design principle is **provenance first**: a relation is not just an edge; it carries source, context, extraction method, confidence, and verification state.

> Research software. OncoGraph is not intended for diagnosis, treatment selection, or other clinical decision-making.

## v0.1 scope

Entities: `Drug`, `Target`, `Disease`, `Paper`, `Trial`.

Relations are generic directed edges such as `targets`, `studied_in`, `supports`, and `associated_with`. Every edge can have one or more evidence records.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
oncograph seed
uvicorn oncograph.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API documentation.

Useful endpoints:

- `GET /health`
- `GET /entities`
- `GET /entities/{id}`
- `GET /graph/{id}?depth=2`
- `GET /evidence?relation_id=...`

SQLite is the zero-config default. Set `ONCOGRAPH_DATABASE_URL` to a PostgreSQL SQLAlchemy URL for a server deployment.

## Data model

```text
Entity ──< Relation >── Entity
              │
              └──< Evidence
```

`Evidence` records source identifiers/URLs, a short evidence summary, context, extraction method, confidence, verification status, and retrieval time. Source text should not be copied into the repository unless its license permits redistribution.

## Roadmap

1. Stable ontology and identifier normalization.
2. PubMed and ClinicalTrials.gov ingestion adapters.
3. Evidence extraction with human-verifiable provenance.
4. Conflict and missing-evidence detection.
5. Interactive graph UI and agent-facing query API.
6. Reproducible snapshots and source-specific licensing metadata.

## Development

```bash
pytest
ruff check .
```

## License

MIT. Individual upstream datasets and sources retain their own licenses and terms; ingestion code must preserve source attribution and licensing metadata.
