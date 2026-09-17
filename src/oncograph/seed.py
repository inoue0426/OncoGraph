from sqlmodel import Session, select

from .db import create_db_and_tables, engine
from .models import Entity, EntityType, Evidence, Relation, VerificationStatus


def seed() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        if session.exec(select(Entity)).first() is not None:
            return

        therapy = Entity(type=EntityType.DRUG, name="Example therapy", canonical_id="example:therapy")
        target = Entity(type=EntityType.TARGET, name="Example target", canonical_id="example:target")
        disease = Entity(type=EntityType.DISEASE, name="Example cancer context", canonical_id="example:disease")
        session.add_all([therapy, target, disease])
        session.commit()

        rel1 = Relation(subject_id=therapy.id, predicate="targets", object_id=target.id)
        rel2 = Relation(subject_id=therapy.id, predicate="studied_in", object_id=disease.id)
        session.add_all([rel1, rel2])
        session.commit()

        session.add(
            Evidence(
                relation_id=rel1.id,
                source="example",
                source_id="example:1",
                summary="Synthetic seed record for demonstrating provenance.",
                extraction_method="seed",
                confidence=1.0,
                verification_status=VerificationStatus.VERIFIED,
            )
        )
        session.commit()
