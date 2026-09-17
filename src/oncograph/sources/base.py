from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class RedistributionPolicy(StrEnum):
    OPEN = "open"
    METADATA_ONLY = "metadata_only"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class SourceType(StrEnum):
    """Coarse classification of how a source's evidence was produced.

    Deliberately small and open to new members (e.g. PUBLICATION lands with
    PubMed ingestion later) rather than exhaustive; it exists so evidence can
    be filtered/grouped by provenance kind without parsing ``source``.
    """

    CURATED_DATABASE = "curated_database"
    REGISTRY = "registry"
    COMPUTED = "computed"
    PUBLICATION = "publication"  # reserved for a future PubMed/Publication source
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
    source_type: SourceType = SourceType.UNKNOWN
    license: str | None = None


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
    # Free-form claim kind (e.g. "target_interaction", "approved_indication");
    # new adapters may introduce new values without a schema change.
    evidence_type: str | None = None
    # 0.0-1.0 strength when the source natively provides one (e.g. a computed
    # association score); leave unset rather than inventing a number.
    confidence: float | None = None


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
