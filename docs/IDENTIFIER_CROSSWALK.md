# Identifier crosswalk (incremental, backward-compatible)

The importer now records all `EntityRecord.identifiers` in
`EntityIdentifier`, while preserving the original `Entity.canonical_id`.
Endpoint resolution checks an exact canonical identifier first, then accepts
an alternate identifier **only if it resolves to one unique entity**.
Unresolved/ambiguous aliases are never name-matched.

## Species and type safeguards

The `taxon_id` comes from explicit record metadata when available. If absent,
HGNC primary IDs imply human (NCBI Taxonomy 9606) and MGI imply mouse
(10090), and this species is propagated to alternate IDs in the record.
For other sources the taxon remains unknown; callers importing mixed species
should provide `metadata={"taxon_id": ...}`. An incoming conflicting
alternate mapping is rejected with an `EntityResolutionIssue`.

Alternate lookup also applies conservative namespace semantics: HGNC, NCBI
Gene and Ensembl claims are gene-compatible; UniProt claims are
protein-compatible; and ChEMBL/PubChem claims are drug-compatible. A raw
accession claimed by both a gene and a protein is still ambiguous, even when
one claim has the expected type. Species-neutral identifiers (for example a
ChEMBL ID) can be used on a species-scoped edge; species-sensitive claims must
match the requested taxon.

**Limitations:** This is an initial crosswalk layer, not a complete
identity/migration solution. It detects duplicate-like alternate claims and
records them for review, but does not merge pre-existing duplicated entity
rows, infer orthologs, or repair incorrect upstream mappings. Namespace type
constraints are deliberately conservative and do not replace a curated
HGNC/NCBI/Ensembl/UniProt mapping release.
For old databases, repeat a trusted source import (e.g. the HGNC adapter)
to populate alternate mappings; existing primary IDs remain unchanged.
The table is created by the application's metadata initialization; deployments
with managed SQL migrations must add it before running the importer.

## Validation

`pytest tests/test_identifier_crosswalk.py`

Check that importing HGNC primary and NCBI/Ensembl alternatives twice is
idempotent, NCBI endpoints resolve to the same gene, and conflicting alternate
IDs cannot silently merge distinct entities.

## Audit findings from main and PR #24

The PR #24 baseline correctly introduced a provenance-ready crosswalk table
and unique-only alternate resolution. The remaining risks were: common
prefixed/aliased ID spellings were not normalized consistently; alternate
lookups could cross gene/protein entity types; explicit edge taxa could reject
species-neutral drug IDs or accept a mismatched canonical row; and a changed
name on a unique alternate claim was not surfaced as a possible duplicate.
These gaps are covered by the focused normalization and resolution tests.

## Next steps

- Reliable external-ID crosswalk imports from HGNC, MGI, UniProt and ChEMBL.
- Conflict-resolution UI/report, duplication audit and dedicated migration.
- Stable published snapshot metrics for resolved/ambiguous/skipped identifiers.
