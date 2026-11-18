# Lewis Lab parser policy

OncoGraph currently supports selected **human** Lewis Lab files through
source-specific, local-only adapters. The supported adapters are:

| Source key | File profile | Taxon | Mapping required |
| --- | --- | --- | --- |
| `lewis_ramilowski_2015` | `Human-2015-Ramilowski-LR-pairs.txt` | 9606 | yes |
| `lewis_cabello_2020` | `Human-2020-Cabello-Aguilar-LR-pairs.csv` | 9606 | yes |
| `lewis_zheng_2022` | `Human-2022-Zheng-MetSensor-pairs.tsv` | 9606 | yes |
| `lewis_qiao_2014` | `Human-2014-Qiao-LR-pairs.xlsx` | 9606 | yes |
| `lewis_pavlicev_2017` | `Human-2017-Pavlicev-LR-pairs.xlsx` | 9606 | yes |
| `lewis_hou_2020` | `Human-2020-Hou-LR-pairs.xlsx` | 9606 | yes |
| `lewis_wang_2019` | `Human-2019-Wang-LR-pairs.csv` | 9606 | yes |
| `lewis_jin_2020` | `Human-2020-Jin-LR-pairs.csv` (audited export quarantined) | unverified | yes |
| `lewis_shao_2020` | `Human-2020-Shao-LR-pairs.txt` | 9606 | yes |
| `lewis_dimitrov_2022` | `Human-2022-Dimitrov-LR-pairs.csv` | 9606 | yes |
| `lewis_noel_2020` | `Human-2020-Noël-LR-pairs.xlsx` | 9606 | yes |
| `lewis_browaeys_2019` | LR member of `Human-2019-Browaeys-LR-pairs.zip` | 9606 | yes |

The upstream compendium is heterogeneous and its repository-level README is
not a redistribution license. No upstream files are stored here, and these
adapters must not be added to the public refresh until each file's permission,
citation, and source scope are verified.

## Explicit mapping

The CLI requires a local tab-separated mapping with columns:

```text
taxon_id  symbol  namespace  identifier  entity_type
```

Mappings are keyed by `(taxon_id, symbol)`. Missing or duplicate mappings are
reported and skipped; symbols are never used as graph identity keys. For this
project's primary scope, only human mappings (`taxon_id=9606`) should be
provided.

All five columns and their row values are required. In particular, absent or
blank `entity_type` is rejected rather than defaulted to `gene`. Older local
maps relying on that default must explicitly declare their molecular types.

XLSX parsing requires the project's `lewis` extra (which adds `openpyxl`). The
CI workflow installs this extra so workbook parser tests are not silently
skipped. Workbooks are read in memory and are never copied into the repository.

For NicheNet, only the explicitly named `NicheNet-LR-pairs.csv` archive member
is eligible. The separate signaling-network member is downstream regulation,
not a ligand-receptor interaction, and is not imported.

## Validation artifact

Validate a permission-cleared local file before any database import:

```bash
uv run python scripts/validate_lewis_source.py \
  lewis_ramilowski_2015 /path/to/Human-2015-Ramilowski-LR-pairs.txt \
  --identifier-map /path/to/human-symbol-map.tsv \
  --out /tmp/lewis-ramilowski-validation.json
```

The JSON report includes input rows, emitted entities/edges, duplicate rows,
membership edges, skipped rows, unresolved and ambiguous values, errors, and a
`valid` flag. The command exits nonzero unless the parse is clean.
Reports also record SHA-256 hashes of the source and identifier map, the release,
and taxon. Inputs are checked again after parsing to detect changes during a run.
The output path cannot overwrite either input file.

## Biological safeguards

Evidence IDs use a versioned SHA-256 fingerprint of endpoints, kinds, original
record ID, citation, source evidence, interaction type, and release. Identical
rows deduplicate independently of row order; distinct provenance is retained.
The original source ID is preserved in `context.upstream_record_id`.
Each new evidence record also retains `source_sha256`, `source_ligand`, and
`source_receptor` to trace resolved endpoints to the input file and original
partner expressions. The file hash is checked before and after reading.
Reimporting an identical observation keeps the first evidence record and its
original file hash; reordering input rows does not create duplicate evidence.
Earlier experimental imports used unversioned IDs. Reimporting those databases
can retain both old and new evidence; rebuild a disposable local database or
review those records explicitly before comparing counts. No automatic deletion
or production migration is performed.

- A source row becomes one directed evidence record; ordinary pair sources use
  `ligand_receptor_interaction`, while MEBOCOST rows use the more cautious
  `metabolite_target_association` predicate. Duplicate source rows are
  collapsed by a stable source fingerprint.
- Provenance distinguishes `curated_literature`, `curated_database`,
  `curated_network`, `curated_complex`, `source_derived`,
  `compiled_prior`, and `metabolic_association` in `context.interaction_mode`.
  A tool's use for CCC inference does not make its reference list an inferred
  cell-cell communication result. Pavlicev, NATMI, iTalk, and CellChat exports
  therefore use `source_derived` unless row-level evidence establishes a more
  specific classification. These labels describe source provenance, not a
  verified experimental evidence grade; source evidence text remains attached.
- Complex sides remain opaque `molecular_complex` entities. The parser emits
  explicit `has_subunit` membership edges and never invents component-wise
  ligand-receptor bindings.
- Metabolites require an explicit `entity_type=metabolite` mapping and retain
  their source identifier namespace (for example ChEBI).
- Protein partners accept only gene or protein mappings; mappings to drugs,
  diseases, metabolites, or preassembled complexes are rejected. Gene mappings
  retain their gene type and do not assert protein-level physical binding.
  MEBOCOST's `Annotation` is retained as `context.interaction_type`, preserving
  distinctions such as transporter versus receptor associations.
- The parser does not convert downstream-gene or functional-annotation files
  into ligand-receptor edges.
- `validation_report()` exposes input, emitted, duplicate, skipped, unresolved,
  ambiguous, and membership counts for source-level review.

The remaining Lewis files, including mouse and non-mammalian sources, remain
unintegrated until their schemas, identifier semantics, citations, and
permissions receive separate source-specific review.

The Vento/CellPhoneDB file is intentionally not enabled yet: its partner
columns contain descriptive complex labels (for example, receptor names with
subunit notation) rather than a validated identifier mapping. It must not be
forced through the simple symbol profiles above.

## Human coverage status

The upstream README lists 18 human files. Twelve have enabled profiles in
the table above. The six remaining human entries are intentionally blocked:

| File/profile | Current blocker |
| --- | --- |
| Zhao/NeuronChat 2023 | Disabled: the audited export has 182/190 blank target-subunit fields; contributor genes may represent synthesis/transport rather than ligands. |
| Kirouac 2010 | Receptor labels such as `ADIPOR 1/2` need a validated component map. |
| Choi 2015 | Folder metadata and the cited biological model need species reconciliation before using taxon 9606. |
| Vento-Tormo 2018 | Descriptive CellPhoneDB complex labels need explicit subunit mapping. |
| Ximerakis/BaderLab 2019 | The audit tool now recognizes its gzip-delimited payload; ingestion remains blocked until alias direction, species, and interaction semantics are validated. |
| OmniPath/Turei 2021 | The bundle contains intercellular proteins and PPIs, not a validated LR-pair table; no interaction may be inferred. |

The local schema audit used upstream commit
`c0ce8167c20c2f5d1a3d309e04514da9a178c41c`. NeuronChat's eight remaining
target fields are numeric, so none of its 190 rows currently has a validated
target mapping. The registered command fails explicitly, even with a supplied
identifier map. Do not reconstruct targets by splitting interaction names.
Re-enabling this source requires a reviewed upstream representation that
distinguishes ligands, metabolic contributors, targets, and interaction classes.
The NATMI workbook contains 2,293 data rows, differing from the README's 2,187;
these are format counts, not validated interactions.

### Local identifier audit (2026-11-18)

Reproduce approved-symbol-only coverage without creating a database:

```bash
uv run --extra lewis python scripts/audit_lewis_identifiers.py \
  /path/to/Ligand-Receptor-Pairs/Human /path/to/hgnc_complete_set.txt \
  --source lewis_ramilowski_2015 --source lewis_dimitrov_2022
```

The command prints JSON containing hashes, counts, unresolved values, and
ambiguities. Repeat `--source` for additional sources. Exit status 1 denotes
an incomplete, invalid, or quarantined source; partial coverage is not success.

A database-free audit of the upstream commit above used only approved HGNC
symbols (45,395 keys), without alias or former-symbol inference. The HGNC
complete-set SHA-256 was
`6df77ac3cbaeb86a6dce5e17d851ebb27b6b3cdcd2471a211a3d8464f00c54c4`.
These are parser candidates, not validated biological interactions or evidence
of redistribution permission. No database was populated. All sources have
`valid=false` because some rows remain unresolved or invalid.

| Source | Input rows | Candidate interactions | Skipped rows | Unresolved occurrences |
| --- | ---: | ---: | ---: | ---: |
| Ramilowski | 2422 | 2327 | 95 | 100 |
| Cabello | 3251 | 3172 | 76 | 78 |
| Zheng | 440 | 0 | 440 | 441 |
| Qiao | 933 | 861 | 72 | 75 |
| Pavlicev | 1006 | 859 | 142 | 177 |
| Hou | 2293 | 2284 | 9 | 9 |
| Wang | 2649 | 2533 | 116 | 121 |
| Jin | 2005 | 1862 | 143 | 150 |
| Shao | 3398 | 3382 | 16 | 17 |
| Dimitrov | 4701 | 4674 | 27 | 28 |
| Noel | 380 | 370 | 10 | 11 |
| Browaeys | 12659 | 12606 | 53 | 53 |

Unresolved counts are occurrences, not unique identifiers. Cabello had 3
duplicate rows and Pavlicev had 5. No ambiguous mappings were observed with
this restricted map. Zheng's metabolite endpoints intentionally remain
unresolved because an HGNC-only map cannot resolve HMDB identifiers. Missing
complex mappings and historical symbols still require source-specific review.

Cabello uses the actual export columns `source` and `PMIDs`. Its rows are
compiled prior knowledge, not predictions from a cell-expression analysis.
An earlier profile used incorrect column names and lost that provenance;
the corrected audit preserves nine additional distinct evidence candidates.
Previously imported local evidence requires review or rebuilding from inputs,
because the old incomplete records cannot recover their missing citations.

LIANA underscore-delimited partners are parsed as complexes, following the
[official resource implementation](https://github.com/saezlab/liana-py/blob/main/src/liana/resource/_resource_utils.py).
This resolves 4,674 candidate interactions and emits 2,230 source-specific
membership edges in the local audit. Components must all resolve; no
component-wise binding interactions are inferred.

### Metabolite identity-preservation audit

A separate MEBOCOST pass retained the 158 distinct source-provided HMDB IDs
verbatim as metabolite identities (all match `HMDB` plus seven digits), alongside
the same approved-symbol HGNC map. This produced 439 candidate associations
from 440 rows, with one unresolved gene occurrence, `TFR1`. Syntax validation
does not verify HMDB accession currency, molecular identity, or reuse rights.
The HGNC snapshot lists `TFR1` as an alias of `TFRC` (`HGNC:11763`); the
approved-symbol-only audit deliberately did not apply that alias automatically.

The source annotates 234 transporter, 155 receptor, and 51 nuclear-receptor
rows. They remain metabolite-target associations. These classes do not on
their own demonstrate extracellular signaling or cell-cell communication.
This second pass is not directly comparable with the HGNC-only table above:
it explicitly adds source-declared metabolite identities. Neither pass writes
graph data or clears redistribution permission.

### CellChat species quarantine and same-partner interactions

The audited Jin export contains mouse-specific partners including `H2-T23`,
`H2-K1`, and `PIRA2`, despite its Human directory. Its SHA-256 is
`e65535e07106d201d1436dd7858cd5a568b7cdd3b079844208d52f8e1889a864`.
The adapter now rejects the entire table if H2-prefixed or PIRA2 partner
components occur. Conserved symbols resolving to HGNC do not prove that an
interaction was reported for humans. This targeted guard is not a general
species verifier: replacement files still require independent scope review.
The historical Jin counts above are identifier-resolution candidates only;
none of those 1,862 interactions is currently eligible for ingestion from
the audited export. Excluding Jin, the audit has 33,068 candidates across
11 profiles, with 1,056 skipped rows and 1,110 unresolved occurrences.

A temporary in-memory SQLite diagnostic also found 23 source-reported
same-partner contacts previously rejected as self edges. Explicit identical
raw partners can now be retained with `source_reported_self_interaction` in
evidence context for the ligand-receptor predicate. This does not assert
autocrine signaling or validate experimental binding. Distinct raw partners
collapsing to one identifier are rejected. The diagnostic created 2,167
relations and 3,751 evidence records without import errors; a second pass
created none. It preceded the species quarantine and is not biological
validation or permission to ingest that export. No persistent database was
modified.
