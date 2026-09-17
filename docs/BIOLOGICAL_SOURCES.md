# Biological knowledge sources (Issue #5 investigation)

This documents what was checked, what was integrated, and why, for the sources listed in Issue
#5 ("Biological Knowledge Expansion"). Not every candidate source needs a full adapter to satisfy
that issue -- several are intentionally left at "investigated, not integrated" below.

## Integrated (real adapter, real data verified this session)

| Source | Adapter | License | Notes |
|---|---|---|---|
| Reactome | `sources/reactome.py` | **CC0**, confirmed live via `reactome.org/license`: "All data in the Reactome database ... are licensed under ... CC0. User may copy, modify, and distribute these data, even for commercial purposes." | Gene (NCBI Gene ID) -> Pathway (`part_of_pathway`), from the official `NCBI2Reactome.txt`, filtered to Homo sapiens. |
| CIViC | `sources/civic.py` | **CC0**, confirmed live via `docs.civicdb.org`: "We provide CIViC data freely to all under the Creative Commons Public Domain Dedication, CC0 1.0 Universal License." | Clinical evidence for a small curated gene list (`scripts/fetch_civic_evidence.py`, open GraphQL API, no key). Drug (NCIt) -> Disease (DOID) when a therapy is named (`clinically_evidenced_for`); Gene (NCBI Gene) -> Disease (DOID) otherwise (`clinically_associated_with`). `evidence_direction` -> `claim_state`; `evidence_level`/`significance` kept in `context` (qualitative, not forced into `confidence`). |

## Integrated with an explicit licensing caveat

| Source | Adapter | Status |
|---|---|---|
| DGIdb | `sources/dgidb.py` | Open GraphQL API, no key required, MIT-licensed *software* -- but no explicit redistribution license was found for the *aggregated interaction data* itself (unlike Reactome/CIViC's explicit CC0 statements). `SourceDescriptor.redistribution = UNKNOWN`, same conservative treatment this repo already gives CTD. DGIdb aggregates ~30 upstream sources per interaction (including, for some rows, OncoKB and CIViC); those names are kept in `context.contributing_sources` for transparency only -- every DGIdb-derived edge's `source` is `"dgidb"`, never attributed to an individual upstream contributor. **Before this is used in the public pipeline, DGIdb's data license should be confirmed directly with the project.** |

## Scaffold only: adapter + local-file interface, no fetch script, no real data

| Source | Adapter | Why scaffold-only |
|---|---|---|
| OncoKB | `sources/oncokb.py` | Verified live: `/api/v1/genes` returns `401 Unauthorized` without a registered API token; terms require a data usage agreement for redistribution. The adapter reads a caller-supplied local export (from someone's own token-authenticated access) and never calls OncoKB itself. Not wired into any fetch script or pipeline. |
| Ligand-receptor / cell-cell communication (CellPhoneDB, CellChatDB) | `sources/ligand_receptor.py` | Both compile pairs from multiple upstream curated sources (UniProt, IUPHAR/GtoPdb, literature) with mixed terms; verifying every component's license was out of scope for this pass. The adapter takes a generic, vendor-agnostic local file (ligand/receptor identifiers + `communication_type: inferred \| experimental`) so a specific licensed source can be wired in later without changing the predicate/context shape. |

## Investigated, not integrated (documentation only)

Survey-level only in this pass -- not re-verified live the way Reactome/CIViC/OncoKB were, and no
adapter code was written. Good candidates for a future, focused pass:

- **STRING**: confirmed live (`string-db.org`) -- CC BY 4.0. Protein-protein / functional
  association scores, including a "coexpression" evidence channel; a natural fit for the
  `oncograph.coexpression` module once wired to a real adapter.
- **UniProt**: widely documented as CC BY 4.0. Would strengthen protein-level identifiers
  (already a normalized namespace, see `docs/EVIDENCE.md`) and functional annotation.
- **ChEMBL**: EBI-hosted (`ebi.ac.uk/chembl`, confirmed reachable), widely documented as CC BY-SA
  4.0. Already a normalized identifier namespace (`chembl`); DGIdb/CIViC/Open Targets edges already
  carry ChEMBL-style drug identifiers where their upstream data provides one.
- **IntAct / BioGRID**: molecular interaction databases (IMEx consortium members); BioGRID states
  an MIT-style open data license. Not independently re-confirmed live this session.
- **OmniPath**: aggregates many of the above (like DGIdb does for drug-gene data) with its own
  per-resource licensing model; would need the same aggregation-transparency treatment as DGIdb.
- **WikiPathways**: widely documented as CC0, a natural second pathway source alongside Reactome.
- **PharmGKB**: has historically required a separate license agreement for redistribution beyond
  personal/academic use; treat like OncoKB (scaffold-only) until confirmed otherwise.

## Cross-source identifier resolution: what actually merges today

Verified in a real smoke import (HGNC + Reactome + CIViC + DGIdb together):

- **DGIdb genes resolve against existing HGNC-sourced Gene entities.** DGIdb's gene `conceptId`
  (e.g. `hgnc:3236`) is reformatted to match our canonical `HGNC:3236` form, so DGIdb interactions
  correctly attach to the same Gene entities HGNC/GtoPdb already created -- 0 unresolved gene
  endpoints in the smoke test.
- **Reactome and CIViC's gene-side edges do not** -- both key genes by NCBI Gene ID
  (`ncbigene:1956`), which HGNC only records as a *secondary* identifier (not the canonical one
  `import_entities` matches on; see the known limitation noted in Issue #4's report). Until HGNC's
  own canonical form includes NCBI Gene ID, or a crosswalk step is added, these edges log as
  `unresolved` (`EntityResolutionIssue`, per Issue #4) rather than silently guessing.
- **Drug entities merge correctly when two sources use the same identifier system**: CIViC and
  DGIdb both sometimes resolve a drug to the same NCIt ID, and in the smoke test those correctly
  became a single shared Drug entity rather than duplicates.
- This is a real, load-bearing architectural gap (identifier-first resolution only ever matches on
  one canonical identifier per entity), not specific to this issue's adapters -- fixing it broadly
  (e.g. a proper identifier crosswalk/xref table) is a larger design change intentionally left out
  of this pass.

## GO "low-information term" filtering support

`GeneOntologyAdapter` now computes, per term, `is_root` (no `is_a` parent -- true only for the
three GO root terms) and `child_count` (direct `is_a` children -- large for near-root, generic
terms). This is metadata support for filtering, not filtering itself; Issue #8's UI is expected to
use it to avoid showing e.g. "biological_process" as if it were a specific, informative annotation.

## New entity types

`EntityType` gained `biomarker`, `mutation`, `fusion`, `copy_number_alteration`, and
`expression_signature` for the genomic-alteration concepts this issue asks for. No adapter
currently emits them (that depends on which of the sources above eventually get wired in with real
mutation/CNA/fusion data); they exist so a future adapter doesn't need a schema change to use them.
