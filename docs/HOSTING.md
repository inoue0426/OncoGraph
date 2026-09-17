# Hosting

The MVP uses GitHub for code and automation, and GitHub Pages for a read-only static search and
detail UI. `scripts/build_static_site.py` generates two browser indexes from a permitted SQLite
snapshot: an entity index (`id`, `type`, `name`, `canonical_id`) and a relation index (`subject_id`,
`predicate`, `object_id`, plus each edge's evidence: source, source URL, and context). If no
database is present, both are written empty. Kept intentionally minimal for the MVP; no full
descriptions or per-entity metadata are exported.

One workflow (`.github/workflows/pages.yml`), triggered by manual dispatch and a weekly schedule
only (no push trigger, so an ordinary code push does not refetch or reimport data), does the whole
pipeline:

1. Fetch the open HGNC, GtoPdb, and Gene Ontology sources with `scripts/fetch_open_gene_sources.py`.
2. Fetch drug-associated clinical trials (ClinicalTrials.gov API) and target-disease associations
   (Open Targets Platform API) with `scripts/fetch_open_drug_associations.py`, scoped to the
   approved drugs/targets the first step already fetched.
3. Import everything in dependency order with `oncograph import-source`: HGNC first so genes exist
   before GtoPdb resolves drug targets to them, then GtoPdb (adds drug entities and drug→target
   edges), then Gene Ontology, then ClinicalTrials.gov (drug→trial edges, keyed to GtoPdb drug IDs)
   and Open Targets (target→disease edges, keyed to HGNC gene IDs).
4. Build both static indexes from that database and deploy `web/` to Pages.

The raw files and the SQLite database exist only on the runner's filesystem for that job and are
never committed. The currently published Pages site is left untouched until the next scheduled or
manual run. Restricted data and credentials must never be committed or published.

The frontend (`web/app.js`) joins the two indexes client-side: selecting a drug shows its direct
targets and clinical trials, plus diseases associated with those targets (a two-hop, drug→target→
disease view, since no direct drug→disease indication source is wired in yet).

When the static MVP is no longer enough, move snapshots to object storage, normalized data to
PostgreSQL, optional traversals to a graph database, and expose them through a versioned API.
Evidence and provenance identifiers remain the publication boundary throughout that transition.
