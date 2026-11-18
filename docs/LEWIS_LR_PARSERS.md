# Lewis Lab parser policy

OncoGraph currently supports selected **human** Lewis Lab files through
source-specific, local-only adapters. The supported adapters are:

| Source key | File profile | Taxon | Mapping required |
| --- | --- | --- | --- |
| `lewis_ramilowski_2015` | `Human-2015-Ramilowski-LR-pairs.txt` | 9606 | yes |
| `lewis_cabello_2020` | `Human-2020-Cabello-Aguilar-LR-pairs.csv` | 9606 | yes |
| `lewis_zhao_2023` | `Human-2023-Zhao-LR-pairs.tsv` | 9606 | yes |
| `lewis_zheng_2022` | `Human-2022-Zheng-MetSensor-pairs.tsv` | 9606 | yes |
| `lewis_qiao_2014` | `Human-2014-Qiao-LR-pairs.xlsx` | 9606 | yes |
| `lewis_pavlicev_2017` | `Human-2017-Pavlicev-LR-pairs.xlsx` | 9606 | yes |
| `lewis_hou_2020` | `Human-2020-Hou-LR-pairs.xlsx` | 9606 | yes |
| `lewis_wang_2019` | `Human-2019-Wang-LR-pairs.csv` | 9606 | yes |
| `lewis_jin_2020` | `Human-2020-Jin-LR-pairs.csv` | 9606 | yes |
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
Earlier experimental imports used unversioned IDs. Reimporting those databases
can retain both old and new evidence; rebuild a disposable local database or
review those records explicitly before comparing counts. No automatic deletion
or production migration is performed.

- A source row becomes one directed evidence record; ordinary pair sources use
  `ligand_receptor_interaction`, while MEBOCOST rows use the more cautious
  `metabolite_target_association` predicate. Duplicate source rows are
  collapsed by a stable source fingerprint.
- Provenance distinguishes `curated_literature`, `curated_database`,
  `curated_network`, `curated_complex`, `inferred_cell_communication`,
  `compiled_prior`, and `metabolic_association` in `context.interaction_mode`.
  An inferred CCC edge is never labeled as experimentally demonstrated binding.
- Complex sides remain opaque `molecular_complex` entities. The parser emits
  explicit `has_subunit` membership edges and never invents component-wise
  ligand-receptor bindings.
- Metabolites require an explicit `entity_type=metabolite` mapping and retain
  their source identifier namespace (for example ChEBI).
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

The upstream README lists 18 human files. Thirteen have explicit profiles in
the table above. The five remaining human entries are intentionally blocked:

| File/profile | Current blocker |
| --- | --- |
| Kirouac 2010 | Receptor labels such as `ADIPOR 1/2` need a validated component map. |
| Choi 2015 | Folder metadata and the cited biological model need species reconciliation before using taxon 9606. |
| Vento-Tormo 2018 | Descriptive CellPhoneDB complex labels need explicit subunit mapping. |
| Ximerakis/BaderLab 2019 | The audit tool now recognizes its gzip-delimited payload; ingestion remains blocked until alias direction, species, and interaction semantics are validated. |
| OmniPath/Turei 2021 | The bundle contains intercellular proteins and PPIs, not a validated LR-pair table; no interaction may be inferred. |

No upstream dataset was available as a permission-cleared local import during
this implementation, so unresolved/ambiguous counts below the parser level
are not claimed for the real compendium. Each run's `validation_report()` is
the authoritative source-level report once a permitted file and explicit
human identifier map are supplied.
