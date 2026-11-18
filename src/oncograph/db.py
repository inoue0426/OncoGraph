import os
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

# Import table models here so direct callers of this module (including the
# ``init_db`` command) always register the complete schema before create_all.
from . import models

DATABASE_URL = os.getenv("ONCOGRAPH_DATABASE_URL", "sqlite:///./oncograph.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def create_db_and_tables() -> None:
    """Create missing tables and the alternate-ID lookup index on existing DBs."""
    SQLModel.metadata.create_all(engine)
    # create_all does not add indexes to tables that already exist.
    for index in models.EntityIdentifier.__table__.indexes:
        if index.name == "ix_entityidentifier_namespace_value":
            index.create(engine, checkfirst=True)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
