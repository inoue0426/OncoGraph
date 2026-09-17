"""Issue #11: Context-Conditioned Treatment Response & Transferability."""

import json

from oncograph.models import EntityType
from oncograph.sources.aact import AactAdapter
from oncograph.sources.clinicaltrials import ClinicalTrialsAdapter, _classify_termination_reason
from oncograph.sources.combination_data import CombinationDataAdapter

# --- Termination-reason classification (real ClinicalTrials.gov whyStopped text) --


def test_classify_termination_reason_returns_none_for_a_trial_that_never_stopped():
    assert _classify_termination_reason("COMPLETED", None) is None
    assert _classify_termination_reason("RECRUITING", "irrelevant") is None


def test_classify_termination_reason_not_reported_when_no_text():
    assert _classify_termination_reason("TERMINATED", None) == "NOT_REPORTED"
    assert _classify_termination_reason("WITHDRAWN", "") == "NOT_REPORTED"


def test_classify_termination_reason_never_equates_status_alone_with_efficacy_failure():
    # A bare TERMINATED/WITHDRAWN/SUSPENDED status with no reason text must
    # never become LACK_OF_EFFICACY -- that would fabricate an efficacy claim.
    for status in ("TERMINATED", "WITHDRAWN", "SUSPENDED"):
        assert _classify_termination_reason(status, None) == "NOT_REPORTED"


def test_classify_termination_reason_matches_real_observed_examples():
    # Real whyStopped text observed live from the ClinicalTrials.gov API during this pass.
    assert _classify_termination_reason("TERMINATED", "Company development strategy change") == "BUSINESS_DECISION"
    assert _classify_termination_reason("SUSPENDED", "Safety concerns raised by DSMB") == "SAFETY"
    assert _classify_termination_reason("WITHDRAWN", "Lack of funding") == "FUNDING"
    assert _classify_termination_reason("TERMINATED", "Study did not meet its primary efficacy endpoint") == "LACK_OF_EFFICACY"
    assert _classify_termination_reason("TERMINATED", "Unable to complete recruitment") == "RECRUITMENT"


def test_classify_termination_reason_unmatched_text_falls_back_to_unknown_not_a_guess():
    assert _classify_termination_reason("TERMINATED", "Something ambiguous happened") == "UNKNOWN"


# --- Trial entity metadata carries the classification + raw text --------------


def test_trial_entity_metadata_includes_termination_reason_and_raw_text(tmp_path):
    rows = [
        {
            "ligand_id": "1",
            "ligand_name": "drugx",
            "nct_id": "NCT01",
            "brief_title": "A terminated trial",
            "overall_status": "TERMINATED",
            "why_stopped": "Safety concerns",
            "phases": ["PHASE2"],
            "conditions": ["Cancer"],
            "matched_intervention": "DrugX",
        }
    ]
    path = tmp_path / "trials.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    entity = next(iter(ClinicalTrialsAdapter(path, release="test").iter_entities()))
    assert entity.metadata["termination_reason"] == "SAFETY"
    assert entity.metadata["termination_reason_raw"] == "Safety concerns"


# --- Real combination-treatment detection from multi-drug trial matches -------

_REAL_COMBO_TRIAL_ROWS = [
    {
        "ligand_id": "7519",
        "ligand_name": "olaparib",
        "nct_id": "NCT03737643",
        "brief_title": "Durvalumab + Bevacizumab + Olaparib in Advanced Ovarian Cancer",
        "overall_status": "ACTIVE_NOT_RECRUITING",
        "why_stopped": None,
        "phases": ["PHASE3"],
        "conditions": ["Advanced Ovarian Cancer"],
        "matched_intervention": "Olaparib",
    },
    {
        "ligand_id": "9223",
        "ligand_name": "durvalumab",
        "nct_id": "NCT03737643",
        "brief_title": "Durvalumab + Bevacizumab + Olaparib in Advanced Ovarian Cancer",
        "overall_status": "ACTIVE_NOT_RECRUITING",
        "why_stopped": None,
        "phases": ["PHASE3"],
        "conditions": ["Advanced Ovarian Cancer"],
        "matched_intervention": "Durvalumab",
    },
    {
        "ligand_id": "22",
        "ligand_name": "asenapine",
        "nct_id": "NCT00000001",
        "brief_title": "A Study of Asenapine Alone",
        "overall_status": "COMPLETED",
        "why_stopped": None,
        "phases": ["PHASE2"],
        "conditions": ["Schizophrenia"],
        "matched_intervention": "Asenapine",
    },
]


def test_combination_treatment_created_only_for_trials_matched_to_2plus_distinct_drugs(tmp_path):
    path = tmp_path / "trials.json"
    path.write_text(json.dumps(_REAL_COMBO_TRIAL_ROWS), encoding="utf-8")
    entities = list(ClinicalTrialsAdapter(path, release="test").iter_entities())
    combos = [e for e in entities if e.entity_type == "combination_treatment"]
    assert len(combos) == 1
    assert combos[0].name == "durvalumab + olaparib"
    assert sorted(combos[0].metadata["component_ligand_ids"]) == ["7519", "9223"]
    assert combos[0].metadata["nct_id"] == "NCT03737643"
    # The single-drug asenapine trial must not produce a spurious combination.
    assert not any(c.metadata["nct_id"] == "NCT00000001" for c in combos)


def test_combination_treatment_emits_has_component_and_tested_in_edges(tmp_path):
    path = tmp_path / "trials.json"
    path.write_text(json.dumps(_REAL_COMBO_TRIAL_ROWS), encoding="utf-8")
    edges = list(ClinicalTrialsAdapter(path, release="test").iter_edges())
    combo_edges = [e for e in edges if e.subject.namespace == "ctgov_combo"]
    predicates = {e.predicate for e in combo_edges}
    assert predicates == {"has_component", "tested_in"}
    component_targets = {e.object.value for e in combo_edges if e.predicate == "has_component"}
    assert component_targets == {"7519", "9223"}


def test_combination_id_is_deterministic_across_reimports(tmp_path):
    path = tmp_path / "trials.json"
    path.write_text(json.dumps(_REAL_COMBO_TRIAL_ROWS), encoding="utf-8")
    first = {e.identifiers[0].value for e in ClinicalTrialsAdapter(path).iter_entities() if e.entity_type == "combination_treatment"}
    second = {e.identifiers[0].value for e in ClinicalTrialsAdapter(path).iter_entities() if e.entity_type == "combination_treatment"}
    assert first == second


# --- New EntityType members -----------------------------------------------------


def test_combination_treatment_entity_type_exists():
    assert EntityType("combination_treatment") is not None


# --- AACT scaffold ------------------------------------------------------------


def test_aact_scaffold_preserves_outcome_category_distinct_from_registration(tmp_path):
    records = [{"nct_id": "NCT01", "outcome_category": "NEGATIVE", "serious_adverse_event_count": 5}]
    path = tmp_path / "aact.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    adapter = AactAdapter(path, release="test")
    edges = list(adapter.iter_edges())
    assert edges[0].predicate == "has_reported_outcome"
    assert edges[0].context["outcome_category"] == "NEGATIVE"
    assert edges[0].evidence_type == "aact_trial_outcome"


def test_aact_scaffold_skips_invalid_outcome_category(tmp_path):
    records = [{"nct_id": "NCT01", "outcome_category": "TOTALLY_MADE_UP"}]
    path = tmp_path / "aact.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    assert list(AactAdapter(path).iter_edges()) == []


# --- Combination-data scaffold (DrugComb / NCI ALMANAC / DREAM / AZ-Sanger) -----


def test_combination_data_scaffold_preserves_original_synergy_metric(tmp_path):
    records = [
        {
            "source_dataset": "drugcomb_v1.5",
            "drug_pubchem_cids": ["1", "2"],
            "cellosaurus_id": "CVCL_0023",
            "cell_line_name": "A549",
            "synergy_metric_name": "ZIP",
            "synergy_metric_value": 12.3,
        }
    ]
    path = tmp_path / "combo.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    adapter = CombinationDataAdapter(path, release="test")
    entities = list(adapter.iter_entities())
    combo = next(e for e in entities if e.entity_type == "combination_treatment")
    assert combo.name == "1 + 2"

    edges = list(adapter.iter_edges())
    synergy_edge = next(e for e in edges if e.predicate == "has_synergy_metric")
    assert synergy_edge.context["synergy_metric_name"] == "ZIP"
    assert synergy_edge.context["synergy_metric_value"] == 12.3
    component_edges = [e for e in edges if e.predicate == "has_component"]
    assert {e.object.value for e in component_edges} == {"1", "2"}


def test_combination_data_scaffold_skips_single_drug_rows(tmp_path):
    records = [{"source_dataset": "x", "drug_pubchem_cids": ["1"], "cellosaurus_id": "CVCL_1"}]
    path = tmp_path / "combo.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    adapter = CombinationDataAdapter(path)
    assert [e for e in adapter.iter_entities() if e.entity_type == "combination_treatment"] == []
    assert list(adapter.iter_edges()) == []
