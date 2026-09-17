"""Issue #5: Biological Knowledge Expansion."""

import json

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_entities
from oncograph.models import ClaimState, Entity, EntityType, Evidence, Relation
from oncograph.sources.base import EntityRecord, ExternalIdentifier
from oncograph.sources.civic import CivicAdapter
from oncograph.sources.dgidb import DgidbAdapter
from oncograph.sources.gene_ontology import GeneOntologyAdapter
from oncograph.sources.ligand_receptor import LigandReceptorAdapter
from oncograph.sources.oncokb import OncoKbAdapter
from oncograph.sources.reactome import ReactomeAdapter


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


# --- New entity types ---------------------------------------------------------


def test_new_biological_entity_types_exist():
    for value in (
        "biomarker",
        "mutation",
        "fusion",
        "copy_number_alteration",
        "expression_signature",
    ):
        assert EntityType(value) is not None


# --- Reactome ------------------------------------------------------------------

REACTOME_TSV = (
    "1956\tR-HSA-177929\thttps://reactome.org/PathwayBrowser/#/R-HSA-177929\t"
    "Signaling by EGFR\tTAS\tHomo sapiens\n"
    "1956\tR-HSA-9006934\thttps://reactome.org/PathwayBrowser/#/R-HSA-9006934\t"
    "Signaling by Receptor Tyrosine Kinases\tTAS\tHomo sapiens\n"
    "13649\tR-HSA-177929\thttps://reactome.org/PathwayBrowser/#/R-HSA-177929\t"
    "Signaling by EGFR\tTAS\tMus musculus\n"
)


def test_reactome_is_cc0_and_registered():
    assert ReactomeAdapter.descriptor.license == "CC0"


def test_reactome_filters_to_homo_sapiens_and_dedupes_pathways(tmp_path):
    path = tmp_path / "NCBI2Reactome.txt"
    path.write_text(REACTOME_TSV, encoding="utf-8")
    adapter = ReactomeAdapter(path, release="2026-09")

    entities = list(adapter.iter_entities())
    edges = list(adapter.iter_edges())

    assert len(entities) == 2  # two unique human pathways; the mouse row is excluded
    assert {e.name for e in entities} == {
        "Signaling by EGFR",
        "Signaling by Receptor Tyrosine Kinases",
    }
    assert len(edges) == 2  # two human gene-pathway rows
    assert all(e.predicate == "part_of_pathway" for e in edges)
    assert all(e.subject == ExternalIdentifier("ncbigene", "1956") for e in edges)


def test_reactome_gene_pathway_edge_resolves_and_records_evidence(tmp_path):
    path = tmp_path / "NCBI2Reactome.txt"
    path.write_text(REACTOME_TSV, encoding="utf-8")
    adapter = ReactomeAdapter(path, release="2026-09")

    with _memory_session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="gene", name="EGFR", identifiers=(ExternalIdentifier("ncbigene", "1956"),)
                )
            ],
        )
        report = import_adapter(session, adapter)
        evidence_rows = session.exec(select(Evidence)).all()

    assert report.edges_created == 2
    assert all(e.evidence_type == "pathway_membership" for e in evidence_rows)
    assert all(e.source_type == "curated_database" for e in evidence_rows)


# --- CIViC -----------------------------------------------------------------

CIVIC_RECORDS = [
    {
        "evidence_id": 238,
        "gene_name": "EGFR",
        "gene_entrez_id": 1956,
        "evidence_type": "PREDICTIVE",
        "evidence_direction": "DOES_NOT_SUPPORT",
        "evidence_level": "B",
        "significance": "RESISTANCE",
        "therapies": [{"name": "Erlotinib", "ncit_id": "C66905"}],
        "disease_name": "Lung Non-small Cell Carcinoma",
        "disease_doid": "3908",
        "molecular_profile": "EGFR T790M",
        "source_type": "PUBMED",
        "citation_id": "20942809",
        "source_url": "https://civicdb.org/evidence/238",
    },
    {
        "evidence_id": 116,
        "gene_name": "NPM1",
        "gene_entrez_id": 4869,
        "evidence_type": "DIAGNOSTIC",
        "evidence_direction": "SUPPORTS",
        "evidence_level": "A",
        "significance": "POSITIVE",
        "therapies": [],
        "disease_name": "Acute Myeloid Leukemia",
        "disease_doid": "9119",
        "molecular_profile": "NPM1 EXON 11 MUTATION",
        "source_type": "PUBMED",
        "citation_id": "19357394",
        "source_url": "https://civicdb.org/evidence/116",
    },
]


def _write_civic_fixture(tmp_path):
    path = tmp_path / "civic_evidence.json"
    path.write_text(json.dumps(CIVIC_RECORDS), encoding="utf-8")
    return path


def test_civic_is_cc0():
    assert CivicAdapter.descriptor.license == "CC0"


def test_civic_therapy_evidence_emits_drug_disease_edge_with_contradicts(tmp_path):
    path = _write_civic_fixture(tmp_path)
    adapter = CivicAdapter(path, release="2026-09")

    with _memory_session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="drug", name="Erlotinib", identifiers=(ExternalIdentifier("ncit", "C66905"),)
                ),
                EntityRecord(
                    entity_type="disease", name="NSCLC", identifiers=(ExternalIdentifier("doid", "3908"),)
                ),
            ],
        )
        import_adapter(session, adapter)
        relation = session.exec(select(Relation).where(Relation.predicate == "clinically_evidenced_for")).one()
        evidence = session.exec(select(Evidence).where(Evidence.relation_id == relation.id)).one()

    assert evidence.claim_state == ClaimState.CONTRADICTS  # DOES_NOT_SUPPORT
    assert evidence.evidence_type == "civic_predictive"
    context = json.loads(evidence.context)
    assert context["significance"] == "RESISTANCE"
    assert context["molecular_profile"] == "EGFR T790M"
    assert evidence.publication_id is None  # PMID not separately imported here -> unresolved


def test_civic_no_therapy_emits_gene_disease_edge(tmp_path):
    path = _write_civic_fixture(tmp_path)
    adapter = CivicAdapter(path, release="2026-09")

    with _memory_session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="gene", name="NPM1", identifiers=(ExternalIdentifier("ncbigene", "4869"),)
                ),
                EntityRecord(
                    entity_type="disease", name="AML", identifiers=(ExternalIdentifier("doid", "9119"),)
                ),
            ],
        )
        import_adapter(session, adapter)
        relation = session.exec(
            select(Relation).where(Relation.predicate == "clinically_associated_with")
        ).one()
        evidence = session.exec(select(Evidence).where(Evidence.relation_id == relation.id)).one()

    assert evidence.claim_state == ClaimState.SUPPORTS
    assert evidence.evidence_type == "civic_diagnostic"


# --- DGIdb -------------------------------------------------------------------

DGIDB_RECORDS = [
    {
        "gene_name": "EGFR",
        "gene_concept_id": "hgnc:3236",
        "drug_name": "AFATINIB",
        "drug_concept_id": "chembl:CHEMBL1173655",
        "interaction_score": 0.85,
        "interaction_types": ["inhibitor"],
        "sources": ["ChEMBL", "OncoKB", "CIViC"],
    }
]


def test_dgidb_redistribution_is_unknown():
    assert DgidbAdapter.descriptor.redistribution == "unknown"


def test_dgidb_hgnc_concept_id_gains_prefix_and_resolves(tmp_path):
    path = tmp_path / "dgidb_interactions.json"
    path.write_text(json.dumps(DGIDB_RECORDS), encoding="utf-8")
    adapter = DgidbAdapter(path, release="2026-09")

    with _memory_session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="gene", name="EGFR", identifiers=(ExternalIdentifier("hgnc", "HGNC:3236"),)
                )
            ],
        )
        report = import_adapter(session, adapter)
        gene = session.exec(select(Entity).where(Entity.canonical_id == "hgnc:HGNC:3236")).one()
        relation = session.exec(select(Relation)).one()
        evidence = session.exec(select(Evidence)).one()

    assert report.edges_created == 1
    assert relation.object_id == gene.id
    assert relation.predicate == "interacts_with"
    assert evidence.source == "dgidb"
    assert evidence.source_type == "computed"
    context = json.loads(evidence.context)
    assert context["contributing_sources"] == ["ChEMBL", "OncoKB", "CIViC"]
    # DGIdb aggregation is never attributed as if it were OncoKB/CIViC directly.
    assert evidence.source == "dgidb"


# --- Ligand-receptor scaffold --------------------------------------------------

LIGAND_RECEPTOR_RECORDS = [
    {
        "ligand_namespace": "hgnc",
        "ligand_id": "HGNC:11766",
        "ligand_name": "TGFB1",
        "receptor_namespace": "hgnc",
        "receptor_id": "HGNC:11772",
        "receptor_name": "TGFBR1",
        "communication_type": "experimental",
        "cell_type_from": "fibroblast",
        "cell_type_to": "T cell",
        "source_record_id": "lr-1",
    },
    {
        "ligand_namespace": "hgnc",
        "ligand_id": "HGNC:11766",
        "ligand_name": "TGFB1",
        "receptor_namespace": "hgnc",
        "receptor_id": "HGNC:6770",
        "receptor_name": "ACVR1",
        "communication_type": "inferred",
        "source_record_id": "lr-2",
    },
    {
        "ligand_namespace": "hgnc",
        "ligand_id": "HGNC:11766",
        "receptor_namespace": "hgnc",
        "receptor_id": "HGNC:0000",
        "communication_type": "made_up_and_invalid",
        "source_record_id": "lr-3",
    },
]


def test_ligand_receptor_distinguishes_inferred_from_experimental(tmp_path):
    path = tmp_path / "ligand_receptor.json"
    path.write_text(json.dumps(LIGAND_RECEPTOR_RECORDS), encoding="utf-8")
    adapter = LigandReceptorAdapter(path)

    edges = list(adapter.iter_edges())

    assert len(edges) == 2  # the invalid communication_type row is skipped
    by_id = {e.source_record_id: e for e in edges}
    assert by_id["lr-1"].evidence_type == "ligand_receptor_binding_experimental"
    assert by_id["lr-2"].evidence_type == "ligand_receptor_binding_inferred"
    assert by_id["lr-1"].context["cell_type_from"] == "fibroblast"


# --- GO low-information filtering support --------------------------------------

GO_OBO_WITH_ROOT = (
    "format-version: 1.2\n"
    "\n"
    "[Term]\n"
    "id: GO:0008150\n"
    "name: biological_process\n"
    "namespace: biological_process\n"
    "\n"
    "[Term]\n"
    "id: GO:0000001\n"
    "name: mitochondrion inheritance\n"
    "namespace: biological_process\n"
    "is_a: GO:0008150 ! biological_process\n"
    "\n"
    "[Term]\n"
    "id: GO:0000002\n"
    "name: mitochondrial genome maintenance\n"
    "namespace: biological_process\n"
    "is_a: GO:0008150 ! biological_process\n"
)


# --- OncoKB scaffold (no live data; local-file only, restricted redistribution) --


ONCOKB_FIXTURE = [
    {
        "hugo_symbol": "EGFR",
        "entrez_gene_id": 1956,
        "alteration": "L858R",
        "drug_name": "Osimertinib",
        "ncit_id": "C112993",
        "level_of_evidence": "LEVEL_1",
        "cancer_type": "Non-Small Cell Lung Cancer",
        "citation_pmids": ["31151970"],
    }
]


def test_oncokb_is_restricted_and_scaffold_only():
    assert OncoKbAdapter.descriptor.redistribution == "restricted"


def test_oncokb_scaffold_maps_local_fixture_to_edge(tmp_path):
    path = tmp_path / "oncokb_export.json"
    path.write_text(json.dumps(ONCOKB_FIXTURE), encoding="utf-8")
    adapter = OncoKbAdapter(path, release="2026-09")

    (edge,) = list(adapter.iter_edges())

    assert edge.subject == ExternalIdentifier("ncit", "C112993")
    assert edge.object == ExternalIdentifier("ncbigene", "1956")
    assert edge.predicate == "clinically_actionable_for"
    assert edge.evidence_type == "oncokb_actionability"
    assert edge.publication == ExternalIdentifier("pmid", "31151970")
    assert edge.context["level_of_evidence"] == "LEVEL_1"


def test_go_adapter_flags_root_terms_and_child_counts(tmp_path):
    obo_path = tmp_path / "go-basic.obo"
    obo_path.write_text(GO_OBO_WITH_ROOT, encoding="utf-8")
    adapter = GeneOntologyAdapter(obo_path, release="2024-01-01")

    entities = {e.identifiers[0].value: e for e in adapter.iter_entities()}

    root = entities["GO:0008150"]
    child = entities["GO:0000001"]
    assert root.metadata["is_root"] is True
    assert root.metadata["child_count"] == 2
    assert child.metadata["is_root"] is False
    assert child.metadata["child_count"] == 0
