"""ClinicalTrials.gov adapter for drug-associated trials.

Reads a local JSON snapshot of trial records already matched to approved
drugs by ``scripts/fetch_open_drug_associations.py``. Only public registry
metadata (NCT ID, brief title, status, phase, conditions) is stored here --
not full protocol text -- consistent with the ``metadata_only``
classification in ``oncograph.sources.catalog.CLINICAL_TRIALS``.
"""

import json
from collections.abc import Iterable
from pathlib import Path

from .base import EdgeRecord, EntityRecord, ExternalIdentifier, SourceAdapter
from .catalog import CLINICAL_TRIALS
from .registry import registry


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

    def iter_entities(self) -> Iterable[EntityRecord]:
        for nct_id, row in self._trials().items():
            yield EntityRecord(
                entity_type="trial",
                name=row.get("brief_title") or nct_id,
                identifiers=(ExternalIdentifier("clinicaltrials.gov", nct_id),),
                metadata={
                    "overall_status": row.get("overall_status"),
                    "phases": row.get("phases"),
                    "conditions": row.get("conditions"),
                    "release": self.release,
                },
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
                    "matched_intervention": row.get("matched_intervention"),
                },
            )
