"""Species, type, and duplicate safeguards for identifier resolution."""

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_edges, import_entities
from oncograph.models import Entity, EntityIdentifier, Relation
from oncograph.sources.base import EdgeRecord, EntityRecord, ExternalIdentifier


def _identifier(namespace: str, value: str) -> ExternalIdentifier:
    return ExternalIdentifier(namespace, value)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_unique_alternate_id_change_is_reported_as_possible_duplicate():
    with _session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="gene",
                    name="EGFR",
                    identifiers=(_identifier("hgnc", "HGNC:3236"), _identifier("ncbigene", "1956")),
                ),
                EntityRecord(
                    entity_type="gene",
                    name="ERBB1",
                    identifiers=(_identifier("ensembl", "ENSG00000146648"), _identifier("ncbigene", "1956")),
                ),
            ],
        )
        entities = session.exec(select(Entity)).all()

    assert len(entities) == 2


def test_alternate_uniprot_id_does_not_resolve_gene_entity():
    with _session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="gene",
                    name="GeneWithBadXref",
                    identifiers=(_identifier("hgnc", "HGNC:1"), _identifier("uniprot", "P00533")),
                ),
                EntityRecord(
                    entity_type="drug",
                    name="Drug",
                    identifiers=(_identifier("chembl", "CHEMBL1"),),
                ),
            ],
        )
        report = import_edges(
            session,
            [
                EdgeRecord(
                    subject=_identifier("chembl", "CHEMBL1"),
                    predicate="binds",
                    object=_identifier("uniprot", "P00533"),
                )
            ],
            source_key="audit",
        )

    assert report.edges_skipped == 1
    assert not session.exec(select(Relation)).all()


def test_explicit_species_does_not_cross_resolve_unknown_species_claim():
    with _session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="gene",
                    name="HumanGene",
                    identifiers=(_identifier("hgnc", "HGNC:1"), _identifier("ensembl", "ENSG_SHARED")),
                ),
                EntityRecord(
                    entity_type="gene",
                    name="MouseGene",
                    identifiers=(_identifier("ensembl", "ENSMUSG_SHARED"),),
                    metadata={"taxon_id": 10090},
                ),
            ],
        )
        rows = session.exec(select(EntityIdentifier)).all()
        assert {row.taxon_id for row in rows if row.value == "ENSG_SHARED"} == {9606}

        report = import_edges(
            session,
            [
                EdgeRecord(
                    subject=_identifier("hgnc", "HGNC:1"),
                    predicate="related_to",
                    object=_identifier("ensembl", "ENSG_SHARED"),
                    metadata={"taxon_id": 10090},
                )
            ],
            source_key="audit",
        )

    assert report.edges_skipped == 1
