"""Generic drug-combination synergy adapter -- SCAFFOLD ONLY, no real data.

Covers DrugComb, NCI ALMANAC, DREAM combination-challenge datasets, and
AstraZeneca-Sanger combination datasets generically, the way
``sources/ligand_receptor.py`` covers CellPhoneDB/CellChatDB: none of these
were confirmed reachable via a small, stable, single-file download during
this pass (DrugComb's API endpoints were not confirmed reachable; NCI
ALMANAC/DREAM/AstraZeneca-Sanger require dataset-specific registration or
large downloads) -- see docs/TREATMENT_RESPONSE_CONTEXT.md for what was
actually checked.

Preserves the *original* synergy metric/scale (Bliss, Loewe, HSA, ZIP,
excess-over-single-agent, or a source-specific definition) rather than
collapsing every source's measurements into one generic "SYNERGY" score --
per Issue #11's explicit requirement. A normalized categorical label
(SYNERGISTIC/ADDITIVE/ANTAGONISTIC/UNCERTAIN) is accepted only when the
caller's own record already carries one with its method documented; this
adapter never derives that label itself.

Represents each combination as a first-class ``CombinationTreatment``
entity (``EntityType.COMBINATION_TREATMENT``) with ``has_component`` edges
to its drugs and a ``has_synergy_metric`` edge to the tested cell line --
the same shape ``sources/clinicaltrials.py`` uses for real
ClinicalTrials.gov-derived combinations (Issue #11).

This adapter therefore:

- reads a **local** file the caller must already have (e.g. their own
  DrugComb/NCI ALMANAC export, under that source's own terms) -- it never
  fetches from any of these sources itself;
- is not registered with any fetch script, and is not wired into the
  scheduled data-refresh pipeline.
"""

import hashlib
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


def _combination_id(source_dataset: str, drug_ids: list[str], cellosaurus_id: str) -> str:
    key = f"{source_dataset}:{'+'.join(sorted(drug_ids))}:{cellosaurus_id}"
    return f"combo-{hashlib.sha256(key.encode()).hexdigest()[:16]}"


@registry.register
class CombinationDataAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="combination_data",
        name="Drug-combination synergy datasets (DrugComb / NCI ALMANAC / DREAM / AstraZeneca-Sanger)",
        homepage="https://drugcomb.org/",
        license_url=None,
        redistribution=RedistributionPolicy.UNKNOWN,
        notes=(
            "Generic adapter for combination-response datasets not confirmed reachable "
            "via a small, stable, single-file download this pass. Reads a local, "
            "caller-supplied export only; not wired into any pipeline."
        ),
        source_type=SourceType.CURATED_DATABASE,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        """Expected local record shape (one per combination-response row)::

        {
          "source_dataset": "drugcomb_v1.5",
          "drug_pubchem_cids": ["176870", "5311"],
          "cellosaurus_id": "CVCL_0023", "cell_line_name": "A549",
          "synergy_metric_name": "ZIP", "synergy_metric_value": 12.3,
          "synergy_category": null
        }
        """
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen_drugs: set[str] = set()
        seen_lines: set[str] = set()
        seen_combos: set[str] = set()
        for row in self._records():
            drug_ids = [str(d).strip() for d in row.get("drug_pubchem_cids") or [] if str(d).strip()]
            for cid in drug_ids:
                if cid not in seen_drugs:
                    seen_drugs.add(cid)
                    yield EntityRecord(entity_type="drug", name=cid, identifiers=(ExternalIdentifier("pubchem", cid),))
            cvcl_id = (row.get("cellosaurus_id") or "").strip()
            if cvcl_id and cvcl_id not in seen_lines:
                seen_lines.add(cvcl_id)
                yield EntityRecord(
                    entity_type="cell_line",
                    name=row.get("cell_line_name") or cvcl_id,
                    identifiers=(ExternalIdentifier("cellosaurus", cvcl_id),),
                )
            dataset = (row.get("source_dataset") or "").strip()
            if len(drug_ids) >= 2 and cvcl_id and dataset:
                combo_id = _combination_id(dataset, drug_ids, cvcl_id)
                if combo_id not in seen_combos:
                    seen_combos.add(combo_id)
                    yield EntityRecord(
                        entity_type="combination_treatment",
                        name=" + ".join(sorted(drug_ids)),
                        identifiers=(ExternalIdentifier("combo", combo_id),),
                        metadata={"source_dataset": dataset, "release": self.release},
                    )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            drug_ids = [str(d).strip() for d in row.get("drug_pubchem_cids") or [] if str(d).strip()]
            cvcl_id = (row.get("cellosaurus_id") or "").strip()
            dataset = (row.get("source_dataset") or "").strip()
            if len(drug_ids) < 2 or not cvcl_id or not dataset:
                continue
            combo_ref = ExternalIdentifier("combo", _combination_id(dataset, drug_ids, cvcl_id))
            for cid in drug_ids:
                yield EdgeRecord(
                    subject=combo_ref,
                    predicate="has_component",
                    object=ExternalIdentifier("pubchem", cid),
                    evidence_type="combination_component",
                    context={"release": self.release},
                )
            yield EdgeRecord(
                subject=combo_ref,
                predicate="has_synergy_metric",
                object=ExternalIdentifier("cellosaurus", cvcl_id),
                source_record_id=f"{dataset}:{'+'.join(sorted(drug_ids))}:{cvcl_id}",
                evidence_type="combination_synergy",
                context={
                    "source_dataset": dataset,
                    "synergy_metric_name": row.get("synergy_metric_name"),
                    "synergy_metric_value": row.get("synergy_metric_value"),
                    "synergy_category": row.get("synergy_category"),
                    "release": self.release,
                },
            )
