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

XLSX parsing is optional and requires the project's `lewis` extra (which adds
`openpyxl`). Workbooks are read in memory and are never copied into the
repository.

## Biological safeguards

- A source row becomes one directed evidence record; ordinary pair sources use
  `ligand_receptor_interaction`, while MEBOCOST rows use the more cautious
  `metabolite_target_association` predicate. Duplicate source rows are
  collapsed by a stable source fingerprint.
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
