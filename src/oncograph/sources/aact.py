"""AACT trial results/status/adverse-event adapter -- SCAFFOLD ONLY, no real data.

AACT (Aggregate Analysis of ClinicalTrials.gov, https://aact.ctti-clinicaltrials.org/)
distributes its relational snapshot as a full PostgreSQL database dump (a
new static copy published monthly) or a direct Postgres connection under a
registered account -- not a small per-record REST API or flat file this
repository's fetch-script pattern (a single targeted HTTP GET) can
reasonably script around, unlike the ClinicalTrials.gov API v2 endpoints
this repository already queries directly for trial status and matched
interventions (``sources/clinicaltrials.py``).

This adapter therefore:

- reads a **local** file the caller must already have (e.g. a small export
  of the relevant AACT tables from their own database copy) -- it never
  connects to AACT itself;
- is not registered with any fetch script, and is not wired into the
  scheduled data-refresh pipeline;
- represents outcome direction and adverse-event summaries as their own
  evidence dimensions, distinct from trial registration/enrollment
  (``studied_in``) and never inferring efficacy failure from a
  TERMINATED/WITHDRAWN/SUSPENDED status alone -- see Issue #11 and
  ``sources/clinicaltrials.py``'s ``_classify_termination_reason`` for the
  registry-status-only heuristic this repository already has.
"""

import json
from collections.abc import Iterable
from pathlib import Path

from .base import (
    EdgeRecord,
    EntityRecord,
    ExternalIdentifier,
    RedistributionPolicy,
    SourceAdapter,
    SourceDescriptor,
    SourceType,
)
from .registry import registry

_VALID_OUTCOME_CATEGORIES = {"POSITIVE", "NEGATIVE", "NULL", "MIXED", "INCONCLUSIVE", "NOT_REPORTED"}


@registry.register
class AactAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="aact",
        name="AACT",
        homepage="https://aact.ctti-clinicaltrials.org/",
        license_url="https://aact.ctti-clinicaltrials.org/points_of_contact",
        redistribution=RedistributionPolicy.UNKNOWN,
        notes=(
            "Distributed as a full PostgreSQL dump/connection, not a small per-record "
            "API/file. This adapter reads a local, caller-supplied export only; not "
            "wired into any pipeline. ClinicalTrials.gov's own API v2 (already used by "
            "sources/clinicaltrials.py) covers trial status/whyStopped directly."
        ),
        source_type=SourceType.REGISTRY,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        """Expected local record shape (one per trial outcome-result row)::

        {
          "nct_id": "NCT01234567",
          "outcome_category": "NEGATIVE",
          "primary_outcome_description": "Did not meet primary endpoint",
          "serious_adverse_event_count": 12, "enrollment": 240,
          "result_posted_date": "2023-05-01"
        }
        """
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        return ()  # trials themselves are Entity records via sources/clinicaltrials.py

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            nct_id = (row.get("nct_id") or "").strip()
            category = (row.get("outcome_category") or "").strip().upper()
            if not nct_id or category not in _VALID_OUTCOME_CATEGORIES:
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier("clinicaltrials.gov", nct_id),
                predicate="has_reported_outcome",
                object=ExternalIdentifier("aact_outcome_category", category),
                source_record_id=nct_id,
                evidence_type="aact_trial_outcome",
                context={
                    "outcome_category": category,
                    "primary_outcome_description": row.get("primary_outcome_description"),
                    "serious_adverse_event_count": row.get("serious_adverse_event_count"),
                    "enrollment": row.get("enrollment"),
                    "result_posted_date": row.get("result_posted_date"),
                    "release": self.release,
                },
            )
