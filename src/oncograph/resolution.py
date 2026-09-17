from sqlmodel import Session, select

from .models import Entity, EntityIdentifier, EntityType, ResolutionConflict
from .normalization import normalize_identifier
from .sources.base import EntityRecord


def resolve_entity(session: Session, record: EntityRecord, source: str | None = None) -> Entity:
    matches: dict[str, Entity] = {}
    normalized = [normalize_identifier(i) for i in record.identifiers]
    for identifier in normalized:
        row = session.exec(
            select(EntityIdentifier).where(
                EntityIdentifier.namespace == identifier.namespace,
                EntityIdentifier.value == identifier.value,
            )
        ).first()
        if row:
            entity = session.get(Entity, row.entity_id)
            if entity:
                matches[str(entity.id)] = entity

    if len(matches) > 1:
        for identifier in normalized:
            session.add(ResolutionConflict(namespace=identifier.namespace, value=identifier.value, reason="Identifiers resolve to multiple entities", source=source))
        session.flush()
        raise ValueError("Ambiguous entity resolution")

    if matches:
        entity = next(iter(matches.values()))
        if entity.type.value != record.entity_type:
            raise ValueError(f"Identifier resolves to {entity.type}, not {record.entity_type}")
    else:
        entity = Entity(type=EntityType(record.entity_type), name=record.name, description=record.description)
        session.add(entity)
        session.flush()

    for identifier in normalized:
        existing = session.exec(select(EntityIdentifier).where(EntityIdentifier.namespace == identifier.namespace, EntityIdentifier.value == identifier.value)).first()
        if existing is None:
            session.add(EntityIdentifier(entity_id=entity.id, namespace=identifier.namespace, value=identifier.value, source=source))
    session.flush()
    return entity
