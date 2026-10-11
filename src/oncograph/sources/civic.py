"""CIViC clinical evidence adapter.

Reads a local JSON snapshot of accepted CIViC evidence items (produced by
``scripts/fetch_civic_evidence.py`` against CIViC's public GraphQL API, for
a small curated gene list -- not the full database). CIViC data is released
under CC0: "We provide CIViC data freely to all ... under the Creative
Commons Public Domain Dedication, CC0 1.0 Universal License."

Each evidence item becomes one edge:

- if it names a therapy: Drug (NCIt) -> Disease (DOID), predicate
  ``clinically_evidenced_for`` -- CIViC's predictive/diagnostic/prognostic
  clinical curation, distinct from GtoPdb's pharmacology-only ``targets``
  edges and from Open Targets' computed ``associated_with`` scores.
- otherwise (no therapy -- e.g. purely prognostic/oncogenic evidence about
  a variant): Gene (NCBI Gene) -> Disease (DOID), predicate
  ``clinically_associated_with``.

When CIViC supplies a molecular profile ID, a distinct Biomarker entity
also links to its disease, preserving variant context as a browsable item.

CIViC's evidence_level (A-E) and significance (SENSITIVITY/RESISTANCE/...)
are qualitative, not a 0-1 score, so they stay in ``context`` rather than
being forced into ``confidence``. ``evidence_direction`` maps to
``claim_state`` (DOES_NOT_SUPPORT -> contradicts).
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

_CLAIM_STATE_BY_DIRECTION = {
    "SUPPORTS": "supports",
    "DOES_NOT_SUPPORT": "contradicts",
    "NA": "uncertain",
}


@registry.register
class CivicAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="civic",
        name="CIViC",
        homepage="https://civicdb.org/",
        license_url="https://docs.civicdb.org/en/latest/about.html",
        redistribution=RedistributionPolicy.OPEN,
        notes=(
            "CIViC data is released under CC0. Fetched via the public GraphQL API for a "
            "small, curated gene list (see scripts/fetch_civic_evidence.py), not the full "
            "database. Clinical evidence curation is distinct from GtoPdb pharmacology "
            "edges and Open Targets computed association scores -- kept as its own "
            "predicate/source rather than merged into either."
        ),
        source_type=SourceType.CURATED_DATABASE,
        license="CC0",
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def _diseases(self) -> dict[str, dict]:
        diseases: dict[str, dict] = {}
        for row in self._records():
            doid = (row.get("disease_doid") or "").strip()
            if doid and doid not in diseases:
                diseases[doid] = row
        return diseases

    def _therapies(self) -> dict[str, str]:
        therapies: dict[str, str] = {}
        for row in self._records():
            for therapy in row.get("therapies") or []:
                ncit_id = (therapy.get("ncit_id") or "").strip()
                name = therapy.get("name")
                if ncit_id and ncit_id not in therapies:
                    therapies[ncit_id] = name
        return therapies

    def _profiles(self) -> dict[str, dict]:
        profiles: dict[str, dict] = {}
        for row in self._records():
            profile_id = str(row.get("molecular_profile_id") or "").strip()
            if profile_id and row.get("molecular_profile") and profile_id not in profiles:
                profiles[profile_id] = row
        return profiles

    def iter_entities(self) -> Iterable[EntityRecord]:
        for doid, row in self._diseases().items():
            yield EntityRecord(
                entity_type="disease",
                name=row.get("disease_name") or doid,
                identifiers=(ExternalIdentifier("doid", doid),),
                metadata={"release": self.release},
            )
        for ncit_id, name in self._therapies().items():
            yield EntityRecord(
                entity_type="drug",
                name=name or ncit_id,
                identifiers=(ExternalIdentifier("ncit", ncit_id),),
                metadata={"release": self.release},
            )
        for profile_id, row in self._profiles().items():
            yield EntityRecord(
                entity_type="biomarker",
                name=row["molecular_profile"],
                identifiers=(ExternalIdentifier("civic", profile_id),),
                metadata={"release": self.release, "gene_name": row.get("gene_name")},
            )

    def _publication(self, row: dict) -> ExternalIdentifier | None:
        if row.get("source_type") == "PUBMED" and row.get("citation_id"):
            return ExternalIdentifier("pmid", str(row["citation_id"]))
        return None

    def _shared_context(self, row: dict) -> dict:
        return {
            "release": self.release,
            "molecular_profile": row.get("molecular_profile"),
            "molecular_profile_id": row.get("molecular_profile_id"),
            "evidence_level": row.get("evidence_level"),
            "significance": row.get("significance"),
            "civic_evidence_type": row.get("evidence_type"),
            "civic_evidence_id": row.get("evidence_id"),
            "civic_review_status": "ACCEPTED",
            "gene_name": row.get("gene_name"),
            "citation_url": row.get("citation_url"),
        }

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            doid = (row.get("disease_doid") or "").strip()
            if not doid:
                continue
            claim_state = _CLAIM_STATE_BY_DIRECTION.get(row.get("evidence_direction"), "uncertain")
            evidence_type = f"civic_{(row.get('evidence_type') or 'unknown').lower()}"
            therapies = [t for t in (row.get("therapies") or []) if (t.get("ncit_id") or "").strip()]

            profile_id = str(row.get("molecular_profile_id") or "").strip()
            if profile_id and row.get("molecular_profile"):
                yield EdgeRecord(
                    subject=ExternalIdentifier("civic", profile_id),
                    predicate="has_civic_evidence_for",
                    object=ExternalIdentifier("doid", doid),
                    source_record_id=str(row.get("evidence_id")),
                    source_url=row.get("source_url"),
                    context=self._shared_context(row),
                    evidence_type=evidence_type,
                    claim_state=claim_state,
                    publication=self._publication(row),
                )

            if therapies:
                for therapy in therapies:
                    yield EdgeRecord(
                        subject=ExternalIdentifier("ncit", therapy["ncit_id"]),
                        predicate="clinically_evidenced_for",
                        object=ExternalIdentifier("doid", doid),
                        source_record_id=f"{row.get('evidence_id')}:{therapy['ncit_id']}",
                        source_url=row.get("source_url"),
                        context=self._shared_context(row),
                        evidence_type=evidence_type,
                        claim_state=claim_state,
                        publication=self._publication(row),
                    )
            else:
                gene_entrez_id = row.get("gene_entrez_id")
                if not gene_entrez_id:
                    continue
                yield EdgeRecord(
                    subject=ExternalIdentifier("ncbigene", str(gene_entrez_id)),
                    predicate="clinically_associated_with",
                    object=ExternalIdentifier("doid", doid),
                    source_record_id=str(row.get("evidence_id")),
                    source_url=row.get("source_url"),
                    context=self._shared_context(row),
                    evidence_type=evidence_type,
                    claim_state=claim_state,
                    publication=self._publication(row),
                )
