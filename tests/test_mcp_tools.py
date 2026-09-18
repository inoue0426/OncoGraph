"""oncograph.mcp.tools: MCP tool implementations, tested against the
private session-taking functions (no MCP server/transport involved) with a
small, realistic in-memory graph -- no live external calls, matching this
repository's existing test pattern throughout.
"""

import json
import tempfile

import pytest
from sqlmodel import Session, SQLModel, create_engine

from oncograph.mcp._common import OncoGraphMCPError
from oncograph.mcp.tools import (
    _find_combination_treatments,
    _find_contextual_response_evidence,
    _find_drug_mechanism,
    _find_drugs_for_disease,
    _find_mechanism_paths,
    _find_trials,
    _get_entity,
    _get_evidence,
    _get_neighbors,
    _search_entities,
    _traverse_graph,
    get_graph_stats,
)
from oncograph.models import ClaimState, Entity, Evidence, Relation


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_graph(session: Session) -> dict[str, Entity]:
    drug = Entity(type="drug", name="TestDrug", canonical_id="gtopdb:1")
    other_drug = Entity(type="drug", name="OtherDrug", canonical_id="gtopdb:2")
    gene = Entity(type="gene", name="TestGene", canonical_id="hgnc:HGNC:1")
    disease = Entity(type="disease", name="TestDisease", canonical_id="mondo:1")
    trial = Entity(
        type="trial",
        name="TestTrial",
        canonical_id="clinicaltrials.gov:NCT001",
        description="Test Cancer",
        entity_metadata=json.dumps({"overall_status": "RECRUITING", "conditions": ["Test Cancer"]}),
    )
    combo = Entity(type="combination_treatment", name="TestDrug + OtherDrug", canonical_id="ctgov_combo:1")
    session.add_all([drug, other_drug, gene, disease, trial, combo])
    session.flush()

    targets = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
    inhibits = Relation(subject_id=drug.id, predicate="inhibits", object_id=gene.id)
    indicated = Relation(subject_id=drug.id, predicate="indicated_for", object_id=disease.id)
    studied_in = Relation(subject_id=drug.id, predicate="studied_in", object_id=trial.id)
    mechanism_path = Relation(subject_id=drug.id, predicate="implicated_in_mechanism_for", object_id=disease.id)
    has_component_1 = Relation(subject_id=combo.id, predicate="has_component", object_id=drug.id)
    has_component_2 = Relation(subject_id=combo.id, predicate="has_component", object_id=other_drug.id)
    tested_in = Relation(subject_id=combo.id, predicate="tested_in", object_id=trial.id)
    session.add_all(
        [targets, inhibits, indicated, studied_in, mechanism_path, has_component_1, has_component_2, tested_in]
    )
    session.flush()

    session.add(Evidence(relation_id=targets.id, source="gtopdb", source_type="curated_database", evidence_type="target_interaction"))
    session.add(Evidence(relation_id=inhibits.id, source="chembl", source_type="curated_database", evidence_type="chembl_mechanism_of_action"))
    session.add(
        Evidence(
            relation_id=indicated.id,
            source="open_targets_indications",
            source_type="curated_database",
            evidence_type="approved_indication",
        )
    )
    session.add(
        Evidence(
            relation_id=studied_in.id,
            source="clinicaltrials_gov",
            source_type="registry",
            evidence_type="clinical_trial_enrollment",
            context=json.dumps({"matched_intervention": "TestDrug", "overall_status": "RECRUITING"}),
        )
    )
    session.add(
        Evidence(
            relation_id=mechanism_path.id,
            source="drugmechdb",
            source_type="curated_database",
            evidence_type="drugmechdb_mechanism_path",
            context=json.dumps(
                {
                    "nodes": [
                        {"id": "MESH:1", "label": "Drug", "name": "TestDrug"},
                        {"id": "MESH:2", "label": "Disease", "name": "TestDisease"},
                    ],
                    "links": [{"key": "causes", "source": "MESH:1", "target": "MESH:2"}],
                }
            ),
        )
    )
    session.add(Evidence(relation_id=has_component_1.id, source="clinicaltrials_gov", source_type="registry"))
    session.add(Evidence(relation_id=has_component_2.id, source="clinicaltrials_gov", source_type="registry"))
    session.add(Evidence(relation_id=tested_in.id, source="clinicaltrials_gov", source_type="registry"))
    session.commit()

    return {
        "drug": drug,
        "other_drug": other_drug,
        "gene": gene,
        "disease": disease,
        "trial": trial,
        "combo": combo,
        "targets_relation": targets,
    }


# --- search_entities ------------------------------------------------------------


def test_search_entities_ranks_exact_name_above_substring():
    with _memory_session() as session:
        entities = _seed_graph(session)
        result = _search_entities(session, "TestDrug", None, limit=20)
    names = [r["name"] for r in result["results"]]
    assert names[0] == "TestDrug"  # exact match ranked first, ahead of "TestDrug + OtherDrug" (combo name)
    assert entities  # fixture built successfully


def test_search_entities_filters_by_entity_type():
    with _memory_session() as session:
        _seed_graph(session)
        result = _search_entities(session, "Test", "gene", limit=20)
    assert all(r["type"] == "gene" for r in result["results"])
    assert len(result["results"]) == 1


def test_search_entities_includes_relation_and_source_counts():
    with _memory_session() as session:
        _seed_graph(session)
        result = _search_entities(session, "TestDrug", "drug", limit=20)
    drug_result = next(r for r in result["results"] if r["canonical_id"] == "gtopdb:1")
    # targets, inhibits, indicated_for, studied_in, implicated_in_mechanism_for (as subject)
    # + has_component (as object, from the combo) = 6.
    assert drug_result["relation_count"] == 6
    # gtopdb, chembl, open_targets_indications, clinicaltrials_gov, drugmechdb = 5 distinct sources.
    assert drug_result["evidence_source_count"] == 5


def test_search_entities_empty_query_returns_no_results():
    with _memory_session() as session:
        _seed_graph(session)
        result = _search_entities(session, "   ", None, limit=20)
    assert result["results"] == []


def test_search_entities_deterministic_ordering_is_stable_across_calls():
    with _memory_session() as session:
        _seed_graph(session)
        first = _search_entities(session, "Test", None, limit=20)
        second = _search_entities(session, "Test", None, limit=20)
    assert [r["id"] for r in first["results"]] == [r["id"] for r in second["results"]]


# --- get_entity -------------------------------------------------------------


def test_get_entity_returns_canonical_data_and_relation_summary():
    with _memory_session() as session:
        entities = _seed_graph(session)
        result = _get_entity(session, "gtopdb:1")
    assert result["canonical_id"] == "gtopdb:1"
    assert result["relation_summary"]["relation_count"] == 6
    assert set(result["relation_summary"]["distinct_predicates"]) == {
        "targets", "inhibits", "indicated_for", "studied_in", "implicated_in_mechanism_for", "has_component"
    }
    assert entities["drug"].name == "TestDrug"


def test_get_entity_unknown_entity_raises_oncograph_mcp_error():
    with _memory_session() as session:
        _seed_graph(session)
        with pytest.raises(OncoGraphMCPError, match="No entity found"):
            _get_entity(session, "does-not-exist")


# --- get_neighbors ------------------------------------------------------------


def test_get_neighbors_returns_connecting_relations():
    with _memory_session() as session:
        _seed_graph(session)
        result = _get_neighbors(session, "gtopdb:1", predicate="targets", entity_type=None, limit=50)
    assert result["neighbor_count"] == 1
    assert result["neighbors"][0]["canonical_id"] == "hgnc:HGNC:1"
    assert result["relations"][0]["predicate"] == "targets"


def test_get_neighbors_filters_by_entity_type():
    with _memory_session() as session:
        _seed_graph(session)
        result = _get_neighbors(session, "gtopdb:1", predicate=None, entity_type="trial", limit=50)
    assert all(n["type"] == "trial" for n in result["neighbors"])


def test_get_neighbors_respects_limit():
    with _memory_session() as session:
        _seed_graph(session)
        result = _get_neighbors(session, "gtopdb:1", predicate=None, entity_type=None, limit=1)
    assert result["neighbor_count"] == 1


# --- get_evidence -------------------------------------------------------------


def test_get_evidence_preserves_all_provenance_fields():
    with _memory_session() as session:
        entities = _seed_graph(session)
        relation_id = str(entities["targets_relation"].id)
        result = _get_evidence(session, relation_id)
    assert result["relation"]["predicate"] == "targets"
    ev = result["evidence"][0]
    for field in (
        "source", "source_id", "source_url", "source_type", "evidence_type", "license",
        "publication_id", "context", "confidence", "claim_state", "verification_status", "retrieved_at",
    ):
        assert field in ev


def test_get_evidence_invalid_uuid_raises_oncograph_mcp_error():
    with _memory_session() as session:
        _seed_graph(session)
        with pytest.raises(OncoGraphMCPError, match="must be a UUID"):
            _get_evidence(session, "not-a-uuid")


def test_get_evidence_unknown_relation_raises_oncograph_mcp_error():
    with _memory_session() as session:
        _seed_graph(session)
        with pytest.raises(OncoGraphMCPError, match="No relation found"):
            _get_evidence(session, "00000000-0000-0000-0000-000000000000")


# --- traverse_graph -------------------------------------------------------------


def test_traverse_graph_default_strategy_is_query_conditioned():
    with _memory_session() as session:
        _seed_graph(session)
        result = _traverse_graph(
            session, "gtopdb:1", 1, None, None, None, False, 100, "query_conditioned", "What gene does TestDrug target?"
        )
    assert result["retrieval_strategy"] == "query_conditioned"


def test_traverse_graph_unknown_strategy_raises_oncograph_mcp_error():
    with _memory_session() as session:
        _seed_graph(session)
        with pytest.raises(OncoGraphMCPError, match="Unknown retrieval_strategy"):
            _traverse_graph(session, "gtopdb:1", 1, None, None, None, False, 100, "not_a_strategy", None)


def test_traverse_graph_unknown_entity_raises_oncograph_mcp_error():
    with _memory_session() as session:
        _seed_graph(session)
        with pytest.raises(OncoGraphMCPError, match="No entity found"):
            _traverse_graph(session, "does-not-exist", 1, None, None, None, False, 100, "graph", None)


def test_traverse_graph_enforces_limit():
    with _memory_session() as session:
        _seed_graph(session)
        result = _traverse_graph(session, "gtopdb:1", 2, None, None, None, False, 1, "graph", None)
    non_root = [e for e in result["entities"] if e["id"] != result["root"]["id"]]
    assert len(non_root) == 1
    assert result["truncated"] is True


def test_traverse_graph_reports_contradictory_relations():
    with _memory_session() as session:
        entities = _seed_graph(session)
        # A second, contradicting evidence row on the same "targets" relation.
        session.add(
            Evidence(
                relation_id=entities["targets_relation"].id,
                source="some_other_source",
                claim_state=ClaimState.CONTRADICTS,
            )
        )
        session.commit()
        result = _traverse_graph(session, "gtopdb:1", 1, "targets", None, None, False, 100, "graph", None)
    assert str(entities["targets_relation"].id) in result["contradictory_relation_ids"]


# --- find_drugs_for_disease ------------------------------------------------------


def test_find_drugs_for_disease_returns_real_indicated_for_relation():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_drugs_for_disease(session, "mondo:1", limit=20)
    assert result["drug_count"] == 1
    assert result["drugs"][0]["canonical_id"] == "gtopdb:1"


# --- find_trials --------------------------------------------------------------


def test_find_trials_filters_by_drug_and_status():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_trials(session, None, None, "gtopdb:1", "RECRUITING", limit=20)
    assert result["trial_count"] == 1
    assert result["trials"][0]["canonical_id"] == "clinicaltrials.gov:NCT001"


def test_find_trials_status_mismatch_returns_empty():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_trials(session, None, None, "gtopdb:1", "COMPLETED", limit=20)
    assert result["trial_count"] == 0


def test_find_trials_filters_by_disease_substring():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_trials(session, None, "Test Cancer", None, None, limit=20)
    assert result["trial_count"] == 1


# --- find_drug_mechanism / find_mechanism_paths ---------------------------------


def test_find_drug_mechanism_identifies_by_evidence_type_not_predicate():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_drug_mechanism(session, "gtopdb:1", None, max_hops=2, limit=20)
    predicates = {r["predicate"] for r in result["mechanism_relations"]}
    # "targets" (target_interaction), "inhibits" (chembl_mechanism_of_action), and
    # "implicated_in_mechanism_for" (drugmechdb_mechanism_path) are mechanism-flagged;
    # "indicated_for"/"studied_in"/"has_component" are not.
    assert predicates == {"targets", "inhibits", "implicated_in_mechanism_for"}


def test_find_mechanism_paths_distinguishes_stored_from_computed():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_mechanism_paths(session, "gtopdb:1", None, max_hops=2, limit=20)
    path_types = {p["path_type"] for p in result["paths"]}
    assert "stored_curated" in path_types
    assert "computed_traversal" in path_types
    stored = next(p for p in result["paths"] if p["path_type"] == "stored_curated")
    assert stored["source"] == "drugmechdb"
    assert len(stored["nodes"]) == 2


def test_find_mechanism_paths_never_labels_computed_as_curated():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_mechanism_paths(session, "gtopdb:1", None, max_hops=2, limit=20)
    for path in result["paths"]:
        if path["path_type"] == "computed_traversal":
            assert "source" not in path or path.get("source") != "drugmechdb"


# --- find_combination_treatments -------------------------------------------------


def test_find_combination_treatments_by_drug():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_combination_treatments(session, "gtopdb:1", None, limit=20)
    assert result["combination_count"] == 1
    combo = result["combinations"][0]
    component_ids = {c["canonical_id"] for c in combo["components"]}
    assert component_ids == {"gtopdb:1", "gtopdb:2"}
    assert combo["trials"][0]["canonical_id"] == "clinicaltrials.gov:NCT001"


def test_find_combination_treatments_by_disease_substring():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_combination_treatments(session, None, "Test Cancer", limit=20)
    assert result["combination_count"] == 1


def test_find_combination_treatments_unrelated_drug_returns_empty():
    with _memory_session() as session:
        _seed_graph(session)
        # OtherDrug is a component but has no *own* has_component edge as combo's start point --
        # querying for a totally unrelated canonical id should just resolve-error, not silently match.
        with pytest.raises(OncoGraphMCPError):
            _find_combination_treatments(session, "does-not-exist", None, limit=20)


# --- find_contextual_response_evidence -------------------------------------------


def test_find_contextual_response_evidence_returns_honest_empty_with_note():
    with _memory_session() as session:
        _seed_graph(session)
        result = _find_contextual_response_evidence(session, "gtopdb:1", None, None, None, limit=20)
    assert result["response_relation_count"] == 0
    assert result["note"] is not None
    assert "no real drug-response dataset" in result["note"]


# --- get_graph_stats (reuses oncograph.stats.compute_stats) ---------------------


def test_get_graph_stats_reuses_compute_stats(monkeypatch):
    # get_graph_stats() opens its own session via the module-level engine;
    # point that at a freshly seeded, file-based temp DB (not a pure
    # "sqlite://" in-memory DB, which is per-connection and would look
    # empty to the tool's own fresh session) so setup and the tool call
    # share the same data.
    engine = create_engine(f"sqlite:///{tempfile.mktemp(suffix='.db')}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_graph(session)

    import oncograph.mcp._common as common_module

    monkeypatch.setattr(common_module, "engine", engine)
    stats = get_graph_stats()
    assert stats["entities"]["drug"] == 2
    assert stats["entities"]["total"] == 6
    assert stats["relations"] == 8
    assert stats["paths"]["mechanistic"] == 1
