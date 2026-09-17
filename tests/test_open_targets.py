import json

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_entities
from oncograph.models import Entity, Evidence, Relation
from oncograph.sources import registry
from oncograph.sources.base import EntityRecord, ExternalIdentifier
from oncograph.sources.open_targets import OpenTargetsAdapter

ASSOCIATIONS = [
    {
        "hgnc_id": "HGNC:76",
        "ensembl_gene_id": "ENSG00000097007",
        "disease_id": "MONDO_0011996",
        "disease_name": "chronic myelogenous leukemia, BCR-ABL1 positive",
        "score": 0.8256952504441574,
    },
    {
        "hgnc_id": "HGNC:76",
        "ensembl_gene_id": "ENSG00000097007",
        "disease_id": "MONDO_0011996",
        "disease_name": "chronic myelogenous leukemia, BCR-ABL1 positive",
        "score": 0.8256952504441574,
    },
]


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _write_fixture(tmp_path):
    path = tmp_path / "open_targets_target_diseases.json"
    path.write_text(json.dumps(ASSOCIATIONS), encoding="utf-8")
    return path


def _seed_target(session: Session) -> None:
    import_entities(
        session,
        [
            EntityRecord(
                entity_type="gene",
                name="ABL1",
                identifiers=(ExternalIdentifier("hgnc", "HGNC:76"),),
            )
        ],
    )


def test_open_targets_adapter_is_registered():
    assert registry.get("open_targets") is OpenTargetsAdapter


def test_open_targets_dedupes_disease_entities(tmp_path):
    path = _write_fixture(tmp_path)
    adapter = OpenTargetsAdapter(path, release="2026-09-17")

    entities = list(adapter.iter_entities())

    assert len(entities) == 1
    assert entities[0].identifiers == (ExternalIdentifier("mondo", "0011996"),)


def test_open_targets_resolves_target_by_hgnc_id_and_records_score(tmp_path):
    path = _write_fixture(tmp_path)
    adapter = OpenTargetsAdapter(path, release="2026-09-17")

    with _memory_session() as session:
        _seed_target(session)
        report = import_adapter(session, adapter)

        target = session.exec(select(Entity).where(Entity.canonical_id == "hgnc:HGNC:76")).one()
        disease = session.exec(
            select(Entity).where(Entity.canonical_id == "mondo:0011996")
        ).one()
        relation = session.exec(select(Relation)).one()
        evidence = session.exec(select(Evidence)).one()

    assert report.edges_created == 1
    assert relation.subject_id == target.id
    assert relation.predicate == "associated_with"
    assert relation.object_id == disease.id

    assert evidence.source == "open_targets"
    context = json.loads(evidence.context)
    assert context["score"] == 0.8256952504441574

    assert evidence.evidence_type == "target_disease_association"
    assert evidence.source_type == "computed"
    assert evidence.license == "CC0"
    assert evidence.confidence == pytest.approx(0.8256952504441574)


def test_open_targets_reimport_is_idempotent(tmp_path):
    path = _write_fixture(tmp_path)

    with _memory_session() as session:
        _seed_target(session)
        first = import_adapter(session, OpenTargetsAdapter(path, release="2026-09-17"))
        second = import_adapter(session, OpenTargetsAdapter(path, release="2026-09-17"))

    assert first.edges_created == 1
    assert second.edges_created == 0
    assert second.evidence_created == 0
