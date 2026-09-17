"""Gene Ontology (GO) OBO adapter.

GO data products are CC BY 4.0. This adapter is intentionally file-based so
imports can be pinned to an explicit release for reproducibility.
"""

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


@registry.register
class GeneOntologyAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="gene_ontology",
        name="Gene Ontology",
        homepage="https://geneontology.org/",
        license_url="https://geneontology.org/docs/go-citation-policy/",
        redistribution=RedistributionPolicy.OPEN,
        notes="GO data products are CC BY 4.0; retain release and attribution.",
    )

    def __init__(self, obo_path: str | Path, release: str | None = None):
        self.obo_path = Path(obo_path)
        self.release = release

    def _terms(self):
        current: dict[str, object] | None = None
        with self.obo_path.open(encoding="utf-8") as handle:
            for raw in handle:
                line = raw.rstrip("\n")
                if line == "[Term]":
                    if current and current.get("id"):
                        yield current
                    current = {"is_a": [], "relationships": []}
                    continue
                if line.startswith("["):
                    if current and current.get("id"):
                        yield current
                    current = None
                    continue
                if current is None or not line or line.startswith("!"):
                    continue
                if ": " not in line:
                    continue
                key, value = line.split(": ", 1)
                if key == "is_a":
                    current["is_a"].append(value.split(" ! ", 1)[0])
                elif key == "relationship":
                    rel, target = value.split(" ", 1)
                    current["relationships"].append((rel, target.split(" ! ", 1)[0]))
                elif key in {"id", "name", "namespace", "def", "is_obsolete"}:
                    current[key] = value
        if current and current.get("id"):
            yield current

    def iter_entities(self) -> Iterable[EntityRecord]:
        for term in self._terms():
            if term.get("is_obsolete") == "true":
                continue
            go_id = str(term["id"])
            yield EntityRecord(
                entity_type="go_term",
                name=str(term.get("name", go_id)),
                identifiers=(ExternalIdentifier("go", go_id),),
                description=str(term.get("def")) if term.get("def") else None,
                metadata={"namespace": term.get("namespace"), "release": self.release},
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for term in self._terms():
            if term.get("is_obsolete") == "true":
                continue
            subject = ExternalIdentifier("go", str(term["id"]))
            for parent in term.get("is_a", []):
                yield EdgeRecord(
                    subject=subject,
                    predicate="is_a",
                    object=ExternalIdentifier("go", str(parent)),
                    source_record_id=str(term["id"]),
                    context={"release": self.release},
                )
            for predicate, target in term.get("relationships", []):
                yield EdgeRecord(
                    subject=subject,
                    predicate=str(predicate),
                    object=ExternalIdentifier("go", str(target)),
                    source_record_id=str(term["id"]),
                    context={"release": self.release},
                )
