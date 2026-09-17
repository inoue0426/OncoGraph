import json
import sys
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from oncograph.models import Entity, Evidence, Relation

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_static_site


def _seeded_db(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        drug = Entity(type="drug", name="asenapine", canonical_id="gtopdb:22")
        gene = Entity(
            type="gene", name="HTR2A", canonical_id="hgnc:HGNC:5293", description="5-HT2A receptor"
        )
        session.add(drug)
        session.add(gene)
        session.flush()
        relation = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
        session.add(relation)
        session.flush()
        session.add(
            Evidence(
                relation_id=relation.id,
                source="gtopdb",
                source_id="22:6",
                source_url="https://www.guidetopharmacology.org/GRAC/LigandDisplayForward?ligandId=22",
                source_type="curated_database",
                evidence_type="target_interaction",
                license="ODbL (database) / CC BY-SA 4.0 (content)",
                context=json.dumps({"release": "2026.3"}),
            )
        )
        session.commit()


def test_read_entities_returns_empty_list_when_db_missing(tmp_path):
    assert build_static_site.read_entities(tmp_path / "missing.db") == []


def test_read_relations_returns_empty_list_when_db_missing(tmp_path):
    assert build_static_site.read_relations(tmp_path / "missing.db") == []


def test_read_entities_and_relations_round_trip(tmp_path):
    db_path = tmp_path / "oncograph.db"
    _seeded_db(db_path)

    entities = build_static_site.read_entities(db_path)
    relations = build_static_site.read_relations(db_path)

    assert {e["canonical_id"] for e in entities} == {"gtopdb:22", "hgnc:HGNC:5293"}

    drug_id = next(e["id"] for e in entities if e["canonical_id"] == "gtopdb:22")
    gene = next(e for e in entities if e["canonical_id"] == "hgnc:HGNC:5293")
    assert gene["description"] == "5-HT2A receptor"

    assert len(relations) == 1
    assert relations[0]["subject_id"] == drug_id
    assert relations[0]["predicate"] == "targets"
    assert relations[0]["object_id"] == gene["id"]
    assert len(relations[0]["evidence"]) == 1
    evidence = relations[0]["evidence"][0]
    assert evidence["source"] == "gtopdb"
    assert evidence["source_id"] == "22:6"
    assert evidence["context"] == {"release": "2026.3"}
    assert evidence["source_type"] == "curated_database"
    assert evidence["evidence_type"] == "target_interaction"
    assert evidence["license"] == "ODbL (database) / CC BY-SA 4.0 (content)"
    assert evidence["confidence"] is None
