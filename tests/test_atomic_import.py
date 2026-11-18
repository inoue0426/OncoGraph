"""Atomic imports must persist all source writes or none of them."""

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter
from oncograph.models import Entity, EntityIdentifier, EntityResolutionIssue, Evidence, Relation
from oncograph.sources.base import EdgeRecord, EntityRecord, ExternalIdentifier, SourceDescriptor


@pytest.mark.parametrize("failure", [None, "unresolved", "exception"])
def test_atomic_import_rolls_back_updates_and_new_records(
    tmp_path: Path, failure: str | None
) -> None:
    """Check durable database contents from a fresh session after source completion.

    Args:
        tmp_path: Disposable database directory.
        failure: Failure to inject after entity writes.

    Returns:
        None.
    """

    class Adapter:
        descriptor = SourceDescriptor(key="atomic_fixture", name="Fixture", homepage="")

        def iter_entities(self):
            """Return an existing entity update and a new entity."""
            return iter(
                [
                    EntityRecord("drug", "Updated", (ExternalIdentifier("chembl", "CHEMBL1"),)),
                    EntityRecord("drug", "New", (ExternalIdentifier("chembl", "CHEMBL2"),)),
                ]
            )

        def iter_edges(self):
            """Inject a failure after at least one valid edge."""
            yield EdgeRecord(
                ExternalIdentifier("chembl", "CHEMBL1"),
                "targets",
                ExternalIdentifier("chembl", "CHEMBL2"),
                source_record_id="1",
            )
            if failure == "exception":
                raise RuntimeError("fixture failure")
            if failure == "unresolved":
                yield EdgeRecord(
                    ExternalIdentifier("chembl", "CHEMBL1"),
                    "targets",
                    ExternalIdentifier("chembl", "CHEMBL3"),
                    source_record_id="2",
                )

    engine = create_engine(f"sqlite:///{tmp_path / 'atomic.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Entity(type="drug", name="Original", canonical_id="chembl:CHEMBL1"))
        session.commit()
    with Session(engine) as session:
        if failure == "exception":
            with pytest.raises(RuntimeError, match="fixture failure"):
                import_adapter(session, Adapter(), atomic=True)
        else:
            report = import_adapter(session, Adapter(), atomic=True)
            assert report.rolled_back == bool(failure)
            if failure:
                assert report.entities_created == report.entities_updated == 0
                assert report.edges_created == report.evidence_created == 0
            else:
                repeated = import_adapter(session, Adapter(), atomic=True)
                assert (
                    repeated.entities_created
                    == repeated.edges_created
                    == repeated.evidence_created
                    == 0
                )
    with Session(engine) as session:
        entities = session.exec(select(Entity)).all()
        assert len(entities) == (1 if failure else 2)
        original = next(entity for entity in entities if entity.canonical_id == "chembl:CHEMBL1")
        assert original.name == ("Original" if failure else "Updated")
        for model in (Relation, Evidence):
            assert len(session.exec(select(model)).all()) == (0 if failure else 1)
        if failure:
            assert not session.exec(select(EntityIdentifier)).all()
            assert not session.exec(select(EntityResolutionIssue)).all()
    engine.dispose()
