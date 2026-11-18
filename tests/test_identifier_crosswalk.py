"""Identifier-crosswalk tests: no names used as keys; ambiguous aliases never guess."""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_edges, import_entities
from oncograph.models import Entity, EntityIdentifier, Evidence, Relation
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


@pytest.mark.parametrize("namespace,prefix,taxon", [("hgnc", "HGNC:", 9606), ("mgi", "MGI:", 10090)])
def test_legacy_sqlite_records_survive_schema_initialization_and_reimport(tmp_path, monkeypatch, namespace, prefix, taxon):
    """Initializing an old graph preserves identities, relations, and evidence."""
    from oncograph import db

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    # These three table layouts match the pre-crosswalk schema.
    for model in (Entity, Relation, Evidence):
        model.__table__.create(engine)
    identifiers = [eid(namespace, f"{prefix}{index}") for index in (1, 2)]
    with Session(engine) as session:
        entities = [Entity(type="gene", name=f"Gene{index}", canonical_id=f"{namespace}:{prefix}{index}")
                    for index in (1, 2)]
        session.add_all(entities)
        session.flush()
        relation = Relation(subject_id=entities[0].id, object_id=entities[1].id, predicate="regulates")
        session.add(relation)
        session.flush()
        evidence = Evidence(relation_id=relation.id, source="legacy", source_id="old-record", context='{"original": true}')
        session.add(evidence)
        session.commit()
        original_ids = [entity.id for entity in entities]
        original_relation_id, original_evidence_id = relation.id, evidence.id
    monkeypatch.setattr(db, "engine", engine)
    db.create_db_and_tables()
    db.create_db_and_tables()
    with Session(engine) as session:
        edge = EdgeRecord(subject=identifiers[0], object=identifiers[1], predicate="regulates",
                          source_record_id="new-record", metadata={"taxon_id": taxon})
        report = import_edges(session, [edge], source_key="new-source")
        assert report.errors == []
        assert report.edges_created == 0
        assert report.evidence_created == 1
        records = [EntityRecord(entity_type="gene", name=f"Gene{index}", identifiers=(identifier,))
                   for index, identifier in enumerate(identifiers, start=1)]
        for _ in range(2):
            report = import_entities(session, records)
            assert report.errors == []
            assert report.entities_created == 0
        assert {entity.id for entity in session.exec(select(Entity)).all()} == set(original_ids)
        assert session.exec(select(Relation)).one().id == original_relation_id
        assert session.get(Evidence, original_evidence_id).context == '{"original": true}'
        assert len(session.exec(select(EntityIdentifier)).all()) == 2
        assert len(session.exec(select(Evidence)).all()) == 2
        assert import_edges(session, [edge], source_key="new-source").evidence_created == 0
    engine.dispose()


@pytest.mark.parametrize("namespace,value,taxon,metadata,claimed_taxa", [
    ("hgnc", "HGNC:1", 10090, None, []),
    ("ensembl", "ENSG000001", 9606, None, []),
    ("hgnc", "HGNC:1", 9606, '{"taxon_id": 10090}', []),
    ("hgnc", "HGNC:1", 9606, '{"taxon_id": 10090}', [9606]),
    ("hgnc", "HGNC:1", 9606, None, [10090]),
    ("hgnc", "HGNC:1", 9606, None, [9606, 10090]),
])
def test_legacy_taxon_fallback_never_overrides_conflicting_or_unknown_species(namespace, value, taxon, metadata, claimed_taxa):
    """Namespace inference cannot clear unknown namespaces or conflicting species claims."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        entity = Entity(type="gene", name="Legacy", canonical_id=f"{namespace}:{value}", entity_metadata=metadata)
        partner = Entity(type="gene", name="Partner", canonical_id="hgnc:HGNC:2")
        session.add_all([entity, partner])
        session.flush()
        for claimed_taxon in claimed_taxa:
            session.add(EntityIdentifier(entity_id=entity.id, namespace=namespace, value=value,
                                         taxon_id=claimed_taxon))
        session.commit()
        report = import_edges(session, [EdgeRecord(
            subject=eid(namespace, value), object=eid("hgnc", "HGNC:2"),
            predicate="regulates", metadata={"taxon_id": taxon},
        )], source_key="audit")
        assert report.edges_skipped == 1
        assert report.edges_created == report.evidence_created == 0
        assert session.exec(select(Relation)).all() == []
    engine.dispose()


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
