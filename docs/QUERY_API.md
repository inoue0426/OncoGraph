# Graph query & reasoning API (Issue #7)

`oncograph.query` is the evidence-aware traversal layer; `src/oncograph/main.py` exposes it over
HTTP. Everything returned is machine-readable JSON -- entities, relations, evidence, provenance,
confidence, context, contradictory evidence, and publication references -- never prose.

## `GET /query/traverse`

Generic N-hop traversal from any entity.

| Param | Meaning |
|---|---|
| `ref` (required) | Entity UUID, canonical ID (e.g. `gtopdb:4941`), or exact name. Identifier-first: tried in that order. |
| `entity_type` | Restrict resolution to one `EntityType` (disambiguates a name shared across types). |
| `max_hops` | 1-5, default 1. |
| `predicates` | Comma-separated predicate names to follow (e.g. `targets,associated_with`). Omit to follow all. |
| `sources` | Comma-separated source keys (e.g. `gtopdb,open_targets`). A relation is kept only if at least one of its `Evidence` rows matches. |
| `min_confidence` | 0.0-1.0. Evidence rows below this are dropped (not the whole relation, unless none remain). |
| `require_publication` | If true, only follow hops with at least one publication-cited `Evidence` row -- this is what makes "drug -> publication-supported disease path" possible. |

Response shape:

```json
{
  "root": {"id": "...", "type": "drug", "name": "...", "canonical_id": "...", "description": null},
  "entities": [ /* same shape as root, one per reached entity, root included */ ],
  "relations": [
    {
      "id": "...", "subject_id": "...", "predicate": "targets", "object_id": "...",
      "evidence": [
        {
          "id": "...", "source": "gtopdb", "source_id": "...", "source_url": "...",
          "source_type": "curated_database", "evidence_type": "target_interaction",
          "license": "...", "publication_id": null, "context": {"release": "..."},
          "confidence": null, "claim_state": "supports", "verification_status": "unverified",
          "retrieved_at": "2026-01-01T00:00:00+00:00"
        }
      ],
      "has_contradictory_evidence": false,
      "publication_ids": []
    }
  ],
  "paths": { "<entity_id>": ["<relation_id>", "..."] }
}
```

`has_contradictory_evidence` is true when a relation's (filtered) evidence set contains both a
`supports` and a `contradicts` row -- see `docs/EVIDENCE.md`'s `claim_state`. `paths` gives the
shortest relation-id path from the root to each reached entity (BFS, so shortest by hop count).

Traversal explores both outgoing and incoming relations at each hop: this repository's predicates
aren't always stored in the direction a query implies (e.g. "genes associated with this disease"
needs to walk `Gene -[associated_with]-> Disease` backwards from the disease), so treating it as
undirected for reachability -- while still reporting each relation's real stored direction --
avoids requiring the caller to know or guess which side is the subject.

404 if `ref` doesn't resolve to any entity.

## `GET /query/{helper}`

Representative oncology query helpers, all just `ref` + a sensible starting `entity_type` and hop
depth on top of `traverse` -- none hard-code predicate names, since different sources use
different predicates for similar claims (e.g. `associated_with` vs `clinically_associated_with`),
and filtering to a fixed list would silently hide real, differently-sourced evidence.

| `{helper}` | Starting entity type | Hops |
|---|---|---|
| `disease-to-genes-to-drugs` | `disease` | 2 |
| `drug-to-target-to-pathway-to-disease` | `drug` | 3 |
| `gene-to-pathway-to-disease` | `gene` | 2 |
| `biomarker-to-response-to-drug` | `biomarker` | 2 |
| `trial-to-disease-to-intervention` | `trial` | 2 |
| `drug-to-publication-supported-disease-path` | `drug` | 3, `require_publication=true` |

404 if `ref` doesn't resolve to an entity of the expected type.

## Comparing retrieval strategies

`Retriever` (a `Protocol`), `RetrievalQuery`, and `RetrievalResult` in `oncograph.query` exist so a
future benchmark harness (Issue #9) can compare an LLM-only baseline, flat/vector RAG, vanilla
graph retrieval, and evidence-aware OncoGraph retrieval through one interface. Only
`GraphRetriever` (wrapping `resolve_entity` + `traverse`) is implemented here -- the others are
explicitly out of scope for this issue.

```python
from oncograph.query import GraphRetriever, RetrievalQuery

result = GraphRetriever(session).retrieve(RetrievalQuery(root_ref="gefitinib", max_hops=2))
# result.root, result.entities, result.relations, result.paths
```
