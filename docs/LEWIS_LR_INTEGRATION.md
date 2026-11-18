# Lewis Lab ligand–receptor compendium: source audit and integration policy

Upstream: https://github.com/LewisLabUCSD/Ligand-Receptor-Pairs (default branch `master`).
Reference: Armingol et al., *Nature Reviews Genetics* (2021),
https://doi.org/10.1038/s41576-020-00292-x. Cite **each underlying article** too.

## Scope

On 2026-11-18 the upstream Git tree contained **32 dataset files**:
18 Human, 10 Mouse, and 4 Others (mammals, C. elegans, Drosophila, plants).
Formats include CSV, TSV, TXT, XLSX and ZIP. Human sets include CellPhoneDB,
NicheNet, CellChat, LIANA and OmniPath; some describe protein complexes,
downstream genes or metabolites rather than plain two-column gene pairs.

The upstream repository does **not** declare a top-level repository license.
Its README requests attribution, but citation is not a redistribution grant.
Likewise an individual database's license may not cover all its aggregated
upstream resources. **Do not add raw exports or import unknown-license content
into the public GitHub Pages refresh.** Confirm per-dataset licensing and
attribution with owners first. Local audit ≠ authorization to redistribute.

## Reproducible local audit

Obtain the upstream repository separately under its applicable terms, then:

```bash
pip install openpyxl
python scripts/audit_lewis_lr.py ../Ligand-Receptor-Pairs --out /tmp/lewis-lr-audit.json
```

The report records species-folder membership, original filename, SHA-256,
byte size, table/sheet name, first row (potential header), and subsequent
nonempty row count. A ZIP is inspected **in memory**, never extracted.
The result is a format inventory, **not** a count of verified biological
interactions. Existing data and any cached copies stay outside the repo.

## Before importing an individual dataset

1. Verify its redistribution rights, scope, citation and version.
2. Define an explicit source-specific column mapping; never guess which
   fields represent ligand, receptor, subunit, metabolite, or downstream genes.
3. Preserve raw identifiers, species taxonomy IDs, publication/source record
   IDs, interaction type, and original direction. Preserve many-to-many
   complexes rather than splitting them into invented independent bindings.
4. Generate a species-aware canonical mapping with unresolved/ambiguous ID
   reports. Do not merge human and mouse records by shared gene symbols.
5. Keep each source observation in its own `Evidence` row, even for identical
   resolved pairs. Distinguish curated physical binding from inferred CCC:
   an LR pair alone does not establish cell-type communication.
6. Quantify source-level input rows, supported rows, skipped rows, ambiguous
   IDs, duplicate pairs, and resulting evidence rows; require rerun
   idempotency tests and CI.
7. Only add a source to public `refresh-data.yml` after license clearance
   and source-specific biological validation.

## Current implementation status

OncoGraph now has a backward-compatible `EntityIdentifier` sidecar table for
explicit alternate identifiers and conservative species-aware lookup. The
first source-specific parsers are documented in
[`LEWIS_LR_PARSERS.md`](LEWIS_LR_PARSERS.md). They are intentionally limited
to selected human files and require a local, explicit `(taxon_id, symbol)`
mapping; symbols are never used as identity keys.

The parsers preserve complexes as opaque entities with explicit subunit
membership and require an explicit metabolite mapping. They do not turn
downstream-gene or functional-annotation files into ligand-receptor edges.
Remaining source files, mouse/non-mammalian species, and any public refresh
remain out of scope until source-specific permissions and biological mappings
are reviewed.

The audit script deliberately does **not** claim full integration and does
not modify the current public graph or data refresh.
