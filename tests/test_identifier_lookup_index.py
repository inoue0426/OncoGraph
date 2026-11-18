"""Regression coverage for upgrading identifier lookup indexes."""

from pathlib import Path

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph import db
from oncograph.models import Entity, EntityIdentifier, EntityType

INDEX_NAME = "ix_entityidentifier_namespace_value"


def test_existing_crosswalk_gets_covering_lookup_index(tmp_path: Path, monkeypatch) -> None:
    """Upgrade existing tables without losing ambiguous identifier claims.

    Args:
        tmp_path: Temporary directory for the existing SQLite database.
        monkeypatch: Fixture replacing the configured database engine.

    Returns:
        None.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {INDEX_NAME}")
    with Session(engine) as session:
        for name in ("first", "second"):
            entity = Entity(type=EntityType.GENE, name=name)
            session.add(entity)
            session.flush()
            session.add(EntityIdentifier(
                entity_id=entity.id, namespace="ncbigene", value="123", taxon_id=9606,
            ))
        session.commit()
        original_ids = {row.id for row in session.exec(select(EntityIdentifier)).all()}

    monkeypatch.setattr(db, "engine", engine)
    db.create_db_and_tables()
    db.create_db_and_tables()

    indexes = {item["name"]: item for item in inspect(engine).get_indexes("entityidentifier")}
    assert indexes[INDEX_NAME]["column_names"] == ["namespace", "value"]
    assert not indexes[INDEX_NAME]["unique"]
    with engine.connect() as connection:
        plan = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT * FROM entityidentifier "
            "WHERE namespace='ncbigene' AND value='123'"
        ).all()
        assert any(INDEX_NAME in row[3] and "value=?" in row[3] for row in plan)
    with Session(engine) as session:
        assert {row.id for row in session.exec(select(EntityIdentifier)).all()} == original_ids
    engine.dispose()
