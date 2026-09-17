"""Issue #6: Drug Response & Experimental Models."""

import json

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_entities
from oncograph.models import Entity, Evidence, Relation
from oncograph.sources.base import EntityRecord, ExternalIdentifier
from oncograph.sources.drug_response import DrugResponseAdapter


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_drug(session: Session) -> None:
    import_entities(
        session,
        [
            EntityRecord(
                entity_type="drug", name="gefitinib", identifiers=(ExternalIdentifier("gtopdb", "4941"),)
            )
        ],
    )


def _write_fixture(tmp_path, records):
    path = tmp_path / "drug_response.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


IC50_RECORD = {
    "drug_namespace": "gtopdb",
    "drug_id": "4941",
    "drug_name": "gefitinib",
    "model_type": "cell_line",
    "model_namespace": "cellosaurus",
    "model_id": "CVCL_0023",
    "model_name": "A549",
    "disease": "lung adenocarcinoma",
    "tissue": "lung",
    "metric_type": "IC50",
    "value": 0.42,
    "unit": "uM",
    "assay": "CellTiter-Glo viability assay",
    "dose": "dose-response",
    "timepoint": "72h",
    "source_dataset": "GDSC2",
    "source_record_id": "gdsc2:gefitinib:A549",
    "source_url": "https://example.org/gdsc2",
}


def test_drug_response_creates_model_entity_and_ic50_edge(tmp_path):
    path = _write_fixture(tmp_path, [IC50_RECORD])
    adapter = DrugResponseAdapter(path, release="2026-09")

    with _memory_session() as session:
        _seed_drug(session)
        report = import_adapter(session, adapter)
        model = session.exec(select(Entity).where(Entity.canonical_id == "cellosaurus:CVCL_0023")).one()
        relation = session.exec(select(Relation)).one()
        evidence = session.exec(select(Evidence)).one()

    assert report.edges_created == 1
    assert model.type == "cell_line"
    assert model.name == "A549"
    assert relation.predicate == "tested_in"
    assert evidence.evidence_type == "drug_response_ic50"
    context = json.loads(evidence.context)
    assert context["value"] == 0.42
    assert context["unit"] == "uM"
    assert context["source_dataset"] == "GDSC2"
    assert evidence.confidence is None  # never coerced from a concentration value


CATEGORICAL_RECORD = {
    "drug_namespace": "gtopdb",
    "drug_id": "4941",
    "model_type": "cohort",
    "model_namespace": "depmap",
    "model_id": "COHORT-1",
    "model_name": "Phase II cohort",
    "metric_type": "PR",
    "qualitative_label": "partial response",
    "source_dataset": "internal_trial",
    "source_record_id": "cohort-1",
}


def test_drug_response_preserves_categorical_metric_without_forcing_numeric(tmp_path):
    path = _write_fixture(tmp_path, [CATEGORICAL_RECORD])
    adapter = DrugResponseAdapter(path)

    with _memory_session() as session:
        _seed_drug(session)
        import_adapter(session, adapter)
        evidence = session.exec(select(Evidence)).one()
        model = session.exec(select(Entity).where(Entity.type == "cohort")).one()

    assert model.canonical_id == "depmap:COHORT-1"
    context = json.loads(evidence.context)
    assert context["metric_type"] == "PR"
    assert context["qualitative_label"] == "partial response"
    assert context["value"] is None
    assert evidence.confidence is None


def test_drug_response_different_metrics_for_same_relation_coexist(tmp_path):
    """IC50 and AUC for the same drug+model land on the same relation as distinct evidence."""
    auc_record = {**IC50_RECORD, "metric_type": "AUC", "value": 0.87, "unit": None, "source_record_id": "auc-1"}
    path = _write_fixture(tmp_path, [IC50_RECORD, auc_record])
    adapter = DrugResponseAdapter(path)

    with _memory_session() as session:
        _seed_drug(session)
        report = import_adapter(session, adapter)
        relations = session.exec(select(Relation)).all()
        evidence_rows = session.exec(select(Evidence)).all()

    assert report.edges_created == 1  # one drug-model relation
    assert len(relations) == 1
    assert len(evidence_rows) == 2  # two distinct, non-comparable measurements
    metrics = {json.loads(e.context)["metric_type"] for e in evidence_rows}
    assert metrics == {"IC50", "AUC"}


def test_drug_response_skips_unknown_model_type_and_metric_type(tmp_path):
    bad_model = {
        **IC50_RECORD,
        "model_type": "not_a_model",
        "model_id": "CVCL_9999",
        "source_record_id": "bad-model",
    }
    bad_metric = {**IC50_RECORD, "metric_type": "NOT_A_METRIC", "source_record_id": "bad-metric"}
    path = _write_fixture(tmp_path, [bad_model, bad_metric])
    adapter = DrugResponseAdapter(path)

    # bad_model's invalid model_type excludes it from entities entirely; bad_metric's
    # model_type is still valid so its model entity is created, but neither row yields
    # an edge (one has an unknown model_type, the other an unknown metric_type).
    entities = list(adapter.iter_entities())
    assert len(entities) == 1
    assert entities[0].identifiers[0].value == "CVCL_0023"
    assert list(adapter.iter_edges()) == []


def test_drug_response_supports_pdx_and_organoid_model_types(tmp_path):
    pdx = {
        **IC50_RECORD,
        "model_type": "pdx",
        "model_namespace": "depmap",
        "model_id": "PDX-1",
        "source_record_id": "pdx-1",
    }
    organoid = {
        **IC50_RECORD,
        "model_type": "organoid",
        "model_namespace": "depmap",
        "model_id": "ORG-1",
        "source_record_id": "organoid-1",
    }
    path = _write_fixture(tmp_path, [pdx, organoid])
    adapter = DrugResponseAdapter(path)

    entity_types = {e.entity_type for e in adapter.iter_entities()}
    assert entity_types == {"pdx", "organoid"}
    assert len(list(adapter.iter_edges())) == 2
