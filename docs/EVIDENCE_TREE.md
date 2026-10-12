# Evidence Tree v1 (research use)

The [GitHub Pages demo](https://inoue0426.github.io/OncoGraph/) computes the tree in the browser from the published `data/search-index.json` and `data/relations.json` snapshot. Pages hosts static files and **cannot execute the Python API or host a remote MCP server**. The same response shape is implemented in Python for a locally imported SQLite database. The local database and the published snapshot can have different data and refresh times.

## Exact input contract

| Field | Meaning |
| --- | --- |
| `gene` | Exact CIViC gene name, case insensitive, such as `EGFR`. |
| `variant` | Exact member name, such as `T790M` or `EGFR T790M`, when membership was exported. Older snapshots permit an exact molecular profile name match, marked `profile_only`. |
| `disease` | Exact disease name or DOID identifier, case insensitive. |
| `jurisdiction` | `US` only; this is a requested scope, **not** a claim of FDA approval. |
| `limit` | 1–200, default 50; `truncated` and `total_evidence_items` report omitted items. |

Browser: enter these three fields in **US evidence tree** and download the returned JSON. The public JSON data files are available at `https://inoue0426.github.io/OncoGraph/data/search-index.json` and `https://inoue0426.github.io/OncoGraph/data/relations.json`; consumers may run an equivalent local projection. This is not an HTTP query endpoint on Pages.

Python (against an imported local database):

```python
from sqlmodel import Session
from oncograph.db import engine
from oncograph.evidence_tree import get_evidence_tree

with Session(engine) as session:
    tree = get_evidence_tree(session, gene="EGFR", variant="T790M", disease="<exact disease name or DOID>")
```

Local HTTP API: run `uvicorn oncograph.main:app` with `ONCOGRAPH_DATABASE_URL` set to your imported database, then `GET /evidence-tree?gene=EGFR&variant=T790M&disease=<URL-encoded exact disease name or DOID>`. Local stdio MCP: `get_evidence_tree(gene, variant, disease, jurisdiction="US", limit=50)` using the same database. For either interface, an invalid jurisdiction or input is an error. A valid query without matching records returns `status: "not_found_in_snapshot"` and `evidence: []`.

## Response contract

`schema_version: "1.0"`; `query` echoes the inputs; `status` is `matched` or `not_found_in_snapshot`; `total_evidence_items` counts deduplicated CIViC evidence IDs within matching molecular profiles and disease; `truncated` is true when `limit` omits records. `evidence` contains one record per CIViC evidence ID, molecular profile ID and disease ID, with `evidence_id`, `profile`, `disease`, `evidence_type`, `level`, `rating`, `significance`, `claim_state`, `source`, `source_id`, `source_url`, `citation_url`, `retrieved_at`, and `therapies` (linked drug entities, if recorded). The `profile` includes `id`, `name`, `variants`, `match_type` (`variant_member` or `profile_only`), and `complex_profile`. `us_regulatory_label` and `civic_assertions` have `status: "not_integrated"` and `source: null`. `limitations` explains interpretation.

Only CIViC records marked `ACCEPTED` are returned. `claim_state: "contradicts"` is preserved; evidence levels and ratings are the original CIViC fields and are **not** FDA or AMP/ASCO/CAP classification. For multi-variant profiles, membership does not assign a clinical finding to one variant alone. Recorded therapies are associated with the CIViC evidence ID; their interaction type is not available, so neither combination nor monotherapy is inferred. Missing results mean the bounded snapshot has no matching record. Disease stage, line of therapy, histology refinements, FDA labels, CIViC Assertions, and an `as_of` historical query are not supported. Do not use this response for treatment decisions.
