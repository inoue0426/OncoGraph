"""ClinicalTrials.gov adapter for drug-associated trials.

Reads a local JSON snapshot of trial records already matched to approved
drugs by ``scripts/fetch_open_drug_associations.py``. Only public registry
metadata (NCT ID, brief title, status, phase, conditions) is stored here --
not full protocol text -- consistent with the ``metadata_only``
classification in ``oncograph.sources.catalog.CLINICAL_TRIALS``.

Also derives, from this same real data, two things Issue #11 asked for:

- a rule-based (not LLM), best-effort classification of *why* a terminated/
  withdrawn/suspended trial stopped (``termination_reason``), from the
  registry's own free-text ``whyStopped`` field -- see
  ``_classify_termination_reason``. This is a heuristic label, not an
  adjudicated fact: the raw text is always preserved alongside it
  (``termination_reason_raw``), and a trial with no ``whyStopped`` text is
  labeled ``NOT_REPORTED``, never guessed at. Operational/administrative
  termination is never equated with a biological efficacy failure.
- real **CombinationTreatment** entities: when the same trial (NCT ID)
  appears in this file under two or more distinct drugs (because each
  drug's own ClinicalTrials.gov query independently matched that trial),
  it genuinely tests those drugs together. One CombinationTreatment entity
  per such trial is created, with ``has_component`` edges to each drug and
  a ``tested_in`` edge to the trial -- see Issue #11's combination-therapy
  schema. Identical drug pairs tested in *different* trials are not merged
  into one shared CombinationTreatment entity in this pass (a scoping
  choice, not a bug -- see docs/TREATMENT_RESPONSE_CONTEXT.md).
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from .base import EdgeRecord, EntityRecord, ExternalIdentifier, SourceAdapter
from .catalog import CLINICAL_TRIALS
from .registry import registry

_MAX_CONDITIONS_TEXT = 500

# Keyword -> termination-reason category. Deliberately simple, literal
# substring matching (not NLP/an LLM) over the registry's own free-text
# whyStopped field -- a heuristic label, not an adjudicated fact. Order
# matters: the first matching category wins.
_TERMINATION_REASON_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SAFETY", ("safety", "adverse", "toxicit", "risk to participant", "side effect")),
    ("LACK_OF_EFFICACY", ("efficacy", "futility", "lack of effect", "no benefit", "did not meet", "interim analysis")),
    ("RECRUITMENT", ("accrual", "enroll", "recruit")),
    ("FUNDING", ("funding", "financial", "budget")),
    (
        "BUSINESS_DECISION",
        ("business", "sponsor decision", "strateg", "portfolio", "company decision", "development plan"),
    ),
    ("OPERATIONAL", ("logistic", "operational", "site closure", "administrative", "covid")),
)

_STOPPED_STATUSES = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}


def _classify_termination_reason(overall_status: str | None, why_stopped: str | None) -> str | None:
    """Best-effort category from the registry's own whyStopped text.

    Returns ``None`` for a trial that was never stopped (not TERMINATED/
    WITHDRAWN/SUSPENDED) -- most trials have no termination reason at all,
    and it would be misleading to label them. For a stopped trial with no
    whyStopped text, returns "NOT_REPORTED" rather than guessing.
    """
    if overall_status not in _STOPPED_STATUSES:
        return None
    if not why_stopped:
        return "NOT_REPORTED"
    lowered = why_stopped.lower()
    for category, keywords in _TERMINATION_REASON_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "UNKNOWN"


def _conditions_text(conditions: list[str] | None) -> str | None:
    """Join a trial's free-text conditions into a short, searchable description.

    Conditions are not stable identifiers (no MONDO/EFO mapping is attempted
    here), so this is kept as plain descriptive text rather than a Disease
    entity or edge -- consistent with never merging entities on display-name
    matches alone.
    """
    if not conditions:
        return None
    text = "; ".join(conditions)
    return text if len(text) <= _MAX_CONDITIONS_TEXT else text[: _MAX_CONDITIONS_TEXT - 1] + "…"


def _combination_id(nct_id: str) -> str:
    """A deterministic, stable identifier for "the combination as tested in
    this trial" -- content-derived (not a random UUID) so re-imports of the
    same file produce the same canonical_id."""
    return f"ctgov-combo-{hashlib.sha256(nct_id.encode()).hexdigest()[:16]}"


@registry.register
class ClinicalTrialsAdapter(SourceAdapter):
    descriptor = CLINICAL_TRIALS

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def _trials(self) -> dict[str, dict]:
        trials: dict[str, dict] = {}
        for row in self._records():
            nct_id = (row.get("nct_id") or "").strip()
            if nct_id and nct_id not in trials:
                trials[nct_id] = row
        return trials

    def _combinations(self) -> dict[str, list[dict]]:
        """nct_id -> its matched-drug rows, for every trial matched to 2+ distinct drugs."""
        by_trial: dict[str, dict[str, dict]] = {}
        for row in self._records():
            nct_id = (row.get("nct_id") or "").strip()
            ligand_id = (row.get("ligand_id") or "").strip()
            if not nct_id or not ligand_id:
                continue
            by_trial.setdefault(nct_id, {})[ligand_id] = row
        return {nct_id: list(rows.values()) for nct_id, rows in by_trial.items() if len(rows) >= 2}

    def iter_entities(self) -> Iterable[EntityRecord]:
        for nct_id, row in self._trials().items():
            overall_status = row.get("overall_status")
            why_stopped = row.get("why_stopped")
            yield EntityRecord(
                entity_type="trial",
                name=row.get("brief_title") or nct_id,
                identifiers=(ExternalIdentifier("clinicaltrials.gov", nct_id),),
                description=_conditions_text(row.get("conditions")),
                metadata={
                    "overall_status": overall_status,
                    "phases": row.get("phases"),
                    "conditions": row.get("conditions"),
                    "termination_reason": _classify_termination_reason(overall_status, why_stopped),
                    "termination_reason_raw": why_stopped,
                    "release": self.release,
                },
            )
        for nct_id, rows in self._combinations().items():
            yield EntityRecord(
                entity_type="combination_treatment",
                name=" + ".join(sorted(row["ligand_name"] for row in rows)),
                identifiers=(ExternalIdentifier("ctgov_combo", _combination_id(nct_id)),),
                metadata={"nct_id": nct_id, "component_ligand_ids": sorted(row["ligand_id"] for row in rows), "release": self.release},
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            ligand_id = (row.get("ligand_id") or "").strip()
            nct_id = (row.get("nct_id") or "").strip()
            if not ligand_id or not nct_id:
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier("gtopdb", ligand_id),
                predicate="studied_in",
                object=ExternalIdentifier("clinicaltrials.gov", nct_id),
                source_record_id=nct_id,
                source_url=f"https://clinicaltrials.gov/study/{nct_id}",
                context={
                    "release": self.release,
                    "overall_status": row.get("overall_status"),
                    "phases": row.get("phases"),
                    "matched_intervention": row.get("matched_intervention"),
                },
                evidence_type="clinical_trial_enrollment",
            )

        for nct_id, rows in self._combinations().items():
            combo_ref = ExternalIdentifier("ctgov_combo", _combination_id(nct_id))
            for row in rows:
                yield EdgeRecord(
                    subject=combo_ref,
                    predicate="has_component",
                    object=ExternalIdentifier("gtopdb", row["ligand_id"]),
                    source_record_id=f"{nct_id}:{row['ligand_id']}",
                    evidence_type="clinicaltrials_combination_component",
                    context={"release": self.release},
                )
            yield EdgeRecord(
                subject=combo_ref,
                predicate="tested_in",
                object=ExternalIdentifier("clinicaltrials.gov", nct_id),
                source_record_id=nct_id,
                source_url=f"https://clinicaltrials.gov/study/{nct_id}",
                evidence_type="clinicaltrials_combination_trial",
                context={"release": self.release, "overall_status": rows[0].get("overall_status")},
            )
