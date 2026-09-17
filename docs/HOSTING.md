# Hosting architecture

OncoGraph's first hosted phase is deliberately GitHub-first. GitHub stores the public code,
runs validation and refresh jobs, and serves a read-only static explorer through GitHub Pages.
This keeps the initial operating surface small without weakening the graph's evidence-first and
provenance-aware design.

## Current GitHub-hosted phase

The `web/` directory is a dependency-free static application. It downloads
`web/data/entities.json`, then searches and filters the index entirely in the browser. The index
contains only public entity fields plus aggregate relationship/evidence counts. It does not copy
evidence text or upstream records into the browser.

`scripts/build_public_index.py` creates that file from a **curated public SQLite snapshot**. The
input must already have passed the project's source, redistribution, and disclosure review. Do not
point the builder at a working database that contains licensed, restricted, private, or
unreviewed material. The generated JSON records its generation time, a safe source label, and the
snapshot SHA-256 so a deployed index can be tied back to an exact reviewed input.

If `data/public/oncograph.db` is absent, the builder emits a valid empty index. This is the safe
default in a clean public checkout and lets the Pages workflow deploy the application shell
without inventing data or publishing a developer database. A reviewed deployment pipeline can
materialize the ignored snapshot at that path before running the builder.

Build the site locally with:

```bash
uv run python scripts/build_public_index.py \
  --database /path/to/reviewed-public-snapshot.db \
  --output web/data/entities.json
python -m http.server --directory web 8000
```

The Pages workflow runs on pushes to `main` and by manual dispatch. It rebuilds the index and
uploads only `web/` as the Pages artifact. GitHub repository settings must use **GitHub Actions**
as the Pages source.

## Open-data refreshes

The scheduled/manual refresh workflow runs the existing open-source fetcher for HGNC (CC0) and
Gene Ontology (CC BY 4.0). Downloaded files stay under ignored `data/raw/`; the workflow publishes
them only as a short-lived GitHub Actions artifact. A separate, longer-lived manifest records
source URLs, licenses, retrieval time, byte sizes, and SHA-256 checksums.

The refresh does not commit upstream datasets, mutate `main`, or automatically expose fetched
records on Pages. Promotion into a public graph snapshot remains an explicit validation and
review step. Restricted, unknown-policy, or credentialed sources must not be added to this
workflow.

## Scale-out path

The static contract allows the browser UI to survive later infrastructure changes:

1. Move immutable raw and normalized snapshots to versioned external object storage. Store
   checksums, source licenses, retrieval timestamps, and build manifests beside every object.
2. Move normalized entities, identifiers, evidence metadata, and audit state to PostgreSQL. Use
   migrations and immutable source-snapshot identifiers so every row remains traceable.
3. Add a graph database only when traversal volume or latency justifies it. Treat it as a derived
   projection, not the provenance system of record; retain stable IDs back to PostgreSQL and the
   source snapshot.
4. Put a versioned, read-only API in front of the stores. Apply allowlists for public fields,
   pagination and rate limits, and expose evidence/provenance links rather than detached claims.
5. Configure the static explorer to query that API while retaining a small generated index as a
   resilient discovery layer. Deploy API and data services separately from GitHub Pages.

At every phase, public hosting is a publication boundary. Source licensing, evidence verification,
and disclosure review happen before data crosses that boundary—not in the frontend.
