"""Species, type, and duplicate safeguards for identifier resolution."""

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_edges, import_entities
from oncograph.models import Entity, EntityIdentifier, Evidence, Relation
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


@pytest.mark.parametrize("marked_as_self", [False, True])
def test_alternate_identifiers_cannot_create_implicit_self_relation(marked_as_self):
    """Two distinct endpoint identifiers may resolve to the same database entity."""
    with _session() as session:
        import_entities(session, [EntityRecord(
            entity_type="gene", name="EGFR",
            identifiers=(_identifier("hgnc", "HGNC:3236"), _identifier("ncbigene", "1956")),
        )])
        edge = EdgeRecord(
            subject=_identifier("hgnc", "HGNC:3236"),
            object=_identifier("ncbigene", "1956"),
            predicate="ligand_receptor_interaction",
            context={"source_reported_self_interaction": marked_as_self,
                     "source_ligand": "EGFR", "source_receptor": "EGFR"},
        )
        report = import_edges(session, [edge], source_key="audit")
        assert report.edges_skipped == 1
        assert report.edges_created == report.evidence_created == 0
        assert "same entity" in report.errors[0]
        assert session.exec(select(Relation)).all() == []
        assert session.exec(select(Evidence)).all() == []


def test_invalid_self_edge_is_counted_as_skipped():
    """Validation rejections contribute to import skip counts."""
    with _session() as session:
        identifier = _identifier("hgnc", "HGNC:3236")
        report = import_edges(session, [EdgeRecord(
            subject=identifier, object=identifier, predicate="binds",
        )], source_key="audit")
        assert report.edges_skipped == 1
        assert report.edges_created == report.evidence_created == 0
        assert len(report.errors) == 1


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


def test_secondary_alias_cannot_merge_entity_with_conflicting_species():
    """An inconsistent crosswalk must not overwrite an existing organism's entity."""
    with _session() as session:
        mouse = Entity(type="gene", name="SharedName", canonical_id="mgi:MGI:1",
                       entity_metadata='{"taxon_id": 10090}')
        session.add(mouse)
        session.flush()
        session.add(EntityIdentifier(entity_id=mouse.id, namespace="ncbigene", value="1", taxon_id=9606))
        session.commit()
        mouse_id = mouse.id
        report = import_entities(session, [EntityRecord(
            entity_type="gene", name="SharedName",
            identifiers=(_identifier("hgnc", "HGNC:1"), _identifier("ncbigene", "1")),
            metadata={"taxon_id": 9606},
        )])
        assert report.entities_updated == 0
        assert report.entities_created == 1
        assert session.get(Entity, mouse_id).entity_metadata == '{"taxon_id": 10090}'
        assert len(session.exec(select(Entity)).all()) == 2


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
