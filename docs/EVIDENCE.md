# Evidence schema

`Evidence` (`src/oncograph/models.py`) is the provenance record attached to a `Relation`. A
relation can carry multiple `Evidence` rows (e.g. several sources independently supporting the
same claim); nothing about the relation itself says how strong or how recent the claim is --
that all lives on `Evidence`.

## Fields

| Field                | Meaning                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| `source`              | Adapter/source key (e.g. `gtopdb`, `clinicaltrials_gov`). Set automatically from `adapter.descriptor.key` -- adapters never set this themselves. |
| `source_id`           | Stable upstream record ID (e.g. an NCT ID, or `"<ligand_id>:<target_id>"`). Used, together with `source`, to keep re-imports idempotent. |
| `source_url`          | Deep link to the upstream record, when permitted. |
| `source_type`         | Coarse provenance kind: `curated_database`, `registry`, `computed`, or (reserved) `publication`. Set automatically from `adapter.descriptor.source_type` -- adapters don't set this per edge either. |
| `evidence_type`       | Coarse claim kind, e.g. `target_interaction`, `approved_indication`, `clinical_trial_enrollment`, `target_disease_association`, `ontology_relation`. Free-form on purpose: introduce a new value for a new kind of claim without a schema change. |
| `context`             | A JSON object (stored as text) for everything else: release/version, method, score breakdowns, matched intervention name, and so on. |
| `confidence`           | A 0.0-1.0 evidentiary strength, only when the source natively provides one (e.g. a computed association score). Leave it unset for categorical/curated facts -- don't invent a number. |
| `license`             | Short human-readable license label (e.g. `"CC0"`, `"ODbL (database) / CC BY-SA 4.0 (content)"`). Set automatically from `adapter.descriptor.license`. |
| `extraction_method`   | How the record was produced (`adapter_import` for adapter-driven imports; `manual`/`seed` elsewhere). |
| `verification_status` | `unverified` / `verified` / `rejected`. |
| `retrieved_at`        | When this row was written. |

## Writing a new adapter

Most of the above is handled for you:

- `SourceDescriptor.source_type` and `SourceDescriptor.license` are declared once per adapter and
  flow onto every `Evidence` row `import_adapter()` creates for that adapter -- you don't repeat
  them per edge.
- Per edge, set `EdgeRecord.evidence_type` to a short, stable, snake_case label for the kind of
  claim (reuse an existing one from the table above when it fits), and `EdgeRecord.confidence`
  only when you have a genuine 0.0-1.0 score to report.
- Put everything else source-specific (release, method, matched name, raw score, ...) in
  `EdgeRecord.context`. Prefer this over adding a new column: `context` is a JSON object precisely
  so future dimensions -- cancer type/subtype, tissue, cell type/state, experimental model,
  mutation/biomarker, dose, timepoint, responder context, and eventually a
  SUPPORTS/CONTRADICTS/UNCERTAIN stance and a provenance chain back to an upstream claim -- can
  land there first, and only get promoted to a real column once something needs to index or query
  on it directly.

See `docs/SOURCES.md` for the source-policy side of writing an adapter (licensing, redistribution
classification, identifier namespaces).
