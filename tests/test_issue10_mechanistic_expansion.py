"""Issue #10: Mechanistic & Functional Evidence Expansion."""

import json

from oncograph.models import EntityType
from oncograph.sources.bindingdb import BindingDbAdapter
from oncograph.sources.chembl import ChemblAdapter
from oncograph.sources.depmap import DepMapAdapter
from oncograph.sources.drugcentral import DrugCentralAdapter
from oncograph.sources.drugmechdb import DrugMechDbAdapter
from oncograph.sources.gtex import GtexAdapter
from oncograph.sources.signor import SignorAdapter
from oncograph.sources.trrust import TrrustAdapter, _build_symbol_index

# --- New entity types -----------------------------------------------------------


def test_new_entity_types_exist():
    for value in ("tissue", "combination_treatment"):
        assert EntityType(value) is not None


# --- DrugMechDB -------------------------------------------------------------

_DRUGMECHDB_PATH = [
    {
        "graph": {
            "_id": "DB00619_MESH_D015464_1",
            "disease": "CML",
            "disease_mesh": "MESH:D015464",
            "drug": "imatinib",
            "drug_mesh": "MESH:D000068877",
        },
        "links": [
            {"key": "decreases activity of", "source": "MESH:D000068877", "target": "UniProt:P00519"},
            {"key": "causes", "source": "UniProt:P00519", "target": "MESH:D015464"},
        ],
        "nodes": [
            {"id": "MESH:D000068877", "label": "Drug", "name": "imatinib"},
            {"id": "UniProt:P00519", "label": "Protein", "name": "BCR/ABL"},
            {"id": "MESH:D015464", "label": "Disease", "name": "CML"},
        ],
    }
]


def test_drugmechdb_is_cc0_and_registered():
    assert DrugMechDbAdapter.descriptor.license == "CC0-1.0"
    assert DrugMechDbAdapter.descriptor.redistribution.value == "open"


def test_drugmechdb_emits_drug_disease_protein_entities(tmp_path):
    path = tmp_path / "paths.json"
    path.write_text(json.dumps(_DRUGMECHDB_PATH), encoding="utf-8")
    adapter = DrugMechDbAdapter(path, release="test")
    entities = list(adapter.iter_entities())
    types = {e.entity_type for e in entities}
    assert types == {"drug", "disease", "protein"}
    drug = next(e for e in entities if e.entity_type == "drug")
    assert (drug.identifiers[0].namespace, drug.identifiers[0].value) == ("mesh", "D000068877")


def test_drugmechdb_emits_endpoint_edge_with_full_path_preserved(tmp_path):
    path = tmp_path / "paths.json"
    path.write_text(json.dumps(_DRUGMECHDB_PATH), encoding="utf-8")
    adapter = DrugMechDbAdapter(path, release="test")
    edges = list(adapter.iter_edges())
    endpoint_edge = next(e for e in edges if e.predicate == "implicated_in_mechanism_for")
    assert endpoint_edge.subject.namespace == "mesh"
    assert endpoint_edge.subject.value == "D000068877"
    assert endpoint_edge.object.value == "D015464"
    assert len(endpoint_edge.context["nodes"]) == 3
    assert len(endpoint_edge.context["links"]) == 2


def test_drugmechdb_emits_direct_first_hop_target_edge(tmp_path):
    path = tmp_path / "paths.json"
    path.write_text(json.dumps(_DRUGMECHDB_PATH), encoding="utf-8")
    adapter = DrugMechDbAdapter(path, release="test")
    edges = list(adapter.iter_edges())
    target_edge = next(e for e in edges if e.evidence_type == "drugmechdb_direct_target")
    assert target_edge.predicate == "decreases_activity_of"
    assert (target_edge.object.namespace, target_edge.object.value) == ("uniprot", "P00519")


def test_drugmechdb_skips_paths_missing_an_endpoint(tmp_path):
    broken = [{"graph": {"_id": "x", "drug_mesh": "MESH:D1"}, "nodes": [], "links": []}]
    path = tmp_path / "paths.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    adapter = DrugMechDbAdapter(path, release="test")
    assert list(adapter.iter_edges()) == []


# --- ChEMBL -------------------------------------------------------------------

_CHEMBL_RECORDS = [
    {
        "drug_name": "gefitinib",
        "chembl_id": "CHEMBL939",
        "mechanisms": [
            {
                "action_type": "INHIBITOR",
                "mechanism_of_action": "EGFR inhibitor",
                "target_chembl_id": "CHEMBL203",
                "target_uniprot": "P00533",
                "target_gene_symbol": "EGFR",
                "max_phase": 4,
                "mec_id": 244,
                "mechanism_refs": [{"ref_type": "DailyMed", "ref_url": "https://example.test/x"}],
            }
        ],
    }
]


def test_chembl_is_cc_by_sa_and_registered():
    assert ChemblAdapter.descriptor.license == "CC BY-SA 3.0"


def test_chembl_maps_action_type_to_a_directed_predicate(tmp_path):
    path = tmp_path / "mech.json"
    path.write_text(json.dumps(_CHEMBL_RECORDS), encoding="utf-8")
    adapter = ChemblAdapter(path, release="test")
    edges = list(adapter.iter_edges())
    assert len(edges) == 1
    assert edges[0].predicate == "inhibits"
    assert edges[0].context["mechanism_of_action"] == "EGFR inhibitor"
    assert edges[0].context["max_phase"] == 4
    assert edges[0].source_url == "https://example.test/x"


def test_chembl_unrecognized_action_type_falls_back_to_generic_predicate(tmp_path):
    records = json.loads(json.dumps(_CHEMBL_RECORDS))
    records[0]["mechanisms"][0]["action_type"] = "SOME NEW TYPE"
    path = tmp_path / "mech.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    edges = list(ChemblAdapter(path).iter_edges())
    assert edges[0].predicate == "has_mechanism_of_action_on"


def test_chembl_skips_mechanism_with_no_resolved_target(tmp_path):
    records = json.loads(json.dumps(_CHEMBL_RECORDS))
    records[0]["mechanisms"][0]["target_uniprot"] = None
    path = tmp_path / "mech.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    assert list(ChemblAdapter(path).iter_edges()) == []


# --- TRRUST ---------------------------------------------------------------------

_HGNC_TSV = (
    "hgnc_id\tsymbol\talias_symbol\tprev_symbol\tentrez_id\tensembl_gene_id\tuniprot_ids\n"
    "HGNC:1\tMYC\t\t\t\t\t\n"
    "HGNC:2\tTP53\t\t\t\t\t\n"
)
_TRRUST_TSV = "MYC\tTP53\tRepression\t1234;5678\nMYC\tUNKNOWNGENE\tActivation\t9999\n"


def test_trrust_is_cc_by_sa_and_registered():
    assert TrrustAdapter.descriptor.license == "CC BY-SA 4.0"


def test_trrust_resolves_symbols_via_hgnc_and_skips_unresolvable(tmp_path):
    hgnc_path = tmp_path / "hgnc.tsv"
    hgnc_path.write_text(_HGNC_TSV, encoding="utf-8")
    trrust_path = tmp_path / "trrust.tsv"
    trrust_path.write_text(_TRRUST_TSV, encoding="utf-8")

    adapter = TrrustAdapter(trrust_path, hgnc_path, release="test")
    entities = list(adapter.iter_entities())
    assert {e.identifiers[0].value for e in entities} == {"HGNC:1", "HGNC:2"}  # UNKNOWNGENE never appears

    edges = list(adapter.iter_edges())
    assert len(edges) == 1  # only the MYC->TP53 row resolves on both ends
    assert edges[0].predicate == "negatively_regulates_expression_of"
    assert edges[0].publication.value == "1234"
    assert edges[0].context["pmids"] == ["1234", "5678"]


def test_trrust_activation_and_unknown_mode_predicates(tmp_path):
    hgnc_path = tmp_path / "hgnc.tsv"
    hgnc_path.write_text(_HGNC_TSV, encoding="utf-8")
    trrust_path = tmp_path / "trrust.tsv"
    trrust_path.write_text("MYC\tTP53\tActivation\t1\nTP53\tMYC\tUnknown\t2\n", encoding="utf-8")
    edges = list(TrrustAdapter(trrust_path, hgnc_path).iter_edges())
    predicates = {e.predicate for e in edges}
    assert predicates == {"positively_regulates_expression_of", "regulates_expression_of"}


def test_build_symbol_index_prefers_current_symbol_over_alias(tmp_path):
    # A symbol that is simultaneously HGNC:2's current symbol and HGNC:1's alias
    # must resolve to HGNC:2 (the current owner), never the stale alias record.
    hgnc_path = tmp_path / "hgnc.tsv"
    hgnc_path.write_text(
        "hgnc_id\tsymbol\talias_symbol\tprev_symbol\tentrez_id\tensembl_gene_id\tuniprot_ids\n"
        "HGNC:1\tOLD1\tTP53\t\t\t\t\n"
        "HGNC:2\tTP53\t\t\t\t\t\n",
        encoding="utf-8",
    )
    index = _build_symbol_index(hgnc_path)
    assert index["TP53"] == "HGNC:2"


# --- GTEx -------------------------------------------------------------------

_GTEX_RECORDS = [
    {
        "gene_symbol": "EGFR",
        "ensembl_gene_id": "ENSG00000146648",
        "tissue_id": "Lung",
        "tissue_uberon_id": "UBERON:0002048",
        "median_tpm": 12.3,
        "unit": "TPM",
        "dataset_id": "gtex_v8",
    }
]


def test_gtex_is_open_and_registered():
    assert GtexAdapter.descriptor.redistribution.value == "open"


def test_gtex_emits_gene_and_tissue_entities(tmp_path):
    path = tmp_path / "gtex.json"
    path.write_text(json.dumps(_GTEX_RECORDS), encoding="utf-8")
    entities = list(GtexAdapter(path, release="test").iter_entities())
    types = {e.entity_type for e in entities}
    assert types == {"gene", "tissue"}
    tissue = next(e for e in entities if e.entity_type == "tissue")
    assert (tissue.identifiers[0].namespace, tissue.identifiers[0].value) == ("uberon", "UBERON:0002048")


def test_gtex_expressed_in_edge_preserves_median_tpm(tmp_path):
    path = tmp_path / "gtex.json"
    path.write_text(json.dumps(_GTEX_RECORDS), encoding="utf-8")
    edges = list(GtexAdapter(path).iter_edges())
    assert len(edges) == 1
    assert edges[0].predicate == "expressed_in"
    assert edges[0].context["median_tpm"] == 12.3


# --- Scaffold-only adapters: SIGNOR, DrugCentral, DepMap, BindingDB -------------


def test_signor_scaffold_preserves_signed_directed_effect(tmp_path):
    records = [
        {"idA": "P00533", "nameA": "EGFR", "idB": "P62993", "nameB": "GRB2", "effect": "up-regulates activity", "pmid": "1"}
    ]
    path = tmp_path / "signor.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    adapter = SignorAdapter(path, release="test")
    edges = list(adapter.iter_edges())
    assert edges[0].predicate == "activates"  # not a generic undirected "interacts_with"
    assert adapter.descriptor.redistribution.value == "restricted"  # access gap, not merged as open


def test_signor_unknown_effect_falls_back_to_generic_regulates(tmp_path):
    records = [{"idA": "P1", "nameA": "A", "idB": "P2", "nameB": "B", "effect": "unknown"}]
    path = tmp_path / "signor.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    edges = list(SignorAdapter(path).iter_edges())
    assert edges[0].predicate == "regulates"


def test_drugcentral_scaffold_emits_mechanism_edge(tmp_path):
    records = [
        {
            "drugcentral_id": "1610",
            "drug_name": "gefitinib",
            "target_uniprot": "P00533",
            "target_gene_symbol": "EGFR",
            "action_type": "INHIBITOR",
        }
    ]
    path = tmp_path / "dc.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    edges = list(DrugCentralAdapter(path).iter_edges())
    assert edges[0].predicate == "has_mechanism_of_action_on"
    assert edges[0].context["action_type"] == "INHIBITOR"


def test_depmap_scaffold_keeps_dependency_score_out_of_confidence(tmp_path):
    records = [
        {
            "hgnc_id": "HGNC:3236",
            "gene_symbol": "EGFR",
            "cellosaurus_id": "CVCL_0023",
            "cell_line_name": "A549",
            "dependency_score": -0.9,
            "dataset": "CRISPR_23Q4",
        }
    ]
    path = tmp_path / "depmap.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    edges = list(DepMapAdapter(path).iter_edges())
    assert edges[0].confidence is None  # a dependency score is not a 0-1 confidence
    assert edges[0].context["dependency_score"] == -0.9


def test_bindingdb_scaffold_preserves_measurement_type_and_skips_invalid(tmp_path):
    records = [
        {"pubchem_cid": "1", "compound_name": "x", "target_uniprot": "P1", "measurement_type": "IC50", "value_nm": 5.0},
        {"pubchem_cid": "2", "compound_name": "y", "target_uniprot": "P2", "measurement_type": "not_a_type", "value_nm": 1.0},
    ]
    path = tmp_path / "bdb.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    edges = list(BindingDbAdapter(path).iter_edges())
    assert len(edges) == 1
    assert edges[0].evidence_type == "bindingdb_ic50"
    assert edges[0].context["value_nm"] == 5.0
