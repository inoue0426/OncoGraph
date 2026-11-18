import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlmodel import Session, select

from .models import (
    ClaimState,
    Entity,
    EntityIdentifier,
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

# These namespaces have a sufficiently stable biological meaning to constrain
# alternate-ID lookup. Canonical IDs remain backward-compatible and are still
# authoritative when an existing graph contains legacy data.
_ALTERNATE_IDENTIFIER_TYPES = {
    "hgnc": {EntityType.GENE},
    "ncbigene": {EntityType.GENE},
    "ensembl": {EntityType.GENE},
    "uniprot": {EntityType.PROTEIN},
    "chembl": {EntityType.DRUG},
    "pubchem": {EntityType.DRUG},
}
_SPECIES_SENSITIVE_NAMESPACES = {"hgnc", "mgi", "ncbigene", "ensembl", "uniprot"}


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
    source_reported_self = (
        record.predicate == "ligand_receptor_interaction"
        and record.context.get("source_reported_self_interaction") is True
        and bool(record.context.get("source_ligand"))
        and record.context.get("source_ligand") == record.context.get("source_receptor")
    )
    if normalize_identifier(record.subject) == normalize_identifier(record.object) and not source_reported_self:
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


def _identifier_taxon(identifier: ExternalIdentifier, metadata: dict | None = None) -> int | None:
    """Use explicit species, or the organism-specific identifier namespace."""
    if metadata and metadata.get("taxon_id") is not None:
        return int(metadata["taxon_id"])
    namespace = normalize_identifier(identifier).namespace
    return {"hgnc": 9606, "mgi": 10090}.get(namespace)


def _record_taxon(record: EntityRecord) -> int | None:
    """Return the record-level species used for all of its crosswalk rows."""
    if record.metadata.get("taxon_id") is not None:
        return int(record.metadata["taxon_id"])
    for identifier in record.identifiers:
        taxon = _identifier_taxon(identifier)
        if taxon is not None:
            return taxon
    return None


def _identifier_owners(
    session: Session, identifier: ExternalIdentifier, taxon: int | None = None
) -> set:
    """Find all entities claiming an alternate ID, preserving ambiguity."""
    normalized = normalize_identifier(identifier)
    rows = session.exec(
        select(EntityIdentifier).where(
            EntityIdentifier.namespace == normalized.namespace,
            EntityIdentifier.value == normalized.value,
        )
    ).all()
    if taxon is not None:
        rows = [
            row
            for row in rows
            if row.taxon_id == taxon
            or (row.taxon_id is None and normalized.namespace not in _SPECIES_SENSITIVE_NAMESPACES)
        ]
    return _compatible_alternate_entity_ids(session, normalized.namespace, rows)


def _entity_matches_taxon(session: Session, entity: Entity, taxon: int | None) -> bool:
    """Return whether an entity is compatible with an explicitly requested taxon."""
    if taxon is None:
        return True
    if entity.entity_metadata:
        try:
            metadata = json.loads(entity.entity_metadata)
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        if metadata.get("taxon_id") is not None:
            return int(metadata["taxon_id"]) == taxon
    rows = session.exec(
        select(EntityIdentifier).where(
            EntityIdentifier.entity_id == entity.id,
            EntityIdentifier.taxon_id == taxon,
        )
    ).all()
    return bool(rows)


def _compatible_alternate_entity_ids(
    session: Session, normalized_namespace: str, candidates: list[EntityIdentifier]
) -> set:
    """Filter alternate-ID claims whose namespace contradicts entity type."""
    allowed_types = _ALTERNATE_IDENTIFIER_TYPES.get(normalized_namespace)
    if allowed_types is None:
        return {row.entity_id for row in candidates}
    compatible: set = set()
    for row in candidates:
        entity = session.get(Entity, row.entity_id)
        if entity is not None and entity.type in allowed_types:
            compatible.add(entity.id)
    return compatible


def _lookup_entity_id(
    session: Session, identifier: ExternalIdentifier, *, taxon: int | None = None
):
    """Primary ID lookup first; uniquely indexed alternate ID second.

    Never resolve a disputed alternate identifier to the first available row.
    A canonical hit still wins so legacy graphs keep their original identity.
    """
    normalized = normalize_identifier(identifier)
    taxon = taxon if taxon is not None else _identifier_taxon(identifier)
    canonical_id = f"{normalized.namespace}:{normalized.value}"
    entity = session.exec(select(Entity).where(Entity.canonical_id == canonical_id)).first()
    if entity is not None and _entity_matches_taxon(session, entity, taxon):
        return entity.id
    candidates = session.exec(
        select(EntityIdentifier).where(
            EntityIdentifier.namespace == normalized.namespace,
            EntityIdentifier.value == normalized.value,
        )
    ).all()
    if taxon is not None:
        candidates = [
            x
            for x in candidates
            if x.taxon_id == taxon
            or (x.taxon_id is None and normalized.namespace not in _SPECIES_SENSITIVE_NAMESPACES)
        ]
    raw_owner_ids = {x.entity_id for x in candidates}
    if len(raw_owner_ids) > 1:
        return None
    owner_ids = _compatible_alternate_entity_ids(session, normalized.namespace, candidates)
    return next(iter(owner_ids)) if len(owner_ids) == 1 else None


def _register_identifiers(
    session: Session, entity: Entity, record: EntityRecord, report: ImportReport
) -> None:
    """Attach alternate IDs while surfacing ambiguous cross-entity claims."""
    for identifier in record.identifiers:
        normalized = normalize_identifier(identifier)
        taxon = _identifier_taxon(identifier, record.metadata)
        if taxon is None and record.identifiers:
            taxon = _identifier_taxon(record.identifiers[0], record.metadata)
        rows = session.exec(
            select(EntityIdentifier).where(
                EntityIdentifier.namespace == normalized.namespace,
                EntityIdentifier.value == normalized.value,
            )
        ).all()
        if any(row.entity_id == entity.id and row.taxon_id == taxon for row in rows):
            continue
        canonical_owner = session.exec(
            select(Entity).where(
                Entity.canonical_id == f"{normalized.namespace}:{normalized.value}"
            )
        ).first()
        if canonical_owner is not None and canonical_owner.id != entity.id:
            _log_resolution_issue(
                session, ResolutionIssueType.CONFLICT, identifier,
                detail="Alternate identifier already belongs to another entity",
            )
            report.entities_conflicted += 1
            report.errors.append(
                f"ambiguous alternate identifier: {normalized.namespace}:{normalized.value}"
            )
            continue
        if any(row.entity_id != entity.id and row.taxon_id == taxon for row in rows):
            # Retain both claims so the resolver remains ambiguous regardless
            # of import order; never let the first importer win by accident.
            _log_resolution_issue(
                session, ResolutionIssueType.CONFLICT, identifier,
                detail="Alternate identifier is claimed by multiple entities",
            )
            report.entities_conflicted += 1
            report.errors.append(
                f"ambiguous alternate identifier: {normalized.namespace}:{normalized.value}"
            )
        session.add(
            EntityIdentifier(
                entity_id=entity.id,
                namespace=normalized.namespace,
                value=normalized.value,
                taxon_id=taxon,
                mapping_source=record.metadata.get("source") or normalized.namespace,
            )
        )
        session.flush()


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
        taxon = _record_taxon(record)
        existing = (
            session.exec(select(Entity).where(Entity.canonical_id == canonical_id)).first()
            if canonical_id
            else None
        )
        if existing is not None and not _entity_matches_taxon(session, existing, taxon):
            existing = None
        if existing is None and record.identifiers:
            alternate_owner = _lookup_entity_id(session, record.identifiers[0], taxon=taxon)
            if alternate_owner is not None:
                existing = session.get(Entity, alternate_owner)
        if existing is None and record.identifiers:
            owners = set()
            for identifier in record.identifiers[1:]:
                owners.update(_identifier_owners(session, identifier, taxon))
            if len(owners) == 1:
                candidate = session.get(Entity, next(iter(owners)))
                # Keep the existing conservative name guard. A changed name
                # is reported as a possible duplicate instead of silently
                # merging records from unrelated adapters.
                if candidate is not None and candidate.name == record.name:
                    existing = candidate
                elif candidate is not None:
                    _log_resolution_issue(
                        session,
                        ResolutionIssueType.CONFLICT,
                        identifier,
                        detail=(
                            f"alternate identifier already belongs to {candidate.name!r}; "
                            f"incoming name is {record.name!r}"
                        ),
                    )
            elif len(owners) > 1:
                _log_resolution_issue(
                    session, ResolutionIssueType.CONFLICT, record.identifiers[0],
                    detail="Incoming record has alternate IDs owned by multiple entities",
                )
                report.entities_conflicted += 1
                report.errors.append(f"entity[{i}]: ambiguous alternate identifiers")
                continue
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
            entity = existing
        else:
            entity = Entity(
                type=entity_type,
                name=record.name,
                canonical_id=canonical_id,
                description=record.description,
                entity_metadata=_serialize_json(record.metadata),
            )
            session.add(entity)
            session.flush()
            report.entities_created += 1
        _register_identifiers(session, entity, record, report)
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
            report.edges_skipped += 1
            continue

        edge_taxon = int(record.metadata["taxon_id"]) if record.metadata.get("taxon_id") is not None else None
        subject_id = _lookup_entity_id(session, record.subject, taxon=edge_taxon)
        object_id = _lookup_entity_id(session, record.object, taxon=edge_taxon)
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

        if subject_id == object_id and normalize_identifier(record.subject) != normalize_identifier(record.object):
            report.edges_skipped += 1
            report.errors.append(f"edge[{i}]: distinct endpoint identifiers resolve to the same entity")
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
