# Typed signed molecular observations

`oncograph.signed_molecular` provides an opt-in observation contract and local
import/query functions over the existing EntityIdentifier, Relation and Evidence
tables. Existing generic imports and public exports are unchanged; no database
migration is required.

| Predicates | Subject -> object | Sign | Evidence family |
| --- | --- | --- | --- |
| upregulates / downregulates | drug -> gene | +1 / -1 | drug_induced_transcription |
| activates / inhibits | drug -> protein | +1 / -1 | protein_functional_modulation |
| upregulated_in / downregulated_in | gene -> disease | +1 / -1 | disease_expression_association |

A positive sign has meaning only within its family. Expression changes are not
binding, disease expression associations are not causal disease drivers, and
neither is an indication or clinical response claim. This module does not perform
sign multiplication, model prediction, or mechanism inference.

## Identity

`TypedCrosswalk` reads existing canonical and alternate identifier claims. All
owners are considered, including canonical/alias collisions. Resolution requires
one owner, the specified entity type and, for genes/proteins, an unambiguous
explicit species. HGNC canonical IDs imply human. A protein accession attached
to a legacy gene cannot be used as a protein endpoint.

`register` accepts source-backed EntityRecords, preflights competing claims in a
batch, preserves existing entities, and records rejected identity mappings. It
never uses display names to merge nodes. Ambiguous cross-source mappings need
review instead of automatic resolution. The index must be rebuilt after other
writers modify the database; imports are intended for a single local writer.

## Evidence

`import_signed_observations` requires original dataset, record key, predicate,
release/snapshot, source file checksum, effect sign, evidence family, observation
status and licensing. It rejects model-generated predictions and conflicting
evidence-family declarations. Adapters must retain source-specific scores and
context in `EdgeRecord.context`, without inventing unavailable experimental
metadata. Only native 0-1 confidence values belong in `EdgeRecord.confidence`.

The evidence identity includes the relation, source, original record key and
provenance/context fingerprint (including native confidence when supplied).
Repeated identical observations are idempotent; different releases, scores,
contexts and opposite effects coexist. A surrogate record key must be explicitly
identified as such by its adapter, with the original row retained.

`SignedImportReport` distinguishes mapped observations, created relations and
evidence, duplicates, skip reasons and unique endpoint resolution statuses.
Parser input/scoped counters are populated by each source adapter. No parser
success alone counts as integration.

## Queries and limits

`signed_effects(session, drug_id)` returns original evidence for drug-induced
transcriptional changes. It exposes source/context/license and flags pairs with
opposite directions across observations. That flag is not a scientific
contradiction judgment: differing cells, doses or experiments may explain it.
It excludes functional protein effects and model-generated evidence.

These helpers do not add an HTTP or browser interface, infer missing identity
mappings, or migrate legacy gene/protein conflations. Sources and licensing must
be reviewed before any data is made public.

Validation: `uv run pytest -q tests/test_signed_molecular.py`.
