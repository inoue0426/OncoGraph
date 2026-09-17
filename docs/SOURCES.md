# Source policy

OncoGraph keeps ingestion **code** separate from upstream **data**. The public repository must not contain restricted datasets, credentials, API keys, or source text whose license does not permit redistribution.

## Adapter contract

Each source adapter emits normalized `EntityRecord` and `EdgeRecord` candidates. Every edge should retain enough provenance to recover the upstream record: source key, source record identifier, URL when permitted, context, and retrieval metadata. See `docs/EVIDENCE.md` for the full Evidence field contract and how to populate it from a new adapter.

Importers should be deterministic and idempotent. Validation occurs before database writes. Source-specific raw fields belong in metadata rather than silently changing the shared ontology.

## Identifier namespaces

Prefer stable external identifiers over names. Initial namespaces include DrugBank, PubMed/PMID, DOI, PMCID, ClinicalTrials.gov/NCT, HGNC, NCBI Gene, MeSH, DOID, ChEBI, MONDO, and EFO. Name-only matching should be treated as unresolved rather than silently merged. A Publication's canonical identifier prefers PMID, then DOI, then PMCID -- see `docs/PUBLICATIONS.md`.

## Licensing

`SourceDescriptor.redistribution` is deliberately conservative. `restricted` means data must never be committed to this repository. `metadata_only` means an adapter should store identifiers/provenance rather than copied source content. `unknown` blocks assumptions: verify current upstream terms before enabling distribution or automated ingestion.

Potential sources documented in the catalog include PubMed, ClinicalTrials.gov, CTD, and DrugBank. The catalog is documentation, not authorization to fetch or redistribute a source.

## Attribution

- HGNC complete gene set: CC0.
- Gene Ontology: CC BY 4.0.
- GtoPdb (IUPHAR/BPS Guide to PHARMACOLOGY) approved drugs and primary targets: database licensed
  under the Open Database License (ODbL, https://opendatacommons.org/licenses/odbl/); content
  licensed under CC BY-SA 4.0 (http://creativecommons.org/licenses/by-sa/4.0/). Only the official
  "approved drugs with primary targets" file and the official target-to-HGNC mapping file are used;
  the full ligand/interaction dump and the Postgres export are not fetched.
- ClinicalTrials.gov: public registry metadata (NCT ID, brief title, status, phase, conditions),
  fetched per approved drug via the API v2 and name-matched against the drug's interventions. Only
  registry metadata is stored, not full protocol text; see the `metadata_only` classification below.
- Open Targets Platform: target-disease association scores, fetched per HGNC target (by Ensembl
  gene ID) via the GraphQL API, released under CC0. Scores are a computed evidence aggregate, not a
  clinical indication; only associations at or above the configured score threshold are kept, and
  the threshold/top-k and query scope are recorded alongside each import for reproducibility.
- Europe PMC: bibliographic metadata only (title, journal, year, authors, publication type, DOI,
  PMCID) for a small, curated set of cited PMIDs, fetched via the Europe PMC REST API. No abstract
  or full text is ever fetched or stored. See `docs/PUBLICATIONS.md` for the curated citations
  file this depends on and why literature-evidence linking is human-curated, not mined.
- Reactome: gene-pathway membership from the official NCBI Gene-to-pathway mapping file, CC0.
- CIViC: clinical evidence for a small curated gene list via the open GraphQL API, CC0.
- DGIdb: drug-gene interactions via the open GraphQL API; redistribution is treated as
  conservative/unknown pending explicit confirmation (see `docs/BIOLOGICAL_SOURCES.md`).
- OncoKB: API-key-gated and terms-restricted; scaffold adapter only, no data fetched or committed.

See `docs/BIOLOGICAL_SOURCES.md` for the full Issue #5 source investigation (Reactome, CIViC,
DGIdb, OncoKB, STRING, IntAct, BioGRID, OmniPath, CellPhoneDB/CellChatDB, UniProt, ChEMBL,
WikiPathways, PharmGKB) and what cross-source identifier resolution actually works today.
