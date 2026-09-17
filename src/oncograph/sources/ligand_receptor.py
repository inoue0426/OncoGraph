"""Ligand-receptor / cell-cell communication adapter scaffold.

**Scaffold only, not wired to a specific vendor dataset.** CellPhoneDB and
CellChatDB (the natural real sources for this) compile ligand-receptor pairs
from multiple upstream curated databases (UniProt, IUPHAR/Guide to
PHARMACOLOGY, literature curation, ...) under licensing terms this review
did not have time to fully verify per-component; see
``docs/BIOLOGICAL_SOURCES.md``. Rather than guess, this provides the schema
and adapter interface -- a generic, source-agnostic local file format -- so
a real source can be wired in later without a redesign.

Reads a local JSON list of ligand-receptor pairs:

    {
      "ligand_namespace": "hgnc", "ligand_id": "HGNC:11766", "ligand_name": "TGFB1",
      "receptor_namespace": "hgnc", "receptor_id": "HGNC:11772", "receptor_name": "TGFBR1",
      "communication_type": "inferred" | "experimental",
      "cell_type_from": "fibroblast", "cell_type_to": "T cell",  # optional
      "source_record_id": "...", "source_url": "..."
    }

Ligands/receptors are imported as ``gene`` entities (most are gene-encoded
proteins already covered by HGNC); the ``ligand``/``receptor`` role is
expressed by the ``binds`` predicate, not a separate entity type, to avoid
duplicate entities for genes already known to the graph.

**Inferred vs. experimentally demonstrated communication is never conflated**:
``communication_type`` is required and flows into both ``evidence_type``
(``ligand_receptor_binding_inferred`` / ``_experimental``) and ``context``,
so a consumer can filter or visually distinguish them.
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

_VALID_COMMUNICATION_TYPES = {"inferred", "experimental"}


@registry.register
class LigandReceptorAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="ligand_receptor",
        name="Ligand-receptor interactions (generic/scaffold)",
        homepage="https://www.cellphonedb.org/",
        redistribution=RedistributionPolicy.UNKNOWN,
        notes=(
            "Schema/adapter scaffold only -- no specific vendor dataset (e.g. CellPhoneDB, "
            "CellChatDB) is fetched or bundled here pending explicit licensing "
            "confirmation. Accepts a generic local file so a real source can be wired in "
            "without redesigning the predicate/context shape."
        ),
        source_type=SourceType.UNKNOWN,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def _genes(self) -> dict[tuple[str, str], str]:
        genes: dict[tuple[str, str], str] = {}
        for row in self._records():
            for role in ("ligand", "receptor"):
                namespace = (row.get(f"{role}_namespace") or "").strip()
                value = (row.get(f"{role}_id") or "").strip()
                name = row.get(f"{role}_name")
                if namespace and value:
                    genes.setdefault((namespace, value), name)
        return genes

    def iter_entities(self) -> Iterable[EntityRecord]:
        for (namespace, value), name in self._genes().items():
            yield EntityRecord(
                entity_type="gene",
                name=name or value,
                identifiers=(ExternalIdentifier(namespace, value),),
                metadata={"release": self.release},
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for i, row in enumerate(self._records()):
            communication_type = (row.get("communication_type") or "").strip().lower()
            if communication_type not in _VALID_COMMUNICATION_TYPES:
                continue
            ligand_namespace = (row.get("ligand_namespace") or "").strip()
            ligand_id = (row.get("ligand_id") or "").strip()
            receptor_namespace = (row.get("receptor_namespace") or "").strip()
            receptor_id = (row.get("receptor_id") or "").strip()
            if not all((ligand_namespace, ligand_id, receptor_namespace, receptor_id)):
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier(ligand_namespace, ligand_id),
                predicate="binds",
                object=ExternalIdentifier(receptor_namespace, receptor_id),
                source_record_id=row.get("source_record_id") or str(i),
                source_url=row.get("source_url"),
                context={
                    "release": self.release,
                    "communication_type": communication_type,
                    "cell_type_from": row.get("cell_type_from"),
                    "cell_type_to": row.get("cell_type_to"),
                },
                evidence_type=f"ligand_receptor_binding_{communication_type}",
            )
