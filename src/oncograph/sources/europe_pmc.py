"""Europe PMC publication adapter.

Reads two local files -- neither of which this adapter fetches itself:

- a small, hand-curated "citations" file (see ``docs/PUBLICATIONS.md``)
  saying which PMID supports which existing (subject, predicate, object)
  relation. This is original curation, not upstream content, and is
  committed to the repository (``data/curated/publication_citations.json``).
- a fetched Europe PMC metadata snapshot for those PMIDs (produced by
  ``scripts/fetch_publications.py``), giving bibliographic metadata only.

Only bibliographic metadata (title, journal, year, authors, publication
type, identifiers) is ever stored -- never an abstract or full text. A
citation attaches as literature evidence on the relation it supports,
creating that relation if it does not already exist from another source.
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


def _primary_identifier(meta: dict) -> ExternalIdentifier | None:
    """Prefer PMID, then DOI, then PMCID -- deterministic so re-imports dedupe."""
    pmid = (meta.get("pmid") or "").strip()
    if pmid:
        return ExternalIdentifier("pmid", pmid)
    doi = (meta.get("doi") or "").strip()
    if doi:
        return ExternalIdentifier("doi", doi)
    pmcid = (meta.get("pmcid") or "").strip()
    if pmcid:
        return ExternalIdentifier("pmcid", pmcid)
    return None


@registry.register
class EuropePmcAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="europe_pmc",
        name="Europe PMC",
        homepage="https://europepmc.org/",
        license_url="https://europepmc.org/Copyright",
        redistribution=RedistributionPolicy.METADATA_ONLY,
        notes=(
            "Only bibliographic metadata (title, journal, year, authors, publication "
            "type, identifiers) is imported -- never abstracts or full text. Which "
            "relation a PMID supports comes from a small, human-curated local file, "
            "not automated literature mining."
        ),
        source_type=SourceType.PUBLICATION,
    )

    def __init__(
        self,
        citations_path: str | Path,
        metadata_path: str | Path,
        release: str | None = None,
    ):
        self.citations_path = Path(citations_path)
        self.metadata_path = Path(metadata_path)
        self.release = release

    def _citations(self) -> list[dict]:
        return json.loads(self.citations_path.read_text(encoding="utf-8"))

    def _metadata_records(self) -> list[dict]:
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def _metadata_by_pmid(self) -> dict[str, dict]:
        """Fetched records keyed by PMID -- only for records that have one.

        Citations reference publications by PMID, so this is the right index
        for ``iter_edges``. It is *not* used for ``iter_entities``: a
        publication known only by DOI has no PMID and must not be dropped.
        """
        by_pmid: dict[str, dict] = {}
        for row in self._metadata_records():
            pmid = (row.get("pmid") or "").strip()
            if pmid and pmid not in by_pmid:
                by_pmid[pmid] = row
        return by_pmid

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen: set[tuple[str, str]] = set()
        for meta in self._metadata_records():
            identifier = _primary_identifier(meta)
            if identifier is None:
                continue
            key = (identifier.namespace, identifier.value)
            if key in seen:
                continue
            seen.add(key)
            yield EntityRecord(
                entity_type="paper",
                name=meta.get("title") or identifier.value,
                identifiers=(identifier,),
                metadata={
                    "journal": meta.get("journal"),
                    "year": meta.get("year"),
                    "authors": meta.get("authors"),
                    "publication_types": meta.get("pub_types"),
                    "doi": meta.get("doi"),
                    "pmcid": meta.get("pmcid"),
                    "release": self.release,
                },
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        metadata_by_pmid = self._metadata_by_pmid()
        for row in self._citations():
            pmid = (row.get("pmid") or "").strip()
            meta = metadata_by_pmid.get(pmid)
            if not meta:
                continue
            publication = _primary_identifier(meta)
            if publication is None:
                continue
            subject_namespace = (row.get("subject_namespace") or "").strip()
            subject_id = (row.get("subject_id") or "").strip()
            object_namespace = (row.get("object_namespace") or "").strip()
            object_id = (row.get("object_id") or "").strip()
            predicate = (row.get("predicate") or "").strip()
            if not all((subject_namespace, subject_id, object_namespace, object_id, predicate)):
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier(subject_namespace, subject_id),
                predicate=predicate,
                object=ExternalIdentifier(object_namespace, object_id),
                source_record_id=pmid,
                source_url=meta.get("source_url") or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                context={"release": self.release},
                evidence_type=row.get("evidence_type"),
                extraction_method=row.get("extraction_method") or "curated",
                publication=publication,
            )
