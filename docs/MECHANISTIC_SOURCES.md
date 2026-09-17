# Mechanistic & functional evidence sources (Issue #10)

Extends `docs/BIOLOGICAL_SOURCES.md` with the sources Issue #10 asked to
investigate: causal signaling, drug mechanism-of-action, functional
dependency, quantitative binding, and normal-tissue expression. Investigated
live during this pass (real HTTP checks, not memory) on 2026-09-17.

## Integrated: real adapter + fetch script + real data ingested

| Source | Adapter | License (verified live) | What's ingested |
|---|---|---|---|
| DrugMechDB | `sources/drugmechdb.py` | **CC0-1.0** (GitHub repo license metadata) | Curated drug -> mechanism -> disease paths (`indication_paths.json`, 4,846 paths). Drug/disease endpoints + first real molecular target reified as entities; the full intermediate chain (BiologicalProcess/GO/HP/UniProt/... nodes) preserved in the endpoint edge's `context`, not reified as separate entities in this pass (see the adapter's module docstring for why). |
| ChEMBL | `sources/chembl.py` | **CC BY-SA 3.0** (confirmed at ebi.ac.uk/chembl) | Drug mechanism-of-action via `/mechanism` + `/target` REST endpoints (`scripts/fetch_chembl_mechanisms.py`). `action_type` (INHIBITOR, AGONIST, ...) mapped to a directed predicate (inhibits, agonizes, ...) rather than a free-text label; `mechanism_of_action` text, ChEMBL's own mechanism/target IDs, and reference citations kept in context. |
| TRRUST | `sources/trrust.py` | **CC BY-SA 4.0** (confirmed at grnpedia.org) | Curated TF -> target gene regulation (`trrust_rawdata.human.tsv`). Gene *symbols* resolved to HGNC IDs via the official HGNC file before import (TRRUST itself carries no identifier) -- an unresolvable symbol is skipped, never matched by name alone. |
| GTEx | `sources/gtex.py` | Public portal describes this data as **open access** | Per-tissue **median** expression (TPM) only, via `/api/v2/expression/medianGeneExpression` -- never GTEx's separately-governed individual-level genotype/sample data. Scoped to a curated ~50-gene oncology target list (`scripts/fetch_gtex_expression.py`), not all ~55k GENCODE genes. |

## Scaffold only: adapter + local-file interface, no fetch script, no real data

| Source | Adapter | Why scaffold-only |
|---|---|---|
| SIGNOR | `sources/signor.py` | License confirmed open (CC BY-SA 4.0 / CC BY 4.0, stated inconsistently across the site's own footer) -- but its documented bulk-query API (`signor.uniroma2.it/API/`) returned **403 Forbidden** to a plain request; practical bulk access needs a browser session/form submission. Access-complexity gap, not a licensing one. |
| DrugCentral | `sources/drugcentral.py` | Reachable, states a license on its About page, but is primarily distributed as a full PostgreSQL dump rather than a small per-record API/file. |
| BindingDB | `sources/bindingdb.py` | Its documented single-file download endpoints returned errors (500/404) to a plain request; bulk export needs session/form-based query building. |
| DepMap | `sources/depmap.py` | CRISPR dependency data ships as large genes-by-cell-lines matrices (Figshare, hundreds of MB) -- exactly what this repository's policy says not to fetch/commit wholesale. Adapter expects a caller-supplied *compact* per-pair export instead. |

## Investigated, not integrated (documentation only)

- **JASPAR**: motif/binding-site evidence is a materially different evidence kind from TRRUST's curated regulation calls (Issue #10: "do not treat motif presence alone as equivalent to experimentally demonstrated regulation"). No adapter written this pass -- modeling it meaningfully needs its own predicate/context shape, deferred rather than forced in alongside TRRUST.
- **DisGeNET, ENCODE/Roadmap Epigenomics, PathwayCommons/OmniPath**: explicitly lower-priority per Issue #10 ("evaluate only when they add nonredundant evidence and licensing permits"); not investigated live this pass.

## New entity types

- `EntityType.TISSUE` ("tissue"): GTEx normal-tissue entities, keyed by UBERON ID.
- `EntityType.COMBINATION_TREATMENT` ("combination_treatment"): added in this pass for Issue #11's combination-therapy modeling (see `docs/TREATMENT_RESPONSE_CONTEXT.md`), not used by any Issue #10 adapter.

`EntityType.PROTEIN` already existed (Issue #2) and is reused as-is for
DrugMechDB/ChEMBL/SIGNOR/DrugCentral/BindingDB's UniProt-keyed targets.

## Design choice: no new `Mechanism` entity type

Issue #10 sketches an optional `Drug -> HAS_MOA -> Mechanism -> ACTS_ON ->
Target` shape with `Mechanism` as its own entity (to let an ADC's antigen
target and payload mechanism stay distinct later). This pass instead
represents MoA as a **direct, typed edge** (`Drug -[inhibits/agonizes/...]->
Protein`), with `action_type`/`mechanism_of_action`/target-class metadata
kept in the edge's evidence context. Reasoning: no ADC entities or payload
data exist anywhere in the currently deployed graph yet, so introducing a
new intermediate entity type now would add schema complexity with nothing
real to justify it. This is a deliberate, minimal-footprint choice (per this
project's standing instruction to avoid large-scale schema rewrites), not an
oversight -- promoting mechanism edges to first-class `Mechanism` entities,
with an explicit antigen-vs-payload split, is real future work once ADC
data is actually integrated.

## Cross-source identifier resolution: what's new here

Verified in the same real smoke import used for Issue #5's crosswalk notes:

- **TRRUST's gene symbols now resolve against existing HGNC-sourced Gene
  entities** -- the adapter itself does the symbol -> HGNC-ID lookup before
  emitting anything (see `sources/trrust.py::_build_symbol_index`), so
  TRRUST edges attach to the same canonical Gene entities HGNC/GtoPdb/DGIdb
  already created, not new symbol-keyed duplicates.
- **DrugMechDB, ChEMBL, SIGNOR, DrugCentral, and BindingDB's drug/protein
  entities do not** resolve against existing GtoPdb-keyed Drug entities or
  HGNC-keyed Gene entities -- they key drugs by MESH/ChEMBL/DrugCentral/
  PubChem IDs and targets by UniProt accession, none of which is this
  repository's canonical identifier for those entities today. This is the
  same architectural gap already documented in `docs/BIOLOGICAL_SOURCES.md`
  (identifier-first resolution matches on exactly one canonical identifier
  per entity) -- not new to this pass, and still intentionally out of scope
  to fix broadly here.
- **GTEx's genes are Ensembl-keyed** and likewise do not resolve against
  HGNC-keyed Gene entities for the same reason.

## Real data ingested this pass (smoke-tested against the adapters above)

- DrugMechDB: all 4,846 real paths from the official file -- 2,772 entities, 5,810 edges.
- TRRUST: all rows from the official human TSV -- 2,851 entities (HGNC-resolved), 9,342 edges.
- GTEx: 50 curated oncology genes x their real tissue median expression -- 103 entities, 2,650 edges.
- ChEMBL: all 908 real drugs currently in the deployed graph (`scripts/fetch_chembl_mechanisms.py --from-search-index`) -- 576/908 had a resolvable mechanism record (13 no ChEMBL match, 313 matched but ChEMBL has no curated mechanism for them); 899 entities, 759 edges.

All four real adapters above (DrugMechDB, ChEMBL, TRRUST, GTEx) are wired
into `refresh-data.yml` as of this pass, so the next scheduled/manual
refresh ingests real data from all four into the deployed public graph.
The four scaffold-only adapters (SIGNOR, DrugCentral, DepMap, BindingDB)
are not wired into any pipeline, per the reasons above.
