"""BindingDB quantitative compound-target binding adapter -- SCAFFOLD ONLY, no real data.

Verified during Issue #10: BindingDB's documented single-file download
endpoints returned errors to a plain HTTP request (session/form-based bulk
export, not a stable direct-download URL this repository's fetch-script
pattern -- a single targeted HTTP GET, see docs/SOURCES.md -- can target).

Preserves the measurement type/value/unit instead of collapsing every
record to a binary target edge, per Issue #10's explicit requirement.

This adapter therefore:

- reads a **local** file the caller must already have (e.g. exported via
  BindingDB's own web query interface) -- it never calls BindingDB itself;
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

_VALID_MEASUREMENT_TYPES = {"KI", "KD", "IC50", "EC50"}


@registry.register
class BindingDbAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="bindingdb",
        name="BindingDB",
        homepage="https://www.bindingdb.org/",
        license_url="https://www.bindingdb.org/rwd/bind/info.jsp",
        redistribution=RedistributionPolicy.UNKNOWN,
        notes=(
            "Documented download endpoints returned errors to a plain HTTP request "
            "(session/form-based bulk export, not a stable direct-download URL). This "
            "adapter reads a local, caller-supplied export only; not wired into any "
            "pipeline."
        ),
        source_type=SourceType.CURATED_DATABASE,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        """Expected local record shape (one per BindingDB compound-target assay row)::

        {
          "pubchem_cid": "176870", "compound_name": "gefitinib",
          "target_uniprot": "P00533", "target_name": "EGFR",
          "measurement_type": "IC50", "value_nm": 20.0,
          "assay_description": "..."
        }
        """
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen_drugs: set[str] = set()
        seen_targets: set[str] = set()
        for row in self._records():
            cid = (row.get("pubchem_cid") or "").strip()
            if cid and cid not in seen_drugs:
                seen_drugs.add(cid)
                yield EntityRecord(
                    entity_type="drug",
                    name=row.get("compound_name") or cid,
                    identifiers=(ExternalIdentifier("pubchem", cid),),
                    metadata={"release": self.release},
                )
            uniprot = (row.get("target_uniprot") or "").strip()
            if uniprot and uniprot not in seen_targets:
                seen_targets.add(uniprot)
                yield EntityRecord(
                    entity_type="protein",
                    name=row.get("target_name") or uniprot,
                    identifiers=(ExternalIdentifier("uniprot", uniprot),),
                    metadata={"release": self.release},
                )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            cid = (row.get("pubchem_cid") or "").strip()
            uniprot = (row.get("target_uniprot") or "").strip()
            measurement_type = (row.get("measurement_type") or "").strip().upper()
            if not cid or not uniprot or measurement_type not in _VALID_MEASUREMENT_TYPES:
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier("pubchem", cid),
                predicate="binds",
                object=ExternalIdentifier("uniprot", uniprot),
                source_record_id=f"{cid}:{uniprot}:{measurement_type}",
                evidence_type=f"bindingdb_{measurement_type.lower()}",
                context={
                    "measurement_type": measurement_type,
                    "value_nm": row.get("value_nm"),
                    "assay_description": row.get("assay_description"),
                    "release": self.release,
                },
            )
