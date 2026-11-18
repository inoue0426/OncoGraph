"""Focused tests for the permission-gated, human Lewis Lab adapters."""

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter
from oncograph.models import Entity, Evidence, Relation
from oncograph.sources.base import ExternalIdentifier
from oncograph.sources.lewis_lab import (
    HUMAN_TAXON,
    LewisCabelloAguilarAdapter,
    LewisDelimitedAdapter,
    LewisRamilowskiAdapter,
    LewisResolvedIdentifier,
    LewisSourceProfile,
)


def _map(*rows):
    return {(HUMAN_TAXON, symbol): (LewisResolvedIdentifier(identifier, entity_type),)
            for symbol, identifier, entity_type in rows}


def test_ramilowski_parser_requires_explicit_human_symbol_map(tmp_path):
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    path.write_text(
        "Pair.Name\tLigand.ApprovedSymbol\tLigand.Name\tReceptor.ApprovedSymbol\t"
        "Receptor.Name\tPMID.Manual\tPair.Evidence\n"
        "A2M_LRP1\tA2M\talpha-2-macroglobulin\tLRP1\tLRP1\t16630822\tliterature supported\n"
        "A2M_LRP1\tA2M\talpha-2-macroglobulin\tLRP1\tLRP1\t16630822\tliterature supported\n"
        "BAD\tUNKNOWN\tunknown\tLRP1\tLRP1\t\t\n",
        encoding="utf-8",
    )
    adapter = LewisRamilowskiAdapter(
        path,
        _map(
            ("A2M", ExternalIdentifier("hgnc", "HGNC:7"), "gene"),
            ("LRP1", ExternalIdentifier("hgnc", "HGNC:6692"), "gene"),
        ),
        release="audit-fixture",
    )
    edges = list(adapter.iter_edges())
    report = adapter.validation_report()
    assert len(edges) == 1
    assert report.input_rows == 3
    assert report.duplicate_rows == 1
    assert report.unresolved_identifiers == 1
    assert report.unresolved_values == ["UNKNOWN"]
    assert edges[0].source_record_id == "lewis_ramilowski_2015:A2M_LRP1"
    assert edges[0].context["taxon_id"] == HUMAN_TAXON


def test_cabello_parser_preserves_source_evidence(tmp_path):
    path = tmp_path / "Human-2020-Cabello-Aguilar-LR-pairs.csv"
    path.write_text(
        "ligand,receptor,sources,pmid\nTGFB1,TGFBR1,HPRD,12809600\n",
        encoding="utf-8",
    )
    adapter = LewisCabelloAguilarAdapter(
        path,
        _map(
            ("TGFB1", ExternalIdentifier("hgnc", "HGNC:11766"), "gene"),
            ("TGFBR1", ExternalIdentifier("hgnc", "HGNC:11772"), "gene"),
        ),
    )
    edge = next(adapter.iter_edges())
    assert edge.context["source_evidence"] == "HPRD"
    assert edge.context["citation"] == "12809600"


def test_complex_and_metabolite_rows_are_not_split_or_inferred(tmp_path):
    path = tmp_path / "fixture.tsv"
    path.write_text(
        "ligand\treceptor\tligand_kind\treceptor_kind\n"
        "COL1A1|COL1A2\tITGB1\tprotein\tprotein\n"
        "ATP\tP2RY2\tmetabolite\tprotein\n",
        encoding="utf-8",
    )
    fixture_profile = LewisSourceProfile(
        source_key="test_complex_metabolite",
        filename=path.name,
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="\t",
        ligand_column="ligand",
        receptor_column="receptor",
        ligand_kind_column="ligand_kind",
        receptor_kind_column="receptor_kind",
        complex_separator="|",
    )
    class FixtureAdapter(LewisDelimitedAdapter):
        profile = fixture_profile

    adapter = FixtureAdapter(
        path,
        _map(
            ("COL1A1", ExternalIdentifier("hgnc", "HGNC:2197"), "gene"),
            ("COL1A2", ExternalIdentifier("hgnc", "HGNC:2198"), "gene"),
            ("ITGB1", ExternalIdentifier("hgnc", "HGNC:6153"), "gene"),
            ("ATP", ExternalIdentifier("chebi", "CHEBI:15422"), "metabolite"),
            ("P2RY2", ExternalIdentifier("hgnc", "HGNC:8541"), "gene"),
        ),
    )
    entities = list(adapter.iter_entities())
    edges = list(adapter.iter_edges())
    assert any(entity.entity_type == "molecular_complex" for entity in entities)
    assert any(entity.entity_type == "metabolite" for entity in entities)
    assert sum(edge.predicate == "has_subunit" for edge in edges) == 2
    assert sum(edge.predicate == "ligand_receptor_interaction" for edge in edges) == 2
    assert all(edge.predicate != "ligand_receptor_interaction" or "COL1A1" not in edge.subject.value for edge in edges)


def test_import_is_idempotent_and_preserves_each_source_evidence(tmp_path):
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    path.write_text(
        "Pair.Name\tLigand.ApprovedSymbol\tReceptor.ApprovedSymbol\n"
        "A2M_LRP1\tA2M\tLRP1\n",
        encoding="utf-8",
    )
    adapter = LewisRamilowskiAdapter(
        path,
        _map(
            ("A2M", ExternalIdentifier("hgnc", "HGNC:7"), "gene"),
            ("LRP1", ExternalIdentifier("hgnc", "HGNC:6692"), "gene"),
        ),
    )
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = import_adapter(session, adapter)
        second = import_adapter(session, adapter)
        assert first.edges_created == 1
        assert second.edges_created == 0
        assert second.evidence_created == 0
        assert len(session.exec(select(Entity)).all()) == 2
        assert len(session.exec(select(Relation)).all()) == 1
        assert len(session.exec(select(Evidence)).all()) == 1
