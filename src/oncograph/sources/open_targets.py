"""Open Targets Platform target-disease association adapter.

Reads a local JSON snapshot of target-disease association scores, produced
by ``scripts/fetch_open_drug_associations.py`` and scoped to the HGNC
targets our GtoPdb approved-drug import already resolves. Open Targets
Platform data is released under CC0.
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
)
from .registry import registry


def _disease_identifier(disease_id: str) -> ExternalIdentifier:
    """Split an Open Targets disease ID (e.g. "MONDO_0011996") into (namespace, value)."""
    namespace, separator, value = disease_id.partition("_")
    if not separator:
        return ExternalIdentifier("mondo", disease_id)
    return ExternalIdentifier(namespace.lower(), value)


@registry.register
class OpenTargetsAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="open_targets",
        name="Open Targets Platform",
        homepage="https://platform.opentargets.org/",
        license_url="https://platform-docs.opentargets.org/licence",
        redistribution=RedistributionPolicy.OPEN,
        notes=(
            "Open Targets Platform data is released under CC0. Association scores are "
            "a computed evidence aggregate, not a clinical indication; the score, "
            "scoring method, and query scope are retained for reproducibility."
        ),
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def _diseases(self) -> dict[str, dict]:
        diseases: dict[str, dict] = {}
        for row in self._records():
            disease_id = (row.get("disease_id") or "").strip()
            if disease_id and disease_id not in diseases:
                diseases[disease_id] = row
        return diseases

    def iter_entities(self) -> Iterable[EntityRecord]:
        for disease_id, row in self._diseases().items():
            yield EntityRecord(
                entity_type="disease",
                name=row.get("disease_name") or disease_id,
                identifiers=(_disease_identifier(disease_id),),
                metadata={"release": self.release},
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            hgnc_id = (row.get("hgnc_id") or "").strip()
            disease_id = (row.get("disease_id") or "").strip()
            if not hgnc_id or not disease_id:
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier("hgnc", hgnc_id),
                predicate="associated_with",
                object=_disease_identifier(disease_id),
                source_record_id=f"{row.get('ensembl_gene_id')}:{disease_id}",
                source_url=f"https://platform.opentargets.org/disease/{disease_id}",
                context={
                    "release": self.release,
                    "score": row.get("score"),
                    "method": "open_targets_target_disease_association_score",
                },
            )
