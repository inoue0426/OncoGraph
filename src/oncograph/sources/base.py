from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class RedistributionPolicy(StrEnum):
    OPEN = "open"
    METADATA_ONLY = "metadata_only"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceDescriptor:
    key: str
    name: str
    homepage: str
    license_url: str | None = None
    citation: str | None = None
    redistribution: RedistributionPolicy = RedistributionPolicy.UNKNOWN
    notes: str | None = None


@dataclass(frozen=True)
class ExternalIdentifier:
    namespace: str
    value: str


@dataclass(frozen=True)
class EntityRecord:
    entity_type: str
    name: str
    identifiers: tuple[ExternalIdentifier, ...] = ()
    description: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeRecord:
    subject: ExternalIdentifier
    predicate: str
    object: ExternalIdentifier
    source_record_id: str | None = None
    source_url: str | None = None
    context: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class SourceAdapter(ABC):
    descriptor: SourceDescriptor

    @abstractmethod
    def iter_entities(self) -> Iterable[EntityRecord]:
        """Yield normalized entity candidates without writing to the DB."""
        raise NotImplementedError

    @abstractmethod
    def iter_edges(self) -> Iterable[EdgeRecord]:
        """Yield provenance-bearing edge candidates without writing to the DB."""
        raise NotImplementedError
