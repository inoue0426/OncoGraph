# Drug response & experimental models (Issue #6)

## Schema

A drug-response observation is a `tested_in` edge: `Drug -> Model` (`Entity.type` one of
`cell_line`, `pdx`, `organoid`, `cohort`), with the measurement itself entirely in one
`Evidence.context`:

```json
{
  "metric_type": "IC50",
  "value": 0.42, "unit": "uM",
  "qualitative_label": null,
  "disease": "lung adenocarcinoma", "tissue": "lung",
  "assay": "CellTiter-Glo viability assay",
  "dose": "dose-response", "timepoint": "72h",
  "source_dataset": "GDSC2"
}
```

`metric_type` is one of `IC50`, `EC50`, `AUC`, `VIABILITY`, `SENSITIVITY`, `RESISTANCE`, `CR`,
`PR`, `SD`, `PD`. **These are never merged or compared as if they were the same scale**: a
concentration (IC50/EC50, typically µM or nM), a unitless curve summary (AUC), a percentage
(viability), and RECIST-style clinical categories (CR/PR/SD/PD) each stay tagged with their own
`metric_type` and (for continuous metrics) `unit`; none of this goes into `Evidence.confidence`,
which is reserved for a genuine 0.0-1.0 evidentiary-strength score (see `docs/EVIDENCE.md`) --
mixing them in would silently imply they're comparable when they aren't.

Since a `Relation` already supports multiple `Evidence` rows, a drug tested against the same model
with several metrics (e.g. both IC50 and AUC from the same experiment) becomes one `tested_in`
relation with several `Evidence` rows -- no separate table or schema needed, same pattern as
Issue #4's context-specific/conflicting evidence.

Model identity prefers, in rough order of availability: Cellosaurus (`CVCL_...`, the standard
cross-database cell line identifier -- CC0, though not yet wired to a real adapter here), a
source-specific ID (DepMap `ACH-...`, COSMIC ID) when Cellosaurus isn't available, or a
dataset-scoped cohort/PDX identifier for non-cell-line models.

## Adapter

`oncograph.sources.drug_response.DrugResponseAdapter` is **schema/adapter scaffold only** -- it
reads a generic, source-agnostic local JSON file (see the module docstring for the exact record
shape) and is not wired to any specific vendor's live data. Real integration was deliberately not
attempted this pass:

| Source | Why scaffold, not integrated |
|---|---|
| DepMap / CCLE | Public datasets, but hundreds of MB to multi-GB per release -- inappropriate to fetch/commit into this repository regardless of license. |
| GDSC | The bulk-download URL checked during this review returned `410 Gone` (moved/changed); current access path and terms need re-confirming before integration. |
| PRISM | Distributed via DepMap's portal; same size consideration as DepMap. |
| Cell Model Passports | Not checked in detail this pass. |
| LINCS / L1000 | Very large (millions of profiles); a real integration would need a deliberate scoping decision (e.g. a small curated gene/compound subset) before fetching anything. |

None of these are wired into `refresh-data.yml`. A future pass integrating one of them for real
should keep the schema above -- only the fetch/adapter plumbing needs to change, mirroring how
`oncograph.sources.reactome`/`civic` were added on top of the existing `EdgeRecord`/`Evidence`
contract without a redesign.
