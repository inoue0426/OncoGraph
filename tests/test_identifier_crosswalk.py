"""Identifier-crosswalk tests: no names used as keys; ambiguous aliases never guess."""
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_edges, import_entities
from oncograph.models import Entity, EntityIdentifier, Evidence
from oncograph.sources.base import EdgeRecord, EntityRecord, ExternalIdentifier


def eid(namespace, value):
    return ExternalIdentifier(namespace, value)


def test_hgnc_secondary_ids_resolve_edges_and_reimport_is_idempotent():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    gene = EntityRecord(
        entity_type="gene", name="EGFR",
        identifiers=(eid("hgnc", "HGNC:3236"), eid("ncbigene", "1956"),
                     eid("ensembl", "ENSG00000146648")),
    )
    drug = EntityRecord(
        entity_type="drug", name="ExampleDrug",
        identifiers=(eid("chembl", "CHEMBL1"),),
    )
    with Session(engine) as session:
        import_entities(session, [gene, drug])
        import_entities(session, [gene])
        assert len(session.exec(select(Entity)).all()) == 2
        assert len(session.exec(select(EntityIdentifier)).all()) == 4
        report = import_edges(
            session,
            [EdgeRecord(subject=eid("chembl", "CHEMBL1"),
                        predicate="targets", object=eid("ncbigene", "1956"),
                        source_record_id="test-1")],
            source_key="test",
        )
        assert report.edges_created == 1
        assert len(session.exec(select(Evidence)).all()) == 1


def test_species_namespace_and_conflicting_alt_id_do_not_silent_merge():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = EntityRecord(
            entity_type="gene", name="GeneA",
            identifiers=(eid("hgnc", "HGNC:10"), eid("ensembl", "ENSG_SHARED")),
        )
        second = EntityRecord(
            entity_type="gene", name="GeneB",
            identifiers=(eid("hgnc", "HGNC:20"), eid("ensembl", "ENSG_SHARED")),
        )
        import_entities(session, [first])
        report = import_entities(session, [second])
        assert report.entities_conflicted == 1
        assert len(session.exec(select(Entity)).all()) == 2
        # Both claims remain recorded, so resolution is ambiguous regardless
        # of import order and never silently picks the first importer.
        matches = session.exec(
            select(EntityIdentifier).where(EntityIdentifier.value == "ENSG_SHARED")
        ).all()
        assert len(matches) == 2
        assert matches[0].taxon_id == 9606


def test_alias_collision_with_canonical_id_is_not_attached():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        import_entities(session, [
            EntityRecord(entity_type="gene", name="GeneA", identifiers=(eid("hgnc", "HGNC:1"),)),
            EntityRecord(entity_type="gene", name="GeneB", identifiers=(eid("hgnc", "HGNC:2"), eid("hgnc", "HGNC:1"))),
        ])
        aliases = session.exec(select(EntityIdentifier)).all()
        assert {(row.entity_id, row.namespace, row.value) for row in aliases} == {
            (session.exec(select(Entity).where(Entity.canonical_id == "hgnc:HGNC:1")).one().id, "hgnc", "HGNC:1"),
            (session.exec(select(Entity).where(Entity.canonical_id == "hgnc:HGNC:2")).one().id, "hgnc", "HGNC:2"),
        }


def test_existing_sqlite_database_gets_crosswalk_table(monkeypatch):
    from oncograph import db

    engine = create_engine("sqlite://")
    Entity.__table__.create(engine)
    monkeypatch.setattr(db, "engine", engine)
    db.create_db_and_tables()
    assert EntityIdentifier.__tablename__ in SQLModel.metadata.tables
    with engine.connect() as connection:
        assert connection.dialect.has_table(connection, "entityidentifier")


def test_species_and_gene_protein_ambiguity_require_explicit_resolution():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        import_entities(session, [
            EntityRecord(
                entity_type="gene", name="HumanGene",
                identifiers=(eid("hgnc", "HGNC:100"), eid("ensembl", "ENSG_SHARED")),
            ),
            EntityRecord(
                entity_type="gene", name="MouseGene",
                identifiers=(eid("mgi", "MGI:100"), eid("ensembl", "ENSG_SHARED")),
            ),
            EntityRecord(
                entity_type="protein", name="ProteinProduct",
                identifiers=(eid("uniprot", "P00002"), eid("uniprot", "P00001")),
            ),
            EntityRecord(
                entity_type="gene", name="ProteinGene",
                identifiers=(eid("hgnc", "HGNC:101"), eid("uniprot", "P00001")),
            ),
            EntityRecord(entity_type="drug", name="Drug", identifiers=(eid("chembl", "CHEMBL1"),)),
        ])
        ambiguous = import_edges(
            session,
            [EdgeRecord(subject=eid("chembl", "CHEMBL1"), predicate="targets", object=eid("ensembl", "ENSG_SHARED"))],
            source_key="test",
        )
        assert ambiguous.edges_skipped == 1
        human = import_edges(
            session,
            [EdgeRecord(
                subject=eid("chembl", "CHEMBL1"), predicate="targets",
                object=eid("ensembl", "ENSG_SHARED"), metadata={"taxon_id": 9606},
            )],
            source_key="test",
        )
        assert human.edges_created == 1
        protein_ambiguous = import_edges(
            session,
            [EdgeRecord(subject=eid("chembl", "CHEMBL1"), predicate="binds", object=eid("uniprot", "P00001"))],
            source_key="test",
        )
        assert protein_ambiguous.edges_skipped == 1
