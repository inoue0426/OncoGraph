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
        # A conflicting secondary ID is rejected, never attached to GeneB.
        matches = session.exec(
            select(EntityIdentifier).where(EntityIdentifier.value == "ENSG_SHARED")
        ).all()
        assert len(matches) == 1
        assert matches[0].taxon_id == 9606
