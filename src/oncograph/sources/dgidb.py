"""DGIdb drug-gene interaction adapter.

Reads a local JSON snapshot (``scripts/fetch_dgidb_interactions.py``) of
DGIdb's own aggregated interaction view for a small, curated gene list, from
its public GraphQL API (no API key required).

**Licensing is conservative/unknown by design.** DGIdb's own software is
MIT-licensed, and its API is openly queryable, but no explicit data
redistribution license (comparable to Reactome's or CIViC's CC0 statements)
was found for the *aggregated interaction data* itself during this review.
DGIdb aggregates ~30 upstream sources with heterogeneous terms of their own
(its ``sources`` list per interaction can include e.g. ChEMBL, GuideToPharmacology,
OncoKB, CIViC, TTD, ...). This adapter therefore:

- records ``source="dgidb"`` / ``source_type=SourceType.COMPUTED`` for every
  edge -- it is never attributed to, or conflated with, any individual
  upstream contributor (in particular OncoKB, which this repository
  otherwise treats as restricted/API-key-gated -- see docs/BIOLOGICAL_SOURCES.md);
- keeps DGIdb's own list of contributing source names in ``context`` purely
  for transparency, not as a claim that OncoKB/CIViC/etc. were integrated
  directly;
- is not wired into the scheduled data-refresh pipeline until the licensing
  question above is explicitly resolved.
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


def _parse_concept_id(concept_id: str | None) -> ExternalIdentifier | None:
    """Parse a DGIdb "namespace:value" concept ID, e.g. "hgnc:3236" or "chembl:CHEMBL123"."""
    if not concept_id or ":" not in concept_id:
        return None
    namespace, _, value = concept_id.partition(":")
    namespace = namespace.strip().lower()
    value = value.strip()
    if not namespace or not value:
        return None
    if namespace == "hgnc":
        # DGIdb gives the bare HGNC numeric ID; our own HGNC adapter's
        # canonical form always carries the "HGNC:" prefix.
        value = f"HGNC:{value}"
    return ExternalIdentifier(namespace, value)


@registry.register
class DgidbAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="dgidb",
        name="DGIdb",
        homepage="https://dgidb.org/",
        license_url=None,
        redistribution=RedistributionPolicy.UNKNOWN,
        notes=(
            "DGIdb's software is MIT-licensed and its GraphQL API is openly queryable "
            "without a key, but no explicit redistribution license was found for the "
            "aggregated interaction data itself; treated as conservative/unknown, like "
            "CTD, until confirmed. Aggregates ~30 upstream sources per interaction -- "
            "never attributed to an individual contributor (esp. OncoKB)."
        ),
        source_type=SourceType.COMPUTED,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def _drugs(self) -> dict[str, dict]:
        drugs: dict[str, dict] = {}
        for row in self._records():
            identifier = _parse_concept_id(row.get("drug_concept_id"))
            if identifier is None:
                continue
            key = f"{identifier.namespace}:{identifier.value}"
            if key not in drugs:
                drugs[key] = {"identifier": identifier, "name": row.get("drug_name")}
        return drugs

    def iter_entities(self) -> Iterable[EntityRecord]:
        for entry in self._drugs().values():
            yield EntityRecord(
                entity_type="drug",
                name=entry["name"] or entry["identifier"].value,
                identifiers=(entry["identifier"],),
                metadata={"release": self.release},
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            gene_identifier = _parse_concept_id(row.get("gene_concept_id"))
            drug_identifier = _parse_concept_id(row.get("drug_concept_id"))
            if gene_identifier is None or drug_identifier is None:
                continue
            interaction_types = row.get("interaction_types") or []
            yield EdgeRecord(
                subject=drug_identifier,
                predicate="interacts_with",
                object=gene_identifier,
                source_record_id=f"{row.get('drug_concept_id')}:{row.get('gene_concept_id')}",
                context={
                    "release": self.release,
                    "interaction_types": interaction_types,
                    "contributing_sources": row.get("sources"),
                },
                evidence_type="drug_gene_interaction_aggregated",
                confidence=row.get("interaction_score"),
            )
