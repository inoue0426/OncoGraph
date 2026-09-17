from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from oncograph.db import get_session
from oncograph.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_evidence_create_round_trips_new_schema_fields(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            drug = client.post("/entities", json={"type": "drug", "name": "Test Drug"}).json()
            gene = client.post("/entities", json={"type": "gene", "name": "Test Gene"}).json()
            relation = client.post(
                "/relations",
                json={"subject_id": drug["id"], "predicate": "targets", "object_id": gene["id"]},
            ).json()
            response = client.post(
                "/evidence",
                json={
                    "relation_id": relation["id"],
                    "source": "manual_test",
                    "source_type": "curated_database",
                    "evidence_type": "target_interaction",
                    "license": "CC0",
                    "confidence": 0.9,
                },
            )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 201
    evidence = response.json()
    assert evidence["source_type"] == "curated_database"
    assert evidence["evidence_type"] == "target_interaction"
    assert evidence["license"] == "CC0"
    assert evidence["confidence"] == 0.9


def test_evidence_create_leaves_new_fields_optional(tmp_path) -> None:
    """Existing callers that don't know about the new fields still work."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            drug = client.post("/entities", json={"type": "drug", "name": "Test Drug"}).json()
            gene = client.post("/entities", json={"type": "gene", "name": "Test Gene"}).json()
            relation = client.post(
                "/relations",
                json={"subject_id": drug["id"], "predicate": "targets", "object_id": gene["id"]},
            ).json()
            response = client.post(
                "/evidence", json={"relation_id": relation["id"], "source": "manual_test"}
            )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 201
    evidence = response.json()
    assert evidence["source_type"] is None
    assert evidence["evidence_type"] is None
    assert evidence["license"] is None
