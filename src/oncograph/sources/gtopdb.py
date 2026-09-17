"""GtoPdb approved-drug / primary-target adapter.

Uses only the official "approved drugs with primary targets" interaction
file plus the official target-to-HGNC mapping file -- not the full ligand or
interaction dump, and not the Postgres export. GtoPdb's database structure is
licensed under the Open Database License (ODbL); its content is licensed
under CC BY-SA 4.0.
"""

import csv
import re
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

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(value: str) -> str:
    return _TAG_RE.sub("", value).strip()


def _read_rows(path: Path) -> list[dict]:
    """Read a GtoPdb CSV, skipping its leading '# GtoPdb Version: ...' comment line."""
    with path.open(encoding="utf-8", newline="") as handle:
        lines = handle.readlines()
    if lines and lines[0].lstrip().startswith('"#'):
        lines = lines[1:]
    return list(csv.DictReader(lines))


@registry.register
class GtoPdbAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="gtopdb",
        name="Guide to PHARMACOLOGY (GtoPdb)",
        homepage="https://www.guidetopharmacology.org/",
        license_url="https://opendatacommons.org/licenses/odbl/",
        redistribution=RedistributionPolicy.OPEN,
        notes=(
            "GtoPdb's database structure is licensed under the Open Database License "
            "(ODbL, https://opendatacommons.org/licenses/odbl/); its content is licensed "
            "under CC BY-SA 4.0 (http://creativecommons.org/licenses/by-sa/4.0/). "
            "Preserve attribution to IUPHAR/BPS Guide to PHARMACOLOGY."
        ),
    )

    def __init__(
        self,
        interactions_path: str | Path,
        hgnc_mapping_path: str | Path,
        release: str | None = None,
    ):
        self.interactions_path = Path(interactions_path)
        self.hgnc_mapping_path = Path(hgnc_mapping_path)
        self.release = release

    def _hgnc_id_by_target_id(self) -> dict[str, str]:
        """Map GtoPdb target (IUPHAR) ID to HGNC ID, from the official mapping file only."""
        mapping: dict[str, str] = {}
        for row in _read_rows(self.hgnc_mapping_path):
            target_id = (row.get("IUPHAR ID") or "").strip()
            hgnc_id = (row.get("HGNC ID") or "").strip()
            if target_id and hgnc_id:
                mapping[target_id] = f"HGNC:{hgnc_id}"
        return mapping

    def _drug_rows(self) -> Iterable[dict]:
        seen: set[str] = set()
        for row in _read_rows(self.interactions_path):
            ligand_id = (row.get("Ligand ID") or "").strip()
            if not ligand_id or ligand_id in seen:
                continue
            seen.add(ligand_id)
            yield row

    def iter_entities(self) -> Iterable[EntityRecord]:
        for row in self._drug_rows():
            ligand_id = row["Ligand ID"].strip()
            yield EntityRecord(
                entity_type="drug",
                name=_strip_tags(row.get("Ligand", "")) or ligand_id,
                identifiers=(ExternalIdentifier("gtopdb", ligand_id),),
                metadata={"release": self.release},
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        """Yield one targets-edge per drug/target row with a known HGNC mapping.

        Targets absent from the official GtP_to_HGNC_mapping.csv (e.g. non-human
        targets) are skipped here rather than guessed at by name.
        """
        hgnc_id_by_target = self._hgnc_id_by_target_id()
        for row in _read_rows(self.interactions_path):
            ligand_id = (row.get("Ligand ID") or "").strip()
            target_id = (row.get("Target ID") or "").strip()
            if not ligand_id or not target_id:
                continue
            hgnc_id = hgnc_id_by_target.get(target_id)
            if hgnc_id is None:
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier("gtopdb", ligand_id),
                predicate="targets",
                object=ExternalIdentifier("hgnc", hgnc_id),
                source_record_id=f"{ligand_id}:{target_id}",
                source_url=(
                    f"https://www.guidetopharmacology.org/GRAC/LigandDisplayForward"
                    f"?ligandId={ligand_id}"
                ),
                context={
                    "release": self.release,
                    "target_name": _strip_tags(row.get("Target", "")),
                },
            )
