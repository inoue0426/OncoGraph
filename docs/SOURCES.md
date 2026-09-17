# Source policy

OncoGraph keeps ingestion **code** separate from upstream **data**. The public repository must not contain restricted datasets, credentials, API keys, or source text whose license does not permit redistribution.

## Adapter contract

Each source adapter emits normalized `EntityRecord` and `EdgeRecord` candidates. Every edge should retain enough provenance to recover the upstream record: source key, source record identifier, URL when permitted, context, and retrieval metadata.

Importers should be deterministic and idempotent. Validation occurs before database writes. Source-specific raw fields belong in metadata rather than silently changing the shared ontology.

## Identifier namespaces

Prefer stable external identifiers over names. Initial namespaces include DrugBank, PubMed/PMID, ClinicalTrials.gov/NCT, HGNC, NCBI Gene, MeSH, DOID, and ChEBI. Name-only matching should be treated as unresolved rather than silently merged.

## Licensing

`SourceDescriptor.redistribution` is deliberately conservative. `restricted` means data must never be committed to this repository. `metadata_only` means an adapter should store identifiers/provenance rather than copied source content. `unknown` blocks assumptions: verify current upstream terms before enabling distribution or automated ingestion.

Potential sources documented in the catalog include PubMed, ClinicalTrials.gov, CTD, and DrugBank. The catalog is documentation, not authorization to fetch or redistribute a source.
