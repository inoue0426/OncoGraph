# Hosting

The MVP uses GitHub for code and automation, and GitHub Pages for a read-only static search UI.
`scripts/build_static_site.py` generates the browser index from a permitted SQLite snapshot. If no
database is present, it safely writes an empty index. The index carries only `id`, `type`, `name`,
and `canonical_id` per entity, kept intentionally minimal for the MVP.

One workflow (`.github/workflows/pages.yml`), triggered on push to `main`, manual dispatch, and a
weekly schedule, does the whole pipeline: fetch the open HGNC and Gene Ontology sources with
`scripts/fetch_open_gene_sources.py`, import them into a SQLite database with
`oncograph import-source`, build the search index from that database, then deploy `web/` to Pages.
The raw files and the SQLite database exist only on the runner's filesystem for that job and are
never committed. Restricted data and credentials must never be committed or published.

When the static MVP is no longer enough, move snapshots to object storage, normalized data to
PostgreSQL, optional traversals to a graph database, and expose them through a versioned API.
Evidence and provenance identifiers remain the publication boundary throughout that transition.
