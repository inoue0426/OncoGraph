"""DrugCentral mechanism-of-action adapter -- SCAFFOLD ONLY, no real data.

Verified during Issue #10: drugcentral.org is reachable and states a
license on its About page, but DrugCentral's primary distribution
mechanism is a full PostgreSQL database dump, not a small per-record REST
API or flat file this repository's fetch-script pattern (a single,
targeted HTTP GET, see docs/SOURCES.md) can reasonably script around.
Complementary to the ChEMBL adapter (``sources/chembl.py``), not a
replacement for it.

This adapter therefore:

- reads a **local** file the caller must already have (e.g. a small export
  of the relevant tables from their own DrugCentral database copy) -- it
  never calls or downloads from DrugCentral itself;
- is not registered with any fetch script, and is not wired into the
  scheduled data-refresh pipeline.
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


@registry.register
class DrugCentralAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="drugcentral",
        name="DrugCentral",
        homepage="https://drugcentral.org/",
        license_url="https://drugcentral.org/about",
        redistribution=RedistributionPolicy.UNKNOWN,
        notes=(
            "Reachable and states a license on its About page, but is primarily "
            "distributed as a full PostgreSQL dump rather than a small per-record API/file "
            "this repository's fetch-script pattern can target. This adapter reads a "
            "local, caller-supplied export only; not wired into any pipeline."
        ),
        source_type=SourceType.CURATED_DATABASE,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        """Expected local record shape (one per DrugCentral drug-target-action row)::

        {
          "drugcentral_id": "1610", "drug_name": "gefitinib",
          "target_uniprot": "P00533", "target_gene_symbol": "EGFR",
          "action_type": "INHIBITOR", "act_source": "SCIENTIFIC LITERATURE"
        }
        """
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen_drugs: set[str] = set()
        seen_targets: set[str] = set()
        for row in self._records():
            drug_id = (row.get("drugcentral_id") or "").strip()
            if drug_id and drug_id not in seen_drugs:
                seen_drugs.add(drug_id)
                yield EntityRecord(
                    entity_type="drug",
                    name=row.get("drug_name") or drug_id,
                    identifiers=(ExternalIdentifier("drugcentral", drug_id),),
                    metadata={"release": self.release},
                )
            uniprot = (row.get("target_uniprot") or "").strip()
            if uniprot and uniprot not in seen_targets:
                seen_targets.add(uniprot)
                yield EntityRecord(
                    entity_type="protein",
                    name=row.get("target_gene_symbol") or uniprot,
                    identifiers=(ExternalIdentifier("uniprot", uniprot),),
                    metadata={"release": self.release},
                )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            drug_id = (row.get("drugcentral_id") or "").strip()
            uniprot = (row.get("target_uniprot") or "").strip()
            if not drug_id or not uniprot:
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier("drugcentral", drug_id),
                predicate="has_mechanism_of_action_on",
                object=ExternalIdentifier("uniprot", uniprot),
                source_record_id=f"{drug_id}:{uniprot}",
                evidence_type="drugcentral_mechanism_of_action",
                context={
                    "action_type": row.get("action_type"),
                    "act_source": row.get("act_source"),
                    "release": self.release,
                },
            )
