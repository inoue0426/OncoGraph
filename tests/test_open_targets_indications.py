import json

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_entities
from oncograph.models import Entity, Evidence, Relation
from oncograph.sources import registry
from oncograph.sources.base import EntityRecord, ExternalIdentifier
from oncograph.sources.open_targets_indications import OpenTargetsIndicationsAdapter

INDICATIONS = [
    {
        "ligand_id": "3316",
        "ligand_name": "gefitinib",
        "chembl_id": "CHEMBL939",
        "disease_id": "MONDO_0005233",
        "disease_name": "non-small cell lung carcinoma",
        "max_clinical_stage": "APPROVAL",
    },
    {
        "ligand_id": "3316",
        "ligand_name": "gefitinib",
        "chembl_id": "CHEMBL939",
        "disease_id": "MONDO_0005233",
        "disease_name": "non-small cell lung carcinoma",
        "max_clinical_stage": "APPROVAL",
    },
]


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _write_fixture(tmp_path):
    path = tmp_path / "open_targets_drug_indications.json"
    path.write_text(json.dumps(INDICATIONS), encoding="utf-8")
    return path


def _seed_drug(session: Session) -> None:
    import_entities(
        session,
        [
            EntityRecord(
                entity_type="drug",
                name="gefitinib",
                identifiers=(ExternalIdentifier("gtopdb", "3316"),),
            )
        ],
    )


def test_open_targets_indications_adapter_is_registered():
    assert registry.get("open_targets_indications") is OpenTargetsIndicationsAdapter


def test_open_targets_indications_dedupes_disease_entities(tmp_path):
    path = _write_fixture(tmp_path)
    adapter = OpenTargetsIndicationsAdapter(path, release="2026-09-17")

    entities = list(adapter.iter_entities())

    assert len(entities) == 1
    assert entities[0].identifiers == (ExternalIdentifier("mondo", "0005233"),)


def test_open_targets_indications_resolves_drug_and_records_stage(tmp_path):
    path = _write_fixture(tmp_path)
    adapter = OpenTargetsIndicationsAdapter(path, release="2026-09-17")

    with _memory_session() as session:
        _seed_drug(session)
        report = import_adapter(session, adapter)

        drug = session.exec(select(Entity).where(Entity.canonical_id == "gtopdb:3316")).one()
        disease = session.exec(
            select(Entity).where(Entity.canonical_id == "mondo:0005233")
        ).one()
        relation = session.exec(select(Relation)).one()
        evidence = session.exec(select(Evidence)).one()

    assert report.edges_created == 1
    assert relation.subject_id == drug.id
    assert relation.predicate == "indicated_for"
    assert relation.object_id == disease.id

    assert evidence.source == "open_targets_indications"
    assert evidence.source_id == "CHEMBL939:MONDO_0005233"
    context = json.loads(evidence.context)
    assert context["max_clinical_stage"] == "APPROVAL"

    assert evidence.evidence_type == "approved_indication"
    assert evidence.source_type == "curated_database"
    assert evidence.license == "CC0"
    assert evidence.confidence is None


def test_open_targets_indications_reimport_is_idempotent(tmp_path):
    path = _write_fixture(tmp_path)

    with _memory_session() as session:
        _seed_drug(session)
        first = import_adapter(session, OpenTargetsIndicationsAdapter(path, release="2026-09-17"))
        second = import_adapter(session, OpenTargetsIndicationsAdapter(path, release="2026-09-17"))

    assert first.edges_created == 1
    assert second.edges_created == 0
    assert second.evidence_created == 0
