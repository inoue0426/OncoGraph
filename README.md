# OncoGraph

Evidence-first, machine-readable knowledge graph for oncology research.

OncoGraph is intended to become a large, reusable oncology evidence database for both programmatic research workflows and interactive exploration. Its core rule is **provenance first**: independent sources can support the same edge without losing where each claim came from.

> Research software. Not intended for diagnosis, treatment selection, or clinical decision-making.

## Current architecture

```text
source adapters → validation → identifier resolution → entities/relations → evidence → API/agents
```

The normalized core now includes `Entity`, first-class `EntityIdentifier`, deduplicated `Relation`, `Evidence`, `SourceSnapshot`, and `ResolutionConflict`. This makes multi-source growth possible without merging records only because their names look similar.

Potential integration points are documented for PubMed, ClinicalTrials.gov, CTD, and DrugBank. The public repository contains adapter infrastructure only—not restricted upstream data, credentials, or copied source text.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
oncograph seed
uvicorn oncograph.main:app --reload
```

Open `http://127.0.0.1:8000/docs`.

## Design rules

- Prefer stable identifiers (HGNC, NCBI Gene, ChEBI, DrugBank IDs, PMID, NCT, MeSH/DOID) over names.
- One subject-predicate-object relation can carry evidence from many independent sources.
- Ambiguous mappings fail closed and are logged rather than silently merged.
- Every adapter import records a source snapshot/version/checksum when available.
- Restricted raw data stays outside Git.

See `docs/ARCHITECTURE.md` and `docs/SOURCES.md`.

## Near-term roadmap

1. Source-specific permitted-input adapters and snapshot tooling.
2. Ontology/predicate registry and schema migrations.
3. Bulk PostgreSQL import paths for millions of edges.
4. Search/index layer and graph exports.
5. Evidence conflict scoring and missing-evidence detection.
6. Agent-facing query endpoints and interactive UI.

## Development

```bash
pytest
ruff check .
```

## License

MIT. Upstream datasets retain their own licenses and terms.
