import json

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_edges, import_entities, validate_edge
from oncograph.models import Entity, Evidence
from oncograph.normalization import normalize_identifier
from oncograph.sources import registry
from oncograph.sources.base import EdgeRecord, EntityRecord, ExternalIdentifier
from oncograph.sources.gene_ontology import GeneOntologyAdapter
from oncograph.sources.hgnc import HGNCAdapter


def test_identifier_normalization():
    result = normalize_identifier(ExternalIdentifier("NCT", "nct01234567"))
    assert result.namespace == "clinicaltrials.gov"
    assert result.value == "NCT01234567"


def test_edge_validation():
    edge = EdgeRecord(
        subject=ExternalIdentifier("drugbank", "DB0001"),
        predicate="targets",
        object=ExternalIdentifier("hgnc", "EGFR"),
        source_record_id="example",
    )
    validate_edge(edge)


def test_adapters_are_registered():
    assert registry.get("hgnc") is HGNCAdapter
    assert registry.get("gene_ontology") is GeneOntologyAdapter


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_import_entities_is_idempotent_by_canonical_id():
    records = [
        EntityRecord(
            entity_type="gene",
            name="EGFR",
            identifiers=(ExternalIdentifier("hgnc", "HGNC:3236"),),
        )
    ]
    with _memory_session() as session:
        first = import_entities(session, records)
        second = import_entities(session, records)

    assert first.entities_created == 1
    assert first.entities_updated == 0
    assert second.entities_created == 0
    assert second.entities_updated == 1


def test_import_edges_skips_unresolved_endpoints():
    edge = EdgeRecord(
        subject=ExternalIdentifier("hgnc", "HGNC:1"),
        predicate="targets",
        object=ExternalIdentifier("hgnc", "HGNC:2"),
    )
    with _memory_session() as session:
        report = import_edges(session, [edge], source_key="hgnc")
    assert report.edges_created == 0
    assert report.edges_skipped == 1


def test_import_adapter_persists_hgnc_and_go_data(tmp_path):
    hgnc_path = tmp_path / "hgnc_complete_set.txt"
    hgnc_path.write_text(
        "hgnc_id\tsymbol\tname\tentrez_id\tensembl_gene_id\tuniprot_ids\n"
        "HGNC:3236\tEGFR\tepidermal growth factor receptor\t1956\tENSG00000146648\tP00533\n",
        encoding="utf-8",
    )
    obo_path = tmp_path / "go-basic.obo"
    obo_path.write_text(
        "format-version: 1.2\n"
        "\n"
        "[Term]\n"
        "id: GO:0000001\n"
        "name: mitochondrion inheritance\n"
        "namespace: biological_process\n"
        "\n"
        "[Term]\n"
        "id: GO:0000002\n"
        "name: mitochondrial genome maintenance\n"
        "namespace: biological_process\n"
        "is_a: GO:0000001 ! mitochondrion inheritance\n",
        encoding="utf-8",
    )

    with _memory_session() as session:
        hgnc_report = import_adapter(session, HGNCAdapter(hgnc_path, release="2024-01"))
        go_report = import_adapter(session, GeneOntologyAdapter(obo_path, release="2024-01-01"))
        genes = session.exec(select(Entity).where(Entity.type == "gene")).all()
        terms = session.exec(select(Entity).where(Entity.type == "go_term")).all()

    assert hgnc_report.entities_created == 1
    assert hgnc_report.errors == []
    assert go_report.entities_created == 2
    assert go_report.edges_created == 1
    assert go_report.evidence_created == 1
    assert go_report.errors == []
    assert [g.canonical_id for g in genes] == ["hgnc:HGNC:3236"]
    assert {t.canonical_id for t in terms} == {"go:GO:0000001", "go:GO:0000002"}


def test_repeated_go_edge_import_preserves_provenance_idempotently(tmp_path):
    obo_path = tmp_path / "go-basic.obo"
    obo_path.write_text(
        "format-version: 1.2\n"
        "\n"
        "[Term]\n"
        "id: GO:0000001\n"
        "name: mitochondrion inheritance\n"
        "namespace: biological_process\n"
        "\n"
        "[Term]\n"
        "id: GO:0000002\n"
        "name: mitochondrial genome maintenance\n"
        "namespace: biological_process\n"
        "is_a: GO:0000001 ! mitochondrion inheritance\n",
        encoding="utf-8",
    )

    with _memory_session() as session:
        adapter = GeneOntologyAdapter(obo_path, release="2024-01-01")
        first = import_adapter(session, adapter)
        second = import_adapter(session, GeneOntologyAdapter(obo_path, release="2024-01-01"))
        evidence_rows = session.exec(select(Evidence)).all()

    assert first.edges_created == 1
    assert first.evidence_created == 1
    assert second.edges_created == 0
    assert second.evidence_created == 0

    assert len(evidence_rows) == 1
    evidence = evidence_rows[0]
    assert evidence.source == "gene_ontology"
    assert evidence.source_id == "GO:0000002"
    assert evidence.extraction_method == "adapter_import"
    assert json.loads(evidence.context) == {"release": "2024-01-01"}
