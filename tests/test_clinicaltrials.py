import json

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_entities
from oncograph.models import Entity, Evidence, Relation
from oncograph.sources import registry
from oncograph.sources.base import EntityRecord, ExternalIdentifier
from oncograph.sources.clinicaltrials import ClinicalTrialsAdapter

TRIALS = [
    {
        "ligand_id": "22",
        "ligand_name": "asenapine",
        "nct_id": "NCT00000001",
        "brief_title": "A Study of Asenapine",
        "overall_status": "COMPLETED",
        "phases": ["PHASE2"],
        "conditions": ["Schizophrenia"],
        "matched_intervention": "Asenapine",
    },
    {
        "ligand_id": "22",
        "ligand_name": "asenapine",
        "nct_id": "NCT00000001",
        "brief_title": "A Study of Asenapine",
        "overall_status": "COMPLETED",
        "phases": ["PHASE2"],
        "conditions": ["Schizophrenia"],
        "matched_intervention": "Asenapine",
    },
]


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _write_fixture(tmp_path):
    path = tmp_path / "clinicaltrials_trials.json"
    path.write_text(json.dumps(TRIALS), encoding="utf-8")
    return path


def _seed_drug(session: Session) -> None:
    import_entities(
        session,
        [
            EntityRecord(
                entity_type="drug",
                name="asenapine",
                identifiers=(ExternalIdentifier("gtopdb", "22"),),
            )
        ],
    )


def test_clinicaltrials_adapter_is_registered():
    assert registry.get("clinicaltrials_gov") is ClinicalTrialsAdapter


def test_clinicaltrials_dedupes_trial_entities_by_nct_id(tmp_path):
    path = _write_fixture(tmp_path)
    adapter = ClinicalTrialsAdapter(path, release="2026-09-17")

    entities = list(adapter.iter_entities())

    assert len(entities) == 1
    assert entities[0].name == "A Study of Asenapine"
    assert entities[0].identifiers == (ExternalIdentifier("clinicaltrials.gov", "NCT00000001"),)
    assert entities[0].description == "Schizophrenia"


def test_clinicaltrials_resolves_drug_by_gtopdb_id_and_records_evidence(tmp_path):
    path = _write_fixture(tmp_path)
    adapter = ClinicalTrialsAdapter(path, release="2026-09-17")

    with _memory_session() as session:
        _seed_drug(session)
        report = import_adapter(session, adapter)

        drug = session.exec(select(Entity).where(Entity.canonical_id == "gtopdb:22")).one()
        trial = session.exec(
            select(Entity).where(Entity.canonical_id == "clinicaltrials.gov:NCT00000001")
        ).one()
        relation = session.exec(select(Relation)).one()
        evidence = session.exec(select(Evidence)).one()

    assert report.edges_created == 1
    assert report.edges_skipped == 0
    assert relation.subject_id == drug.id
    assert relation.predicate == "studied_in"
    assert relation.object_id == trial.id

    assert evidence.source == "clinicaltrials_gov"
    assert evidence.source_url == "https://clinicaltrials.gov/study/NCT00000001"
    context = json.loads(evidence.context)
    assert context["overall_status"] == "COMPLETED"
    assert context["phases"] == ["PHASE2"]


def test_clinicaltrials_reimport_is_idempotent(tmp_path):
    path = _write_fixture(tmp_path)

    with _memory_session() as session:
        _seed_drug(session)
        first = import_adapter(session, ClinicalTrialsAdapter(path, release="2026-09-17"))
        second = import_adapter(session, ClinicalTrialsAdapter(path, release="2026-09-17"))

    assert first.edges_created == 1
    assert second.edges_created == 0
    assert second.evidence_created == 0
