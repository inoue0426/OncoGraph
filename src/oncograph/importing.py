import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlmodel import Session, select

from .models import (
    ClaimState,
    Entity,
    EntityResolutionIssue,
    EntityType,
    Evidence,
    Relation,
    ResolutionIssueType,
    utcnow,
)
from .normalization import normalize_identifier
from .sources.base import EdgeRecord, EntityRecord, ExternalIdentifier, SourceAdapter

ADAPTER_EXTRACTION_METHOD = "adapter_import"


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
    if record.confidence is not None and not 0.0 <= record.confidence <= 1.0:
        raise ValueError("Edge confidence must be between 0.0 and 1.0")
    if record.publication is not None:
        normalize_identifier(record.publication)
    if record.claim_state is not None:
        try:
            ClaimState(record.claim_state)
        except ValueError as exc:
            raise ValueError(f"Unknown claim_state {record.claim_state!r}") from exc
    try:
        json.dumps(record.context)
    except TypeError as exc:
        raise ValueError(f"Edge context must be JSON-serializable: {exc}") from exc


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


@dataclass
class ImportReport:
    entities_created: int = 0
    entities_updated: int = 0
    entities_conflicted: int = 0
    edges_created: int = 0
    edges_skipped: int = 0
    evidence_created: int = 0
    errors: list[str] = field(default_factory=list)


def _canonical_id(identifier: ExternalIdentifier) -> str:
    normalized = normalize_identifier(identifier)
    return f"{normalized.namespace}:{normalized.value}"


def _lookup_entity_id(session: Session, identifier: ExternalIdentifier):
    canonical_id = _canonical_id(identifier)
    entity = session.exec(select(Entity).where(Entity.canonical_id == canonical_id)).first()
    return entity.id if entity else None


def _log_resolution_issue(
    session: Session,
    issue_type: ResolutionIssueType,
    identifier: ExternalIdentifier,
    *,
    source: str | None = None,
    detail: str | None = None,
) -> None:
    """Durably record an unresolved/conflicting identifier for later review.

    Best-effort: normalization failures here are swallowed rather than
    raised, since this is itself error-reporting plumbing.
    """
    try:
        normalized = normalize_identifier(identifier)
        namespace, value = normalized.namespace, normalized.value
    except ValueError:
        namespace, value = identifier.namespace, identifier.value
    session.add(
        EntityResolutionIssue(
            issue_type=issue_type,
            namespace=namespace,
            value=value,
            source=source,
            detail=detail,
        )
    )


def import_entities(session: Session, records: Iterable[EntityRecord]) -> ImportReport:
    """Upsert entity candidates, keyed by the record's primary external identifier.

    Records without an identifier are inserted unconditionally since they cannot
    be matched against existing rows; callers should prefer identifier-bearing
    sources for idempotent re-imports.
    """
    report = ImportReport()
    for i, record in enumerate(records):
        try:
            validate_entity(record)
            entity_type = EntityType(record.entity_type)
        except ValueError as exc:
            report.errors.append(f"entity[{i}]: {exc}")
            continue

        canonical_id = _canonical_id(record.identifiers[0]) if record.identifiers else None
        existing = (
            session.exec(select(Entity).where(Entity.canonical_id == canonical_id)).first()
            if canonical_id
            else None
        )
        if existing is not None:
            if existing.type != entity_type:
                # Identifier-first resolution means canonical_id is authoritative;
                # a type disagreement is a mapping conflict, not a routine update.
                # Keep the existing entity untouched and log it for review.
                _log_resolution_issue(
                    session,
                    ResolutionIssueType.CONFLICT,
                    record.identifiers[0],
                    detail=(
                        f"existing type {existing.type!r} vs incoming type "
                        f"{entity_type!r} for {record.name!r}"
                    ),
                )
                report.entities_conflicted += 1
                report.errors.append(
                    f"entity[{i}]: type conflict for {canonical_id} "
                    f"(existing={existing.type}, incoming={entity_type})"
                )
                continue
            existing.name = record.name
            existing.description = record.description
            existing.entity_metadata = _serialize_json(record.metadata)
            existing.updated_at = utcnow()
            session.add(existing)
            report.entities_updated += 1
        else:
            session.add(
                Entity(
                    type=entity_type,
                    name=record.name,
                    canonical_id=canonical_id,
                    description=record.description,
                    entity_metadata=_serialize_json(record.metadata),
                )
            )
            report.entities_created += 1
    session.commit()
    return report


def _serialize_json(data: dict) -> str | None:
    return json.dumps(data, sort_keys=True) if data else None


def _ensure_evidence(
    session: Session,
    relation_id,
    record: EdgeRecord,
    source_key: str,
    extraction_method: str,
    *,
    source_type: str | None = None,
    license: str | None = None,
    publication_id=None,
) -> bool:
    """Attach a provenance-bearing Evidence row to a relation, once per source record.

    Keyed on (relation, source, source_id) so repeated imports of the same
    upstream record do not accumulate duplicate evidence. A relation can
    accumulate several such rows -- each citing a different publication, or
    each recording a different context/claim_state -- which is how one
    relation ends up supported by multiple publications, and how conflicting
    or context-specific evidence coexists instead of overwriting.
    """
    existing = session.exec(
        select(Evidence).where(
            Evidence.relation_id == relation_id,
            Evidence.source == source_key,
            Evidence.source_id == record.source_record_id,
        )
    ).first()
    if existing is not None:
        return False
    session.add(
        Evidence(
            relation_id=relation_id,
            source=source_key,
            source_id=record.source_record_id,
            source_url=record.source_url,
            source_type=source_type,
            evidence_type=record.evidence_type,
            license=license,
            publication_id=publication_id,
            context=_serialize_json(record.context),
            extraction_method=record.extraction_method or extraction_method,
            confidence=record.confidence,
            claim_state=ClaimState(record.claim_state) if record.claim_state else ClaimState.SUPPORTS,
        )
    )
    return True


def import_edges(
    session: Session,
    records: Iterable[EdgeRecord],
    *,
    source_key: str,
    extraction_method: str = ADAPTER_EXTRACTION_METHOD,
    source_type: str | None = None,
    license: str | None = None,
) -> ImportReport:
    """Persist edge candidates as Relations, resolving endpoints by canonical_id.

    Edges whose subject or object was not already imported are skipped rather
    than guessed at, since identifier-only matching must not silently merge.
    Every persisted edge also gets a provenance-bearing Evidence row, whether
    the relation itself already existed or was just created.
    """
    report = ImportReport()
    for i, record in enumerate(records):
        try:
            validate_edge(record)
        except ValueError as exc:
            report.errors.append(f"edge[{i}]: {exc}")
            continue

        subject_id = _lookup_entity_id(session, record.subject)
        object_id = _lookup_entity_id(session, record.object)
        if subject_id is None or object_id is None:
            if subject_id is None:
                _log_resolution_issue(
                    session, ResolutionIssueType.UNRESOLVED, record.subject, source=source_key
                )
            if object_id is None:
                _log_resolution_issue(
                    session, ResolutionIssueType.UNRESOLVED, record.object, source=source_key
                )
            report.edges_skipped += 1
            report.errors.append(f"edge[{i}]: unresolved endpoint")
            continue

        publication_id = _lookup_entity_id(session, record.publication) if record.publication else None
        if record.publication is not None and publication_id is None:
            _log_resolution_issue(
                session, ResolutionIssueType.UNRESOLVED, record.publication, source=source_key
            )
            report.errors.append(f"edge[{i}]: unresolved publication reference")

        exists = session.exec(
            select(Relation).where(
                Relation.subject_id == subject_id,
                Relation.predicate == record.predicate,
                Relation.object_id == object_id,
            )
        ).first()
        if exists is None:
            relation = Relation(subject_id=subject_id, predicate=record.predicate, object_id=object_id)
            session.add(relation)
            session.flush()
            relation_id = relation.id
            report.edges_created += 1
        else:
            relation_id = exists.id

        if _ensure_evidence(
            session,
            relation_id,
            record,
            source_key,
            extraction_method,
            source_type=source_type,
            license=license,
            publication_id=publication_id,
        ):
            report.evidence_created += 1
    session.commit()
    return report


def import_adapter(session: Session, adapter: SourceAdapter) -> ImportReport:
    """Import one adapter's entities, then edges, into the shared graph tables."""
    report = import_entities(session, adapter.iter_entities())
    edge_report = import_edges(
        session,
        adapter.iter_edges(),
        source_key=adapter.descriptor.key,
        source_type=adapter.descriptor.source_type,
        license=adapter.descriptor.license,
    )
    report.edges_created = edge_report.edges_created
    report.edges_skipped = edge_report.edges_skipped
    report.evidence_created = edge_report.evidence_created
    report.errors.extend(edge_report.errors)
    return report
