from dataclasses import dataclass

from sqlmodel import Session, select

from .models import Evidence, Relation, SourceSnapshot, VerificationStatus
from .normalization import normalize_identifier
from .resolution import resolve_entity
from .sources.base import EdgeRecord, EntityRecord, SourceAdapter


@dataclass
class ImportStats:
    entities_seen: int = 0
    edges_seen: int = 0
    relations_created: int = 0
    evidence_created: int = 0


def _entity_by_identifier(session: Session, identifier):
    from .models import Entity, EntityIdentifier
    norm = normalize_identifier(identifier)
    row = session.exec(select(EntityIdentifier).where(EntityIdentifier.namespace == norm.namespace, EntityIdentifier.value == norm.value)).first()
    return session.get(Entity, row.entity_id) if row else None


def persist_adapter(session: Session, adapter: SourceAdapter, *, version: str | None = None, checksum: str | None = None) -> ImportStats:
    stats = ImportStats()
    source = adapter.descriptor.key
    for record in adapter.iter_entities():
        resolve_entity(session, record, source=source)
        stats.entities_seen += 1

    for edge in adapter.iter_edges():
        stats.edges_seen += 1
        subject = _entity_by_identifier(session, edge.subject)
        obj = _entity_by_identifier(session, edge.object)
        if subject is None or obj is None:
            continue
        relation = session.exec(select(Relation).where(Relation.subject_id == subject.id, Relation.predicate == edge.predicate.strip(), Relation.object_id == obj.id)).first()
        if relation is None:
            relation = Relation(subject_id=subject.id, predicate=edge.predicate.strip(), object_id=obj.id)
            session.add(relation)
            session.flush()
            stats.relations_created += 1
        duplicate = session.exec(select(Evidence).where(Evidence.relation_id == relation.id, Evidence.source == source, Evidence.source_id == edge.source_record_id)).first()
        if duplicate is None:
            session.add(Evidence(relation_id=relation.id, source=source, source_id=edge.source_record_id, source_url=edge.source_url, context=str(edge.context) if edge.context else None, extraction_method="source_adapter", verification_status=VerificationStatus.UNVERIFIED))
            stats.evidence_created += 1

    session.add(SourceSnapshot(source=source, version=version, checksum=checksum, record_count=stats.entities_seen + stats.edges_seen, license_url=adapter.descriptor.license_url))
    session.commit()
    return stats
