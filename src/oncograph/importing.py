from dataclasses import dataclass

from .normalization import normalize_identifier
from .sources.base import EdgeRecord, EntityRecord, SourceAdapter


@dataclass
class ValidationReport:
    entities: int = 0
    edges: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_entity(record: EntityRecord) -> None:
    if not record.entity_type.strip() or not record.name.strip():
        raise ValueError("Entity type and name are required")
    for identifier in record.identifiers:
        normalize_identifier(identifier)


def validate_edge(record: EdgeRecord) -> None:
    normalize_identifier(record.subject)
    normalize_identifier(record.object)
    if not record.predicate.strip():
        raise ValueError("Edge predicate is required")
    if record.subject == record.object:
        raise ValueError("Self edges require explicit downstream handling")


def validate_adapter(adapter: SourceAdapter) -> ValidationReport:
    report = ValidationReport()
    for i, entity in enumerate(adapter.iter_entities()):
        try:
            validate_entity(entity)
            report.entities += 1
        except ValueError as exc:
            report.errors.append(f"entity[{i}]: {exc}")
    for i, edge in enumerate(adapter.iter_edges()):
        try:
            validate_edge(edge)
            report.edges += 1
        except ValueError as exc:
            report.errors.append(f"edge[{i}]: {exc}")
    return report
