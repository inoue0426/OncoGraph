# Identifier crosswalk (incremental, backward-compatible)

The importer now records all `EntityRecord.identifiers` in
`EntityIdentifier`, while preserving the original `Entity.canonical_id`.
Endpoint resolution checks an exact canonical identifier first, then accepts
an alternate identifier **only if it resolves to one unique entity**.
Unresolved/ambiguous aliases are never name-matched.

## Species safeguards

The `taxon_id` comes from explicit record metadata when available. If absent,
HGNC primary IDs imply human (NCBI Taxonomy 9606) and MGI imply mouse
(10090), and this species is propagated to alternate IDs in the record.
For other sources the taxon remains unknown; callers importing mixed species
should provide `metadata={"taxon_id": ...}`. An incoming conflicting
alternate mapping is rejected with an `EntityResolutionIssue`.

**Limitations:** This is an initial crosswalk layer, not a complete
identity/migration solution. It does not merge pre-existing duplicated entity
rows, infer orthologs, or validate UniProt gene-versus-protein semantics.
For old databases, repeat a trusted source import (e.g. the HGNC adapter)
to populate alternate mappings; existing primary IDs remain unchanged.
The table is created by the application's metadata initialization; deployments
with managed SQL migrations must add it before running the importer.

## Validation

`pytest tests/test_identifier_crosswalk.py`

Check that importing HGNC primary and NCBI/Ensembl alternatives twice is
idempotent, NCBI endpoints resolve to the same gene, and conflicting alternate
IDs cannot silently merge distinct entities.

## Next steps

- Reliable external-ID crosswalk imports from HGNC, MGI, UniProt and ChEMBL.
- Explicit entity-type and taxon checks before accepting alternate aliases
  from other datasets; distinguish gene and protein products.
- Conflict-resolution UI/report, duplication audit and dedicated migration.
- Stable published snapshot metrics for resolved/ambiguous/skipped identifiers.
