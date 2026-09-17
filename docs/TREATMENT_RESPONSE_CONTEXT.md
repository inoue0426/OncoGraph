# Context-conditioned treatment response & transferability (Issue #11)

Issue #11's scope is large (treatment context, perturbation evidence,
negative/null evidence, AACT, registry-publication discrepancy,
safety/adverse-event evidence, combination therapy, treatment sequence,
model-to-patient transferability). This pass implements the pieces
backed by real, currently-fetchable data, and scaffolds/documents the
rest -- it does not force-fit fabricated or illustrative-only data into
adapter output. Investigated live during this pass on 2026-09-17.

## Implemented with real data

### Trial termination-reason classification (`sources/clinicaltrials.py`)

ClinicalTrials.gov's API v2 (already the source `sources/clinicaltrials.py`
queries directly) returns a free-text `whyStopped` field for terminated/
withdrawn/suspended trials. `_classify_termination_reason()` maps that text
to one of Issue #11's suggested categories (`SAFETY`, `LACK_OF_EFFICACY`,
`RECRUITMENT`, `FUNDING`, `BUSINESS_DECISION`, `OPERATIONAL`, `UNKNOWN`,
`NOT_REPORTED`) via **simple, literal keyword matching** -- not an LLM, not
NLP, the same "rule-based, not NLP" discipline already used for the public
explorer's search-intent parsing. This is a heuristic label:

- A trial that was never stopped gets no termination_reason at all (not a
  fabricated category).
- A stopped trial with no `whyStopped` text gets `NOT_REPORTED`, never a
  guessed category.
- **A bare `TERMINATED`/`WITHDRAWN`/`SUSPENDED` status is never, by itself,
  treated as evidence of efficacy failure** -- exactly what Issue #11 asked
  for. Only text mentioning efficacy/futility drives `LACK_OF_EFFICACY`.
- The raw `whyStopped` text is always preserved alongside the category
  (`termination_reason_raw`), so anyone using this can verify or override
  the heuristic label against the actual registry text.

Verified live against real examples fetched from the ClinicalTrials.gov API
during this pass, e.g. "Company development strategy change" ->
`BUSINESS_DECISION`, "Safety concerns raised by DSMB" -> `SAFETY`.

### Real combination treatments from ClinicalTrials.gov (`sources/clinicaltrials.py`)

`scripts/fetch_open_drug_associations.py` queries ClinicalTrials.gov once
per approved drug (`query.intr=<drug name>`). When the **same NCT ID**
appears under two or more distinct drugs, that trial genuinely tests those
drugs together -- no new source or fetch needed, this falls directly out of
data already being collected. `sources/clinicaltrials.py` now emits one
`CombinationTreatment` entity per such trial (`EntityType.COMBINATION_TREATMENT`,
new this pass), with `has_component` edges to each drug and a `tested_in`
edge to the trial -- the structure Issue #11 asked for.

Verified live: NCT03737643 ("Durvalumab Treatment in Combination With
Chemotherapy and Bevacizumab, Followed by Maintenance Durvalumab,
Bevacizumab and Olaparib...") is matched independently by both the
"durvalumab" and "olaparib" drug queries, producing one real
`durvalumab + olaparib` `CombinationTreatment` entity.

**Scoping choice, not a bug:** the `CombinationTreatment` entity is keyed
per-trial (`ctgov-combo-<hash of NCT ID>`), not per unique drug-pair. The
same two drugs tested in two different trials produce two separate
`CombinationTreatment` entities today, rather than one shared entity with
two `tested_in` edges. Merging identical drug-pairs across trials is
reasonable future work, not done here (see "Not implemented" below).

## Scaffold only: adapter + local-file interface, no fetch script, no real data

| Source | Adapter | Why scaffold-only |
|---|---|---|
| AACT | `sources/aact.py` | Distributed as a full PostgreSQL dump/live DB connection (confirmed live: its site returns a login redirect, not a flat download); not a small per-record API/file. Represents `has_reported_outcome` (POSITIVE/NEGATIVE/NULL/MIXED/INCONCLUSIVE/NOT_REPORTED) as a distinct edge from trial registration. |
| DrugComb / NCI ALMANAC / DREAM / AstraZeneca-Sanger | `sources/combination_data.py` (one generic adapter, like `ligand_receptor.py` covers CellPhoneDB/CellChatDB) | `drugcomb.org` was unreachable (connection failure) during this pass; NCI ALMANAC/DREAM/AstraZeneca-Sanger require dataset-specific registration or large downloads not confirmed feasible as a single targeted fetch. Preserves the original synergy metric name/value (Bliss/Loewe/HSA/ZIP/...) rather than collapsing to one generic score. |

## Not implemented this pass (honestly scoped out, not fabricated)

- **Outcome *direction* from ClinicalTrials.gov's own results data**
  (positive/negative/null/mixed, from `resultsSection`'s actual outcome
  measures and statistics) -- this needs materially more complex parsing
  than the registry/status fields used above, and doing it honestly
  without an LLM (forbidden for claim generation in this project) means
  real per-outcome-measure statistical parsing, which is a substantial,
  separate piece of work. `sources/aact.py`'s scaffold shape anticipates
  this (`outcome_category`), but nothing populates it with real data yet.
- **Registry-publication discrepancy detection** -- needs both a trial's
  registered outcomes and its linked publication's reported outcomes side
  by side; this repository has no Publication (`paper`) entities in its
  currently deployed graph at all (Europe PMC isn't wired into the
  scheduled refresh; see `docs/PUBLICATIONS.md`), so there is nothing to
  compare against yet.
- **Safety/adverse-event evidence** -- needs `resultsSection.adverseEventsModule`
  data, not fetched this pass (same complexity/scope reasoning as outcome
  direction above).
- **Treatment sequence** (drug A before/after drug B) and **model-to-patient
  transferability scoring** -- no real dataset with this structure was
  identified as fetchable this pass; inventing a transferability score
  without a justified method would violate Issue #11's own explicit
  instruction not to do that.
- **Perturbation/state-transition evidence** (LINCS/L1000, sci-Plex, MIX-Seq,
  Tahoe-style datasets) -- not investigated this pass; large,
  assay-specific datasets outside this pass's time budget.

## Cross-source identifier resolution

`CombinationTreatment` entities from both `sources/clinicaltrials.py` and
`sources/combination_data.py` reference their component drugs by whatever
identifier that source uses (GtoPdb ligand ID for ClinicalTrials.gov-
derived combinations, PubChem CID for the generic combination-data
scaffold) -- the same identifier-first policy as every other adapter, and
the same known crosswalk gap already documented in
`docs/BIOLOGICAL_SOURCES.md`/`docs/MECHANISTIC_SOURCES.md` when a source's
native identifier isn't this repository's canonical one for that entity.
