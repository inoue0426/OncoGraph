"""Scientific identity, polarity, provenance and idempotency regression tests."""

import csv
import json

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.models import Entity, EntityIdentifier, Evidence, Relation
from oncograph.signed_molecular import (
    SIGNED_RELATIONS,
    SignedImportReport,
    TypedCrosswalk,
    import_signed_observations,
)
from oncograph.sources.base import EdgeRecord, EntityRecord, ExternalIdentifier
from oncograph.sources.sigma_sources import (
    LINCS_DESCRIPTOR,
    GtoPdbSignedAdapter,
    LincsConsensusAdapter,
    lincs_compound_mapping,
)


def eid(namespace, value):
    return ExternalIdentifier(namespace, value)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def identities(session):
    crosswalk = TypedCrosswalk(session)
    crosswalk.register(
        [
            EntityRecord("drug", "Drug", (eid("chembl", "CHEMBL1"), eid("pubchem", "1"))),
            EntityRecord(
                "gene",
                "Gene",
                (eid("hgnc", "HGNC:2"), eid("ncbigene", "2"), eid("ensembl", "ENSG2")),
                metadata={"taxon_id": 9606},
            ),
            EntityRecord(
                "protein", "Protein", (eid("uniprot", "P00002"),), metadata={"taxon_id": 9606}
            ),
            EntityRecord("disease", "Disease", (eid("mondo", "0000001"),)),
        ]
    )
    return crosswalk


def observation(predicate="upregulates", context=None):
    spec = SIGNED_RELATIONS[predicate]
    endpoints = {
        "drug": eid("pubchem", "1"),
        "gene": eid("ncbigene", "2"),
        "protein": eid("uniprot", "P00002"),
        "disease": eid("mondo", "0000001"),
    }
    return EdgeRecord(
        endpoints[spec[0]],
        predicate,
        endpoints[spec[1]],
        source_record_id="row-1",
        context={
            "original_source_dataset": "synthetic test",
            "release": "test-v1",
            "file_sha256": "test-digest",
            "original_predicate": predicate,
            "effect_sign": spec[2],
            "biological_relationship": spec[3],
            "observation_status": "transformed",
            "model_generated": False,
            "taxon_id": 9606,
            **(context or {}),
        },
    )


def ingest(session, crosswalk, records):
    return import_signed_observations(
        session, records, LINCS_DESCRIPTOR, crosswalk, SignedImportReport()
    )


def test_lincs_parser_preserves_original_row_sign_and_scope(tmp_path):
    path = tmp_path / "edges.tsv"
    path.write_text(
        "\tGene\tGene ID\tChemical Perturbation\tZ-score\tThreshold Value\n"
        "0\tG\t2\tBRD-1\t3.5\t1\n"
        "1\tG\t2\tBRD-1\t-4.2\t-1\n"
        "2\tG\t2\tambiguous\t4\t1\n"
        "3\tG\t2\tmissing\t4\t1\n"
        "4\tG\t2\tBRD-1\tNaN\t1\n"
        "5\tG\t3\tBRD-1\t4\t1\n"
        "6\tG\t2\tBRD-1\t4\t-1\n"
    )
    adapter = LincsConsensusAdapter(
        path,
        {"BRD-1": {"1"}, "ambiguous": {"1", "2"}},
        release="fixture",
        mapping_sha256="test",
        gene_ids={"2"},
    )
    edges = list(adapter.iter_edges())
    assert [e.predicate for e in edges] == ["upregulates", "downregulates"]
    assert edges[0].subject == eid("pubchem", "1")
    assert edges[0].object == eid("ncbigene", "2")
    assert edges[0].context["original_score"] == 3.5
    assert edges[0].context["experimental_context"] is None
    assert edges[0].source_record_id == "0"
    assert adapter.report.input_records == 7
    assert adapter.report.parsed_records == 5
    assert sum(adapter.report.skipped.values()) == 5
    assert adapter.mapping_diagnostics["ambiguous"]["status"] == "ambiguous"


def test_lincs_metadata_does_not_pick_first_cid(tmp_path):
    path = tmp_path / "metadata.tsv"
    path.write_text(
        "pert_id\tpert_iname\tpert_type\tpubchem_cid\n"
        "BRD-1\tshared\ttrt_cp\t1\n"
        "BRD-2\tshared\ttrt_cp\t2\n"
        "BRD-3\tunknown\ttrt_cp\t-666\n"
        "BRD-4\tprotein\ttrt_oe\t3\n"
    )
    mapping, entities = lincs_compound_mapping(path)
    assert mapping["shared"] == {"1", "2"}
    assert mapping["BRD-1"] == {"1"}
    assert "unknown" not in mapping and "protein" not in mapping
    assert len(entities) == 2


def test_gtopdb_function_binding_and_complex_are_distinct(tmp_path):
    path = tmp_path / "interactions.csv"
    base = {
        "Target Species": "Human",
        "Action": "Inhibition",
        "Ligand ID": "1",
        "Target UniProt ID": "P00002",
        "Target Subunit IDs": "",
        "Type": "Inhibitor",
        "Ligand Type": "Synthetic organic",
        "Assay Description": "source assay",
        "Ligand Context": "",
        "Action comment": "",
        "PubMed ID": "123",
        "Affinity Median": "6.5",
        "Affinity Units": "pIC50",
    }
    rows = [
        base,
        {**base, "Action": "Activation"},
        {**base, "Action": "Binding"},
        {**base, "Target Species": "Mouse"},
        {**base, "Target Subunit IDs": "1|2"},
        {**base, "Action": "Partial agonist"},
    ]
    with path.open("w") as handle:
        handle.write('"# GtoPdb Version: fixture"\n')
        writer = csv.DictWriter(handle, fieldnames=list(base))
        writer.writeheader()
        writer.writerows(rows)
    adapter = GtoPdbSignedAdapter(path)
    edges = list(adapter.iter_edges())
    assert [e.predicate for e in edges] == ["inhibits", "activates"]
    assert edges[0].context["original_row"]["Affinity Median"] == "6.5"
    assert edges[0].context["source_native_record_id"] is None
    assert edges[0].context["experimental_context"] == {"Assay Description": "source assay"}
    assert adapter.report.input_records == 6
    assert sum(adapter.report.skipped.values()) == 4


def test_missing_header_fails_loudly(tmp_path):
    path = tmp_path / "invalid.tsv"
    path.write_text("drug\tgene\nA\tB\n")
    adapter = LincsConsensusAdapter(path, {}, release="test", mapping_sha256="test")
    with pytest.raises(ValueError, match="schema"):
        list(adapter.iter_edges())


def test_source_asserted_multivalue_identity_is_rejected(session):
    record = EntityRecord(
        "drug",
        "Ambiguous salt",
        (eid("gtopdb", "1"),),
        metadata={"identifier_mapping_conflicts": {"PubChem CID": "1|2"}},
    )
    index = TypedCrosswalk(session)
    assert index.register([record])["conflicting"] == 1
    assert index.resolve(eid("gtopdb", "1"), "drug", None)[1] == "conflicting"


def test_hetionet_disease_direction_and_edge_license(tmp_path, session):
    import bz2

    from oncograph.sources.hetionet_expression import HetionetExpressionAdapter

    node = {
        "kind": "Disease",
        "identifier": "DOID:1",
        "name": "Disease",
        "data": {"license": "CC BY 3.0", "source": "Disease Ontology"},
    }
    edge = {
        "source_id": ["Disease", "DOID:1"],
        "target_id": ["Gene", 2],
        "kind": "upregulates",
        "direction": "both",
        "data": {"source": "STARGEO", "license": "CC0 1.0", "log2_fold_change": 0.3},
    }
    payload = {
        "nodes": [node],
        "edges": [
            edge,
            {**edge, "kind": "downregulates", "data": {**edge["data"], "log2_fold_change": -0.4}},
            {**edge, "data": {**edge["data"], "license": "unknown"}},
            {**edge, "kind": "associates"},
        ],
    }
    path = tmp_path / "hetionet.json.bz2"
    with bz2.open(path, "wt") as handle:
        json.dump(payload, handle)
    adapter = HetionetExpressionAdapter(path)
    crosswalk = identities(session)
    crosswalk.register(adapter.disease_entities())
    report = import_signed_observations(
        session, adapter.iter_edges(), adapter.descriptor, crosswalk, adapter.report
    )
    assert report.input_records == 4 and report.scoped_records == 3
    assert report.relations_created == 2
    assert report.skipped["unreviewed_source_or_license"] == 1
    for relation in session.exec(select(Relation)):
        assert session.get(Entity, relation.subject_id).type == "gene"
        assert session.get(Entity, relation.object_id).type == "disease"
    evidence = session.exec(select(Evidence)).first()
    context = json.loads(evidence.context)
    assert context["original_direction"] == "both"
    assert context["causal_scope"] == "differential_expression_association_only"


def test_cli_report_json_and_rerun(tmp_path):
    import runpy

    module = runpy.run_path("scripts/import_sigma_sources.py")
    (tmp_path / "hgnc.tsv").write_text(
        "hgnc_id\tsymbol\tstatus\tentrez_id\tensembl_gene_id\tuniprot_ids\n"
        "HGNC:2\tG\tApproved\t2\tENSG2\tP00002\n"
    )
    # table_rows supports uncompressed fixtures only when the suffix agrees.
    import gzip

    with gzip.open(tmp_path / "lincs_pert_info.txt.gz", "wt") as handle:
        handle.write("pert_id\tpert_iname\tpert_type\tpubchem_cid\nBRD-1\tdrug\ttrt_cp\t1\n")
    with gzip.open(tmp_path / "lincs_edges.tsv.gz", "wt") as handle:
        handle.write(
            "\tGene\tGene ID\tChemical Perturbation\tZ-score\tThreshold Value\n"
            "0\tG\t2\tBRD-1\t4\t1\n1\tG\t2\tmissing\t-4\t-1\n"
        )
    db = tmp_path / "test.db"
    first = module["run_import"](tmp_path, db, None, ["lincs"], "fixture snapshot")
    json.dumps(first)
    source = first["sources"]["harmonizome_lincs_consensus"]
    assert source["evidence_created"] == 1
    assert source["skipped"] == {"compound_unmatched": 1}
    second = module["run_import"](tmp_path, db, None, ["lincs"], "fixture snapshot")
    source = second["sources"]["harmonizome_lincs_consensus"]
    assert source["evidence_created"] == source["relations_created"] == 0
    assert source["duplicate_evidence"] == 1
    with Session(create_engine(f"sqlite:///{db}")) as session:
        assert not session.exec(
            select(EntityIdentifier).where(EntityIdentifier.namespace == "uniprot")
        ).all()


def test_gtopdb_multiple_cids_are_not_a_single_identifier(tmp_path):
    from oncograph.sources.sigma_sources import gtopdb_drug_entities

    path = tmp_path / "ligands.csv"
    path.write_text(
        '"# GtoPdb Version: fixture"\n'
        "Ligand id,Name,Type,PubChem CID,ChEMBl ID,DrugBank ID\n"
        "1,Compound,Synthetic organic,12|34,CHEMBL1,DB00001\n"
    )
    record = gtopdb_drug_entities(path)[0]
    assert record.metadata["identifier_mapping_conflicts"] == {"PubChem CID": "12|34"}
    assert all(identifier.value != "12|34" for identifier in record.identifiers)
