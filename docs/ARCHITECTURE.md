# Architecture

OncoGraph is designed as an evidence warehouse, not a collection of copied datasets.

```text
permitted source input
       ↓
source adapter
       ↓
normalized EntityRecord / EdgeRecord
       ↓
validation
       ↓
identifier-first entity resolution
       ↓
Entity + EntityIdentifier
       ↓
Relation (deduplicated subject-predicate-object)
       ↓
Evidence (source-specific provenance)
       ↓
API / graph traversal / agents
```

## Scaling principles

- External identifiers are first-class records and globally unique by namespace/value.
- Relations are deduplicated by subject/predicate/object; independent sources attach separate Evidence records.
- Ambiguous identifier mappings fail closed and are recorded as ResolutionConflict rows.
- Every import creates a SourceSnapshot for reproducibility.
- Raw licensed data stays outside the public repository.
- Importers should be rerunnable: identifiers, relations, and source evidence are deduplicated.

## Intended large-scale direction

PostgreSQL is the primary production store. Keep the normalized relational core as the source of truth; graph projections/search indexes can be derived later for Neo4j, OpenSearch, vector retrieval, or analytical warehouses. This prevents the public API and provenance model from being tied to one graph vendor.
