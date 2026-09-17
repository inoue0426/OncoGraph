"""DrugMechDB curated drug-mechanism-path adapter.

Reads the official ``indication_paths.json`` export (a JSON list of
networkx-style graphs, one per drug-indication pair, each with an ordered
``nodes``/``links`` chain from the drug to the disease through its real
molecular mechanism -- e.g. imatinib -[decreases activity of]-> BCR/ABL
-[causes]-> CML). DrugMechDB is released under CC0 (confirmed via the
GitHub repository's license metadata): no restriction on redistribution.

Scope of this pass: only the drug and disease endpoints (identified from
each path's own ``graph.drug_mesh``/``graph.disease_mesh`` metadata, not
positional guessing) are materialized as canonical graph entities, plus a
direct edge to the first real molecular target on the path when one is
identifiable (a "Protein"-labeled node reached by the path's first hop).
Every other intermediate node (biological processes, phenotypes, GO terms,
anatomical structures, ...) is preserved in full inside the endpoint edge's
``context`` rather than reified as its own graph entity -- DrugMechDB's node
vocabulary spans a dozen ontologies (MESH, GO, HP, UniProt, InterPro,
UBERON, CHEBI, ...) that this pass does not attempt to normalize wholesale.
This keeps the full mechanistic path inspectable (see the evidence panel's
``context``) without a large schema/normalization expansion; promoting more
node labels to first-class entities is future work, not done here.
"""

import json
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
    SourceType,
)
from .registry import registry

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", text.strip().lower()).strip("_")


def _node_by_id(nodes: list[dict], node_id: str) -> dict | None:
    return next((n for n in nodes if n.get("id") == node_id), None)


@registry.register
class DrugMechDbAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="drugmechdb",
        name="DrugMechDB",
        homepage="https://sulab.github.io/DrugMechDB/",
        license_url="https://github.com/SuLab/DrugMechDB/blob/main/LICENSE",
        redistribution=RedistributionPolicy.OPEN,
        notes=(
            "CC0 (confirmed via the GitHub repository's license metadata). Curated "
            "drug -> mechanism -> disease paths; only drug/disease endpoints and the "
            "first real molecular target are reified as entities in this pass -- the "
            "full intermediate path is preserved in the endpoint edge's evidence context."
        ),
        source_type=SourceType.CURATED_DATABASE,
        license="CC0-1.0",
    )

    def __init__(self, indication_paths_path: str | Path, release: str | None = None):
        self.indication_paths_path = Path(indication_paths_path)
        self.release = release

    def _paths(self) -> list[dict]:
        return json.loads(self.indication_paths_path.read_text(encoding="utf-8"))

    def _endpoints(self, path: dict) -> tuple[dict | None, dict | None]:
        graph = path.get("graph", {})
        nodes = path.get("nodes", [])
        drug = _node_by_id(nodes, graph.get("drug_mesh"))
        disease = _node_by_id(nodes, graph.get("disease_mesh"))
        return drug, disease

    def _first_target(self, path: dict) -> tuple[dict | None, str | None]:
        """The path's first link out of the drug node, if its target is a Protein."""
        graph = path.get("graph", {})
        drug_id = graph.get("drug_mesh")
        nodes = path.get("nodes", [])
        for link in path.get("links", []):
            if link.get("source") == drug_id:
                target = _node_by_id(nodes, link.get("target"))
                if target and target.get("label") == "Protein":
                    return target, link.get("key")
        return None, None

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen: set[str] = set()
        for path in self._paths():
            drug, disease = self._endpoints(path)
            for node in (drug, disease):
                if node is None or node["id"] in seen:
                    continue
                seen.add(node["id"])
                entity_type = "drug" if node["label"] == "Drug" else "disease"
                yield EntityRecord(
                    entity_type=entity_type,
                    name=node.get("name") or node["id"],
                    identifiers=(ExternalIdentifier("mesh", node["id"].split(":", 1)[-1]),),
                    metadata={"drugmechdb_label": node["label"], "release": self.release},
                )
            target, _ = self._first_target(path)
            if target is not None and target["id"] not in seen:
                seen.add(target["id"])
                yield EntityRecord(
                    entity_type="protein",
                    name=target.get("name") or target["id"],
                    identifiers=(ExternalIdentifier("uniprot", target["id"].split(":", 1)[-1]),),
                    metadata={"drugmechdb_label": "Protein", "release": self.release},
                )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for path in self._paths():
            drug, disease = self._endpoints(path)
            if drug is None or disease is None:
                continue
            path_id = path.get("graph", {}).get("_id")
            drug_ref = ExternalIdentifier("mesh", drug["id"].split(":", 1)[-1])
            disease_ref = ExternalIdentifier("mesh", disease["id"].split(":", 1)[-1])

            yield EdgeRecord(
                subject=drug_ref,
                predicate="implicated_in_mechanism_for",
                object=disease_ref,
                source_record_id=path_id,
                evidence_type="drugmechdb_mechanism_path",
                context={
                    "nodes": path.get("nodes", []),
                    "links": path.get("links", []),
                    "release": self.release,
                },
            )

            target, link_key = self._first_target(path)
            if target is not None and link_key:
                yield EdgeRecord(
                    subject=drug_ref,
                    predicate=_slug(link_key) or "acts_on",
                    object=ExternalIdentifier("uniprot", target["id"].split(":", 1)[-1]),
                    source_record_id=path_id,
                    evidence_type="drugmechdb_direct_target",
                    context={"link_key": link_key, "release": self.release},
                )
