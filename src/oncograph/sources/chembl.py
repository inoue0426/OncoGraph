"""ChEMBL drug mechanism-of-action adapter.

Reads a local JSON export produced by ``scripts/fetch_chembl_mechanisms.py``
(ChEMBL's ``/mechanism`` and ``/target`` REST endpoints, no key required).
ChEMBL is released under CC BY-SA 3.0 -- attribution and share-alike apply,
same handling this repository already gives GtoPdb's CC BY-SA 4.0 content.

Represents mechanism of action as a structured, typed edge (the predicate
is derived from ChEMBL's own ``action_type``, e.g. INHIBITOR -> "inhibits")
rather than only a free-text label, with the free-text ``mechanism_of_action``
description, ChEMBL's own target/mechanism record IDs, and reference
citations preserved in the edge's context -- see Issue #10.

Known limitation: entities here are keyed by ChEMBL drug/UniProt protein
identifiers, which do not currently resolve against this repository's
GtoPdb-keyed Drug entities or HGNC-keyed Gene entities (the same
identifier-crosswalk gap already documented for Reactome/CIViC/DGIdb in
docs/BIOLOGICAL_SOURCES.md) -- fixing that broadly is a larger design change
intentionally left out of this pass.
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

# ChEMBL's own action_type vocabulary -> a directed predicate. Anything not
# listed falls back to a generic predicate rather than being dropped, since
# ChEMBL introduces new action types over time.
_ACTION_TYPE_PREDICATES = {
    "INHIBITOR": "inhibits",
    "ANTAGONIST": "antagonizes",
    "AGONIST": "agonizes",
    "ACTIVATOR": "activates",
    "BLOCKER": "blocks",
    "MODULATOR": "modulates",
    "DEGRADER": "degrades",
    "PARTIAL AGONIST": "partially_agonizes",
    "INVERSE AGONIST": "inversely_agonizes",
    "BINDING AGENT": "binds",
    "SUBSTRATE": "is_substrate_of",
    "SEQUESTERING AGENT": "sequesters",
    "CROSS-LINKING AGENT": "cross_links",
    "STABILISER": "stabilizes",
    "RELEASING AGENT": "releasing_agent_for",
    "OTHER": "has_mechanism_of_action_on",
}


def _predicate_for(action_type: str | None) -> str:
    if not action_type:
        return "has_mechanism_of_action_on"
    return _ACTION_TYPE_PREDICATES.get(action_type.upper(), "has_mechanism_of_action_on")


@registry.register
class ChemblAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="chembl",
        name="ChEMBL",
        homepage="https://www.ebi.ac.uk/chembl/",
        license_url="https://www.ebi.ac.uk/about/terms-of-use",
        redistribution=RedistributionPolicy.OPEN,
        notes=(
            "CC BY-SA 3.0 (confirmed live at ebi.ac.uk/chembl). Reads a local JSON export "
            "of ChEMBL's own /mechanism and /target REST endpoints (scripts/"
            "fetch_chembl_mechanisms.py), not a full database dump."
        ),
        source_type=SourceType.CURATED_DATABASE,
        license="CC BY-SA 3.0",
    )

    def __init__(self, mechanisms_path: str | Path, release: str | None = None):
        self.mechanisms_path = Path(mechanisms_path)
        self.release = release

    def _records(self) -> list[dict]:
        return json.loads(self.mechanisms_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen_drugs: set[str] = set()
        seen_targets: set[str] = set()
        for record in self._records():
            chembl_id = record.get("chembl_id")
            if chembl_id and chembl_id not in seen_drugs:
                seen_drugs.add(chembl_id)
                yield EntityRecord(
                    entity_type="drug",
                    name=record.get("drug_name") or chembl_id,
                    identifiers=(ExternalIdentifier("chembl", chembl_id),),
                    metadata={"release": self.release},
                )
            for mechanism in record.get("mechanisms", []):
                uniprot = mechanism.get("target_uniprot")
                if not uniprot or uniprot in seen_targets:
                    continue
                seen_targets.add(uniprot)
                yield EntityRecord(
                    entity_type="protein",
                    name=mechanism.get("target_gene_symbol") or uniprot,
                    identifiers=(ExternalIdentifier("uniprot", uniprot),),
                    metadata={"release": self.release},
                )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for record in self._records():
            chembl_id = record.get("chembl_id")
            if not chembl_id:
                continue
            for mechanism in record.get("mechanisms", []):
                uniprot = mechanism.get("target_uniprot")
                if not uniprot:
                    continue
                refs = mechanism.get("mechanism_refs") or []
                yield EdgeRecord(
                    subject=ExternalIdentifier("chembl", chembl_id),
                    predicate=_predicate_for(mechanism.get("action_type")),
                    object=ExternalIdentifier("uniprot", uniprot),
                    source_record_id=str(mechanism.get("mec_id") or ""),
                    source_url=refs[0].get("ref_url") if refs else None,
                    evidence_type="chembl_mechanism_of_action",
                    context={
                        "action_type": mechanism.get("action_type"),
                        "mechanism_of_action": mechanism.get("mechanism_of_action"),
                        "target_chembl_id": mechanism.get("target_chembl_id"),
                        "max_phase": mechanism.get("max_phase"),
                        "mechanism_refs": refs,
                        "release": self.release,
                    },
                )
