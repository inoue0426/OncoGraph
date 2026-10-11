"""Reactome pathway-membership adapter.

Reads Reactome's official NCBI Gene-to-pathway mapping file
(``NCBI2Reactome.txt``, tab-separated: NCBI Gene ID, Reactome pathway ID,
pathway URL, pathway name, evidence code, species), filtered to Homo
sapiens. Reactome data (the database and files derived from it) is released
under the Creative Commons Public Domain Dedication (CC0); users may copy,
modify, and redistribute it, even commercially, without permission.
"""

import csv
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

_SPECIES = "Homo sapiens"
_FIELDNAMES = ("ncbigene_id", "pathway_id", "url", "pathway_name", "evidence_code", "species")
_CANCER_GENES = frozenset(
    {"EGFR", "BRAF", "KRAS", "ALK", "ERBB2", "TP53", "PIK3CA", "BRCA1", "BRCA2"}
)


def _read_rows(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t", fieldnames=_FIELDNAMES):
            if row.get("species") == _SPECIES:
                yield row


@registry.register
class ReactomeAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="reactome",
        name="Reactome",
        homepage="https://reactome.org/",
        license_url="https://reactome.org/license",
        redistribution=RedistributionPolicy.OPEN,
        notes=(
            "Reactome data and files derived from it are released under CC0. Only the "
            "official NCBI Gene-to-pathway mapping file is used, filtered to Homo sapiens. "
            "Public refresh further limits edges to nine cancer genes via HGNC's exact NCBI IDs."
        ),
        source_type=SourceType.CURATED_DATABASE,
        license="CC0",
    )

    def __init__(
        self, ncbi2reactome_path: str | Path, release: str | None = None,
        hgnc_path: str | Path | None = None,
    ):
        self.ncbi2reactome_path = Path(ncbi2reactome_path)
        self.release = release
        self.hgnc_path = Path(hgnc_path) if hgnc_path else None

    def _selected_ids(self) -> dict[str, str] | None:
        if self.hgnc_path is None:
            return None
        with self.hgnc_path.open(encoding="utf-8", newline="") as handle:
            return {
                (row.get("entrez_id") or "").strip(): (row.get("hgnc_id") or "").strip()
                for row in csv.DictReader(handle, delimiter="\t")
                if row.get("symbol") in _CANCER_GENES
                and (row.get("entrez_id") or "").strip()
                and (row.get("hgnc_id") or "").strip()
            }

    def _selected_rows(self) -> Iterable[dict]:
        selected = self._selected_ids()
        for row in _read_rows(self.ncbi2reactome_path):
            if selected is None or (row.get("ncbigene_id") or "").strip() in selected:
                yield row

    def _pathways(self) -> dict[str, dict]:
        pathways: dict[str, dict] = {}
        for row in self._selected_rows():
            pathway_id = (row.get("pathway_id") or "").strip()
            if pathway_id and pathway_id not in pathways:
                pathways[pathway_id] = row
        return pathways

    def iter_entities(self) -> Iterable[EntityRecord]:
        for pathway_id, row in self._pathways().items():
            yield EntityRecord(
                entity_type="pathway",
                name=row.get("pathway_name") or pathway_id,
                identifiers=(ExternalIdentifier("reactome", pathway_id),),
                metadata={"species": row.get("species"), "release": self.release},
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        selected = self._selected_ids()
        for row in self._selected_rows():
            ncbigene_id = (row.get("ncbigene_id") or "").strip()
            pathway_id = (row.get("pathway_id") or "").strip()
            if not ncbigene_id or not pathway_id:
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier(
                    "hgnc" if selected is not None else "ncbigene",
                    selected[ncbigene_id] if selected is not None else ncbigene_id,
                ),
                predicate="part_of_pathway",
                object=ExternalIdentifier("reactome", pathway_id),
                source_record_id=f"{ncbigene_id}:{pathway_id}",
                source_url=row.get("url"),
                context={"evidence_code": row.get("evidence_code"), "release": self.release},
                evidence_type="pathway_membership",
            )
