# Hosting

The MVP uses GitHub for code and automation, and GitHub Pages for a read-only static search and
detail UI. `scripts/build_static_site.py` generates two browser indexes from a permitted SQLite
snapshot: an entity index (`id`, `type`, `name`, `canonical_id`) and a relation index (`subject_id`,
`predicate`, `object_id`, plus each edge's evidence: source, source URL, and context). If no
database is present, both are written empty. Kept intentionally minimal for the MVP; no full
descriptions or per-entity metadata are exported.

Data refresh and Pages deployment are two separate workflows, so an ordinary code push never
refetches or reimports data, and deploying a UI-only change stays fast.

## `refresh-data.yml` — heavy data pipeline

Triggered only by manual dispatch or a weekly schedule (never by push). It:

1. Fetches the open HGNC, GtoPdb, and Gene Ontology sources with `scripts/fetch_open_gene_sources.py`.
2. Fetches drug-associated clinical trials (ClinicalTrials.gov API) and target-disease associations
   (Open Targets Platform API) with `scripts/fetch_open_drug_associations.py`, scoped to the
   approved drugs/targets the first step already fetched.
3. Imports everything in dependency order with `oncograph import-source`: HGNC first so genes exist
   before GtoPdb resolves drug targets to them, then GtoPdb (adds drug entities and drug→target
   edges), then Gene Ontology, then ClinicalTrials.gov (drug→trial edges, keyed to GtoPdb drug IDs)
   and Open Targets (target→disease edges, keyed to HGNC gene IDs).
4. Builds both static indexes (`scripts/build_static_site.py`) and, after checking neither is empty,
   uploads `search-index.json`, `relations.json`, and the fetch manifests (source URL, license,
   release, retrieval time, SHA-256 per file) as a single `search-index` build artifact, retained
   for 30 days.

The raw files and the SQLite database exist only on the runner's filesystem for that job and are
never committed, and nothing here touches `web/` in git. Restricted data and credentials must never
be committed or published.

## `pages.yml` — lightweight deploy

Triggered by every push to `main` and by manual dispatch. It does **not** fetch, import, or parse
any upstream source. It finds the most recent successful `refresh-data.yml` run, downloads that
run's `search-index` artifact, verifies `search-index.json` and `relations.json` are present and
non-empty, copies them into `web/data/`, then deploys `web/` to Pages as-is. If no successful
`refresh-data.yml` run exists yet, the job fails loudly instead of deploying an empty index — run
"Refresh data" once (manual dispatch) before the first Pages deploy on a new repo/fork.

Because it reuses the last known-good data, a pure UI/code change (editing `web/app.js`, adapters,
etc.) redeploys in about a minute instead of waiting on a full refetch. To pick up new upstream
data, run the "Refresh data" workflow manually (or wait for its Monday schedule) and then either
push to `main` or dispatch "Pages" again.

The currently published Pages site is left untouched until a `pages.yml` run completes successfully.

The frontend (`web/app.js`) joins the two indexes client-side: selecting a drug shows its direct
targets and clinical trials, plus diseases associated with those targets (a two-hop, drug→target→
disease view, since no direct drug→disease indication source is wired in yet).

When the static MVP is no longer enough, move snapshots to object storage, normalized data to
PostgreSQL, optional traversals to a graph database, and expose them through a versioned API.
Evidence and provenance identifiers remain the publication boundary throughout that transition.
