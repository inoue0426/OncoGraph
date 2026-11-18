# Local genome-scale LINCS validation

This extends the original [SIGMA source pilot](SIGMA_KG.md), using original
Harmonizome source observations rather than reconstructing the unavailable,
balanced/pruned SIGMA-KG graph. The default legacy importer remains available.
The expanded mode is opt-in and does not change Pages, refresh jobs, or public data.

## Observed validation results

Both runs scanned the same 5,086,167 original rows. The pilot explicitly scoped
nine genes; the full run did not filter the gene list. These are completed local
imports and full re-imports, not parser-only estimates.

| Metric | Expanded nine-gene pilot | All-gene run |
| --- | ---: | ---: |
| Scoped original records | 4,435 | 5,086,167 |
| Unique source compound keys | 3,865 | 23,913 |
| Compounds with imported evidence | 3,865 | 23,912 |
| PubChem compounds with imported evidence | 255 | 10,931 |
| Source-native compounds with imported evidence | 3,610 | 12,981 |
| Genes with imported evidence | 9 | 12,113 |
| Imported relations | 4,435 | 5,081,369 |
| Imported evidence | 4,435 | 5,081,369 |
| Upregulating relations | 2,402 | 2,577,174 |
| Downregulating relations | 2,033 | 2,504,195 |
| Skipped unresolved-gene records | 0 | 4,798 (13 gene IDs) |
| Duplicate observations / duplicate relationships on first import | 0 / 0 | 0 / 0 |
| Opposite-sign pairs | 0 | 0 |
| Added relations / evidence on re-import | 0 / 0 | 0 / 0 |
| Initial import wall time | 33.71 s | 920.26 s |
| Initial import peak process RSS | 985,972,736 bytes | 970,391,552 bytes |
| Re-import wall time | 25.32 s | 287.54 s |

The full export contains 12,126 original gene IDs. One globally mapped compound
has only an unresolved-gene observation, explaining the difference between
10,932 mapped compound keys and 10,931 compounds with imported evidence. Every
source compound has a resolvable endpoint identity; source-native identity does
not imply a known PubChem/ChEMBL identity. No new ChEMBL identities were assigned.

| Compound mapping stage | Pilot keys / eligible rows | Full keys / eligible rows |
| --- | ---: | ---: |
| Legacy unique-CID lookup, before gene validation | 258 / 259 | 11,779 / 257,078 |
| Native ID plus consistent complete InChIKey | 255 / 256 | 10,932 / 247,921 |
| Additional complete-InChIKey-only matches | 0 / 0 | 0 / 0 |
| Preserved source-native identity | 3,610 / 4,179 | 12,981 / 4,838,246 |

Stricter checks downgrade uncertain global matches without discarding their
transcriptional observations. There are 252 source keys with conflicting chemical
metadata in the full export; they stay source-native. The historical pilot
imported 259 observations, compared with 4,435 in the expanded pilot.

The original export has no repeated row IDs, duplicate compound/gene/sign/score
observations, or opposite-sign native pairs. The imported graph has zero endpoint
type, human-taxon, and foreign-key violations. Synthetic tests separately verify
that contradictory observations are retained when present.

The frozen published graph (2026-10-11) has 113,630 entities and 130,900 relations.
All 12,113 affected genes match its gene identities. Of 1,148 published drug-gene
`targets` relations, 259 have endpoints resolvable under this conservative policy;
none of those pairs has a retained LINCS transcriptional observation. The other
889 target relations remain unresolved for this comparison. This restricted
result is not evidence that target/transcriptional overlap is absent in general.
The snapshot contains no pathway nodes.

LINCS2020 platform annotations for imported genes: 958 landmark, 9,020 best
inferred, 2,105 inferred, and 30 absent from that annotation file. These are not
per-observation assay validation claims. Local validation passed 476 Python tests,
20 JavaScript tests across seven suites, and Ruff. PR checks record CI for the
exact proposed commit. Full checksums and counters are in the JSON report.

## Identity policy

The previous adapter used GSE92742 alone. LINCS2020 compound metadata describes
all 23,913 chemical keys in the frozen Harmonizome export, including newer
perturbagens absent from that earlier release. Availability of a label does not
establish a global chemical identity.

The expanded resolver uses these stages:

1. An exact native perturbagen ID, an explicit GSE92742 PubChem CID, and matching
   **complete** InChIKeys in both metadata files.
2. For an exact native ID without its own CID, a complete InChIKey with exactly
   one GSE92742 CID. The CID must itself have only that complete structure key.
3. Otherwise a `lincs_consensus:<exact-source-key>` drug entity. An exact
   `cmap_name` lookup describes source membership only; it never assigns a global
   ID. Multiple member BRD IDs and structure keys remain in provenance.

No name normalization, fuzzy matching, connectivity-only key, similarity, parent
compound, salt stripping, or stereochemical normalization is used. Missing keys,
conflicting native IDs, CID-to-structure disagreements, and multiple CID candidates
cannot establish global identity. Native and label collisions retain all member
IDs and stay source-native. A complete InChIKey match is a chemical identity check,
not an assertion of formulation equivalence; original perturbagen IDs remain on
every observation.

Global resolution here means a **GSE92742-supported PubChem cross-reference with
cross-file structural consistency**, not independent revalidation against a current
PubChem structure release. Metadata errors without an observable conflict remain
possible. The old file contains 150 CIDs associated with multiple complete keys;
these are excluded from global resolution. No new ChEMBL identities are asserted.

We examined GSE70138 (no PubChem CID column), PubChem/ChEMBL exact-structure lookup
options, and UniChem. The current [UniChem source listing](https://www.ebi.ac.uk/unichem/api/v1/sources)
does not include LINCS; its [bulk mapping files](https://chembl.gitbook.io/unichem/downloads)
therefore do not supply a direct LINCS crosswalk. A future frozen PubChem/ChEMBL
structure-validation release can improve global resolution without dropping native
observations. No live API lookup is required to reproduce this run.

The HGNC crosswalk remains species-aware and rejects ambiguous IDs. UniProt
accessions remain protein identities, not aliases on gene entities. Unresolved
or conflicting genes are reported and skipped, never guessed from symbols.

## Biological interpretation

The imported sign is the original export's threshold direction and is checked
against its finite standardized score. Evidence retains the original row index,
chemical key, NCBI gene ID, symbol, score, threshold, checksums, release label,
original orientation/predicate, and mapping provenance. Different rows, scores,
contexts and releases remain different evidence records. The score is **not raw
log-fold change**, confidence, binding affinity, or a patient treatment effect.

This is a transformed consensus transcriptional signature, not a direct drug
binding experiment. Cell line, dose, duration and per-observation validation are
absent and remain unspecified. `model_generated: false` excludes new OncoGraph or
FLASH predictions; it does not mean that LINCS contains no imputed expression.

The optional geneinfo audit reports LINCS2020 `landmark`, `best inferred`, and
`inferred` platform annotations by original NCBI gene ID. These annotations are
not promoted to claims that every imported observation was directly measured or
experimentally validated. Opposite-sign pairs indicate observed disagreements;
they do not establish an error or a context-independent causal contradiction.

## Reproduce outside Git

Use Python 3.11+ and `uv sync --extra dev --extra lewis --extra signed`. Keep raw
files, databases and detailed reports outside all checkouts. The frozen inputs
and aggregate outputs are recorded in [LINCS_GENOME_VALIDATION.json](LINCS_GENOME_VALIDATION.json).
The snapshot label is a retrieval/validation label, not an invented upstream release.

Required original files:

- Harmonizome [gene_attribute_edges.txt.gz](https://maayanlab.cloud/static/hdfs/harmonizome/data/l1000chempert/gene_attribute_edges.txt.gz), saved as `lincs_edges.tsv.gz`.
- GEO [GSE92742 perturbagen metadata](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE92nnn/GSE92742/suppl/GSE92742_Broad_LINCS_pert_info.txt.gz), saved as `lincs_pert_info.txt.gz`.
- Official [LINCS2020 compoundinfo_beta.txt](https://s3.amazonaws.com/macchiato.clue.io/builds/LINCS2020/compoundinfo_beta.txt).
- HGNC [complete set](https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt), saved as `hgnc.tsv`.
- Optional audit only: official [geneinfo_beta.txt](https://s3.amazonaws.com/macchiato.clue.io/builds/LINCS2020/geneinfo_beta.txt).

Use a **separate fresh database** for the expanded validation. This is not an
in-place migration of the legacy nine-gene pilot. Changing the mapping policy or
snapshot changes provenance identities; importing both policies into one graph
can retain two transformations of the same original row. They are not independent
experiments. Re-import checks must use identical bytes, options and snapshot labels.

```sh
LINCS_RAW=/absolute/path/outside/git/raw
LINCS_WORK=/absolute/path/outside/git/validation

uv run python scripts/import_sigma_sources.py \
  --raw-dir "$LINCS_RAW" --sources lincs \
  --lincs-compoundinfo "$LINCS_WORK/compoundinfo_beta.txt" \
  --snapshot 2026-11-18-genome-validation \
  --database "$LINCS_WORK/genome.sqlite" --report "$LINCS_WORK/genome.json"

# Repeat the same command with --report .../genome-reimport.json.
# For a separate pilot.sqlite, add this exact scope:
# --gene-ids 1956,673,3845,4893,7157,5290,207,238,2064

uv run python scripts/audit_lincs_import.py \
  --database "$LINCS_WORK/genome.sqlite" \
  --geneinfo "$LINCS_WORK/geneinfo_beta.txt" \
  --edges "$LINCS_RAW/lincs_edges.tsv.gz" \
  --report "$LINCS_WORK/genome-audit.json"
```

The importer streams the export, resolves entities through the existing crosswalk,
and persists batches of 250 observations. Composite lookup indexes replace
whole-graph relation/evidence dictionaries; no table migration is required. All
batches share one transaction, rolled back on parsing or persistence errors.
Entity registration is a preceding committed step. Imports should use one writer.
The bounded observation batches do not grow with the five-million-row input;
entity/crosswalk and unique-identifier diagnostics still occupy memory. Large
provenance-bearing local databases require substantial disk space.

Import reports distinguish attempted records, unique identifiers, relation reuse,
and evidence duplication. `legacy_mapped_records` counts rows eligible under the
old compound mapper before gene validation; it is not a completed full legacy import. On a first empty import, duplicate evidence counts
repeated exact source-record/context identities; different row IDs on the same
relationship are retained as evidence. On re-import, duplicates include all
previously stored evidence. Missing metadata keys in a future export are reported
as `compound_missing_metadata`, not silently matched by name.

## Research queries

```python
from oncograph.signed_molecular import signed_compounds, signed_effects

observations = signed_effects(session, resolved_drug_uuid)
up = [row for row in observations if row['predicate'] == 'upregulates']
down = [row for row in observations if row['predicate'] == 'downregulates']
both = [row for row in observations if row['opposite_direction_observed']]
compounds = signed_compounds(session, resolved_gene_uuid)
```

Every result includes source, evidence ID, original context and license. Query
helpers require resolved UUIDs, not fuzzy name matches. They return all evidence
for one endpoint; callers should avoid requesting genome-wide evidence in one list.

Known-target overlap is the intersection of affected gene UUIDs with the objects
of evidence-bearing `targets` relations for the same drug. Protein targets require
an explicit encoding relation or reviewed HGNC product crosswalk; they must not be
renamed into genes. Similarly, join affected genes to evidence-bearing
`part_of_pathway` relations whose objects are pathway entities. Such a path is an
annotation-supported connection, not proof of pathway activation or mediation.
Existing graph traversal helpers remain available and their regression tests pass.

`compare_lincs_graph.py` implements the gene-target comparison against frozen
published JSON. It uses exact canonical IDs and unambiguous GtoPdb PubChem/ChEMBL
cross-references, never names. It reports unresolved endpoints and does not modify
either graph. The downloaded public snapshot is older than current main; its
version/checksums are retained. That snapshot has no pathway nodes, so a real
pathway-overlap claim cannot be made from it.

```sh
uv run python scripts/compare_lincs_graph.py \
  --database "$LINCS_WORK/genome.sqlite" \
  --entities "$LINCS_WORK/public-search-index.json" \
  --relations "$LINCS_WORK/public-relations.json" \
  --ligand-mapping "$LINCS_RAW/ligand_id_mapping.csv" \
  --report "$LINCS_WORK/public-comparison.json"
```

## Licensing and publication boundary

| Source | Terms and use in this work |
| --- | --- |
| Harmonizome transformed LINCS export | [CC BY-NC-SA 4.0](https://maayanlab.cloud/Harmonizome/terms); attribution, noncommercial and share-alike requirements apply. Commercial use requires an appropriate license. Used locally. |
| NIH-funded GSE92742 / GSE70138 LINCS data | [Broad redistribution policy](https://clue.io/connectopedia/category/Policies) permits redistribution of NIH/publicly funded L1000 data and requests GEO attribution and an explanation of preprocessing. GSE70138 was inspected, not imported. |
| LINCS2020 S3 metadata | Publicly downloadable, but a public URL alone does not establish unrestricted redistribution. [CLUE terms](https://clue.io/terms) and the NIH-funded exception have different scopes. Funding/license coverage of the complete beta metadata was not independently established; kept local. |
| HGNC identifiers | [CC0](https://www.genenames.org/about/license/); redistribution permitted, attribution recommended. |
| GtoPdb cross-references, comparison only | [ODbL database / CC BY-SA 4.0 content](https://www.guidetopharmacology.org/about.jsp#license); preserved as an independent comparison source, not newly imported target evidence. |
| Published OncoGraph snapshot | Comparison only; each evidence retains its source-specific license. No copied graph data committed. |

Only code, synthetic tests, documentation and aggregate validation statistics are
proposed for GitHub. No raw chemical metadata, full observations, local databases,
Pages artifacts or refresh-pipeline changes are included. Releasing a combined
derivative requires resolving the LINCS2020 metadata terms and satisfying all
applicable source terms, followed by explicit authorization.
