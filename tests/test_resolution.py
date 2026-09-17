from sqlmodel import Session, SQLModel, create_engine, select
from oncograph.models import Entity, EntityIdentifier
from oncograph.resolution import resolve_entity
from oncograph.sources.base import EntityRecord, ExternalIdentifier


def test_resolution_reuses_identifier():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    record = EntityRecord("target", "EGFR", (ExternalIdentifier("hgnc", "EGFR"),))
    with Session(engine) as session:
        first = resolve_entity(session, record, "test")
        second = resolve_entity(session, record, "test")
        session.commit()
        assert first.id == second.id
        assert len(session.exec(select(Entity)).all()) == 1
        assert len(session.exec(select(EntityIdentifier)).all()) == 1
