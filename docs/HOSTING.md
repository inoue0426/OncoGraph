# Hosting

The MVP uses GitHub for code and automation, and GitHub Pages for a read-only static search UI.
`scripts/build_static_site.py` generates the browser index from a permitted SQLite snapshot. If no
database is present, it safely writes an empty index.

The weekly/manual refresh workflow downloads the existing open HGNC and Gene Ontology sources.
Raw files stay under ignored `data/raw/`; only the checksum/license manifest is retained as a
workflow artifact. Restricted data and credentials must never be committed or published.

When the static MVP is no longer enough, move snapshots to object storage, normalized data to
PostgreSQL, optional traversals to a graph database, and expose them through a versioned API.
Evidence and provenance identifiers remain the publication boundary throughout that transition.
