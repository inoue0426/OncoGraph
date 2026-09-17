import json

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_entities
from oncograph.models import Entity, Evidence, Relation
from oncograph.sources import registry
from oncograph.sources.base import EntityRecord, ExternalIdentifier
from oncograph.sources.gtopdb import GtoPdbAdapter

INTERACTIONS_CSV = (
    '"# GtoPdb Version: 2026.3 - published: 2026-09-16"\n'
    '"Ligand","Ligand ID","Target","Target ID","Target Ligand","Target Ligand ID",'
    '"Target Species","Type"\n'
    '"asenapine","22","5-HT<sub>2A</sub> receptor","6",,"0","Human","Synthetic organic"\n'
    '"asenapine","22","Unmapped rat target","999",,"0","Rat","Synthetic organic"\n'
)

HGNC_MAPPING_CSV = (
    '"# GtoPdb Version: 2026.3 - published: 2026-09-16"\n'
    '"HGNC Symbol","HGNC ID","IUPHAR Name","IUPHAR ID","GtP URL"\n'
    '"HTR2A","5293","5-HT<sub>2A</sub> receptor","6",'
    '"https://www.guidetopharmacology.org/GRAC/ObjectDisplayForward?objectId=6"\n'
)


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _write_fixtures(tmp_path):
    interactions_path = tmp_path / "gtopdb_approved_drug_primary_target_interactions.csv"
    interactions_path.write_text(INTERACTIONS_CSV, encoding="utf-8")
    mapping_path = tmp_path / "gtopdb_hgnc_mapping.csv"
    mapping_path.write_text(HGNC_MAPPING_CSV, encoding="utf-8")
    return interactions_path, mapping_path


def _seed_htr2a_gene(session: Session) -> None:
    import_entities(
        session,
        [
            EntityRecord(
                entity_type="gene",
                name="HTR2A",
                identifiers=(ExternalIdentifier("hgnc", "HGNC:5293"),),
            )
        ],
    )


def test_gtopdb_adapter_is_registered():
    assert registry.get("gtopdb") is GtoPdbAdapter


def test_gtopdb_skips_targets_without_official_hgnc_mapping(tmp_path):
    interactions_path, mapping_path = _write_fixtures(tmp_path)
    adapter = GtoPdbAdapter(interactions_path, mapping_path, release="2026.3")

    edges = list(adapter.iter_edges())

    assert len(edges) == 1
    assert edges[0].object == ExternalIdentifier("hgnc", "HGNC:5293")


def test_gtopdb_imports_drug_entity_with_stable_canonical_id(tmp_path):
    interactions_path, mapping_path = _write_fixtures(tmp_path)
    adapter = GtoPdbAdapter(interactions_path, mapping_path, release="2026.3")

    with _memory_session() as session:
        report = import_adapter(session, adapter)
        drugs = session.exec(select(Entity).where(Entity.type == "drug")).all()

    assert report.entities_created == 1
    assert [d.canonical_id for d in drugs] == ["gtopdb:22"]
    assert drugs[0].name == "asenapine"


def test_gtopdb_resolves_target_by_hgnc_id_and_records_evidence(tmp_path):
    interactions_path, mapping_path = _write_fixtures(tmp_path)
    adapter = GtoPdbAdapter(interactions_path, mapping_path, release="2026.3")

    with _memory_session() as session:
        _seed_htr2a_gene(session)
        report = import_adapter(session, adapter)

        drug = session.exec(select(Entity).where(Entity.canonical_id == "gtopdb:22")).one()
        gene = session.exec(select(Entity).where(Entity.canonical_id == "hgnc:HGNC:5293")).one()
        relation = session.exec(select(Relation)).one()
        evidence = session.exec(select(Evidence)).one()

    assert report.edges_created == 1
    assert report.edges_skipped == 0
    assert relation.subject_id == drug.id
    assert relation.predicate == "targets"
    assert relation.object_id == gene.id

    assert evidence.source == "gtopdb"
    assert evidence.source_id == "22:6"
    assert evidence.source_url == (
        "https://www.guidetopharmacology.org/GRAC/LigandDisplayForward?ligandId=22"
    )
    context = json.loads(evidence.context)
    assert context["release"] == "2026.3"
    assert context["target_name"] == "5-HT2A receptor"

    assert evidence.evidence_type == "target_interaction"
    assert evidence.source_type == "curated_database"
    assert evidence.license == "ODbL (database) / CC BY-SA 4.0 (content)"
    assert evidence.confidence is None


def test_gtopdb_reimport_is_idempotent(tmp_path):
    interactions_path, mapping_path = _write_fixtures(tmp_path)

    with _memory_session() as session:
        _seed_htr2a_gene(session)
        first = import_adapter(session, GtoPdbAdapter(interactions_path, mapping_path, release="2026.3"))
        second = import_adapter(session, GtoPdbAdapter(interactions_path, mapping_path, release="2026.3"))

        drugs = session.exec(select(Entity).where(Entity.type == "drug")).all()
        relations = session.exec(select(Relation)).all()
        evidence_rows = session.exec(select(Evidence)).all()

    assert first.entities_created == 1
    assert first.edges_created == 1
    assert first.evidence_created == 1

    assert second.entities_created == 0
    assert second.entities_updated == 1
    assert second.edges_created == 0
    assert second.evidence_created == 0

    assert len(drugs) == 1
    assert len(relations) == 1
    assert len(evidence_rows) == 1
