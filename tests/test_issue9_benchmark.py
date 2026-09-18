"""Issue #9: Research Benchmarking & Evaluation.

No benchmark result is asserted or reported here as a real experimental
finding -- only that the scoring infrastructure computes correct numbers
against hand-constructed prediction/gold pairs.
"""

from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from oncograph.benchmark import (
    BenchmarkItem,
    BenchmarkTaskType,
    GoldEvidenceRef,
    LLMOnlyRetriever,
    Prediction,
    VanillaGraphRetriever,
    VectorRAGRetriever,
    answer_correctness,
    citation_correctness,
    contradiction_awareness,
    evidence_completeness,
    graph_retrieval_to_prediction,
    load_benchmark_items,
    path_correctness,
    provenance_coverage,
    score_prediction,
    unsupported_claim_rate,
)
from oncograph.models import ClaimState, Entity, Evidence, Relation
from oncograph.query import GraphRetriever, RetrievalQuery

# --- VanillaGraphRetriever: a real ablation, not a scaffold --------------------


def test_vanilla_graph_retriever_matches_reachability_but_strips_evidence():
    """Same entities reachable as GraphRetriever, but zero evidence carried
    forward -- the exact ablation the benchmark is meant to isolate."""
    with _memory_session() as session:
        drug = Entity(type="drug", name="TestDrug", canonical_id="gtopdb:1")
        gene = Entity(type="gene", name="TestGene", canonical_id="hgnc:HGNC:1")
        session.add_all([drug, gene])
        session.flush()
        relation = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
        session.add(relation)
        session.flush()
        session.add(Evidence(relation_id=relation.id, source="gtopdb", claim_state=ClaimState.SUPPORTS))
        session.commit()

        aware = GraphRetriever(session).retrieve(RetrievalQuery(root_ref="TestDrug", max_hops=1))
        blind = VanillaGraphRetriever(session).retrieve(RetrievalQuery(root_ref="TestDrug", max_hops=1))

    assert {e["id"] for e in blind.entities} == {e["id"] for e in aware.entities}
    assert len(blind.relations) == len(aware.relations) == 1
    assert aware.relations[0]["evidence"]
    assert blind.relations[0]["evidence"] == []
    assert blind.relations[0]["publication_ids"] == []

    aware_prediction = graph_retrieval_to_prediction(aware)
    blind_prediction = graph_retrieval_to_prediction(blind)
    assert aware_prediction.answer_canonical_ids == blind_prediction.answer_canonical_ids
    assert aware_prediction.evidence_refs and not blind_prediction.evidence_refs


def test_vanilla_graph_retriever_returns_empty_result_for_unresolvable_root():
    with _memory_session() as session:
        result = VanillaGraphRetriever(session).retrieve(RetrievalQuery(root_ref="does-not-exist"))
    assert result.root is None
    assert result.entities == []

BENCHMARK_FILE = Path(__file__).resolve().parent.parent / "data" / "benchmarks" / "v1" / "oncology_core.json"


# --- Loading the versioned item file --------------------------------------------


def test_oncology_core_v1_loads_and_covers_its_original_nine_task_types():
    """v1 was written before Issue #11's real combination-treatment data existed,
    so it covers the original 9 task types, not every BenchmarkTaskType member
    that exists today (combination_treatment_reasoning is v2-only, generated
    from real data -- see scripts/generate_benchmark_items.py)."""
    items = load_benchmark_items(BENCHMARK_FILE)
    assert len(items) == 9
    task_types = {item.task_type for item in items}
    assert task_types == set(BenchmarkTaskType) - {BenchmarkTaskType.COMBINATION_TREATMENT_REASONING}


def test_loaded_item_fields_round_trip():
    items = load_benchmark_items(BENCHMARK_FILE)
    first = next(i for i in items if i.id == "v1-001")
    assert first.task_type == BenchmarkTaskType.SINGLE_HOP_FACTUAL_RETRIEVAL
    assert first.gold_answer_canonical_ids == ("hgnc:HGNC:3236",)
    assert first.gold_evidence_path[0] == GoldEvidenceRef("gtopdb:4941", "targets", "hgnc:HGNC:3236", "gtopdb")


# --- Metrics: real computations, synthetic prediction/gold pairs ---------------


def _item(**kwargs):
    defaults = {
        "id": "t",
        "version": "v1",
        "task_type": BenchmarkTaskType.SINGLE_HOP_FACTUAL_RETRIEVAL,
        "question": "q",
    }
    defaults.update(kwargs)
    return BenchmarkItem(**defaults)


def test_answer_correctness_is_recall_over_gold_ids():
    item = _item(gold_answer_canonical_ids=("a", "b"))
    full = Prediction(answer_canonical_ids=("a", "b", "c"))
    partial = Prediction(answer_canonical_ids=("a",))
    none = Prediction(answer_canonical_ids=())
    assert answer_correctness(full, item) == 1.0
    assert answer_correctness(partial, item) == 0.5
    assert answer_correctness(none, item) == 0.0


def test_citation_correctness_is_precision_over_predicted_evidence():
    gold_ref = GoldEvidenceRef("s", "p", "o")
    item = _item(gold_evidence_path=(gold_ref,))
    exact = Prediction(evidence_refs=(gold_ref,))
    noisy = Prediction(evidence_refs=(gold_ref, GoldEvidenceRef("x", "y", "z")))
    empty = Prediction()
    assert citation_correctness(exact, item) == 1.0
    assert citation_correctness(noisy, item) == 0.5
    assert citation_correctness(empty, item) == 0.0


def test_evidence_completeness_is_recall_over_gold_evidence():
    refs = (GoldEvidenceRef("a", "p", "b"), GoldEvidenceRef("b", "p", "c"))
    item = _item(gold_evidence_path=refs)
    complete = Prediction(evidence_refs=refs)
    half = Prediction(evidence_refs=refs[:1])
    assert evidence_completeness(complete, item) == 1.0
    assert evidence_completeness(half, item) == 0.5


def test_path_correctness_requires_exact_evidence_set_match():
    refs = (GoldEvidenceRef("a", "p", "b"), GoldEvidenceRef("b", "p", "c"))
    item = _item(gold_evidence_path=refs)
    exact = Prediction(evidence_refs=refs)
    extra = Prediction(evidence_refs=(*refs, GoldEvidenceRef("x", "y", "z")))
    assert path_correctness(exact, item) == 1.0
    assert path_correctness(extra, item) == 0.0


def test_unsupported_claim_rate_flags_claims_with_no_evidence_at_all():
    with_claims_no_evidence = Prediction(claims=("EGFR is the target",))
    with_claims_and_evidence = Prediction(claims=("EGFR is the target",), evidence_refs=(GoldEvidenceRef("a", "p", "b"),))
    no_claims = Prediction()
    assert unsupported_claim_rate(with_claims_no_evidence) == 1.0
    assert unsupported_claim_rate(with_claims_and_evidence) == 0.0
    assert unsupported_claim_rate(no_claims) == 0.0


def test_contradiction_awareness_only_penalizes_missed_known_contradictions():
    expects_conflict = _item(context={"has_known_contradiction": True})
    no_conflict_expected = _item(context={})
    flagged = Prediction(contradictions_flagged=True)
    missed = Prediction(contradictions_flagged=False)
    assert contradiction_awareness(expects_conflict, flagged) == 1.0
    assert contradiction_awareness(expects_conflict, missed) == 0.0
    assert contradiction_awareness(no_conflict_expected, missed) == 1.0  # nothing to miss


def test_provenance_coverage_requires_both_answer_and_evidence():
    answer_with_evidence = Prediction(answer_canonical_ids=("a",), evidence_refs=(GoldEvidenceRef("a", "p", "b"),))
    answer_without_evidence = Prediction(answer_canonical_ids=("a",))
    no_answer = Prediction()
    assert provenance_coverage(answer_with_evidence) == 1.0
    assert provenance_coverage(answer_without_evidence) == 0.0
    assert provenance_coverage(no_answer) == 0.0


def test_score_prediction_computes_all_seven_metrics():
    ref = GoldEvidenceRef("gtopdb:1", "targets", "hgnc:HGNC:1", "gtopdb")
    item = _item(gold_answer_canonical_ids=("hgnc:HGNC:1",), gold_evidence_path=(ref,))
    prediction = Prediction(answer_canonical_ids=("hgnc:HGNC:1",), evidence_refs=(ref,))

    score = score_prediction(item, prediction)

    assert score.item_id == "t"
    assert score.answer_correctness == 1.0
    assert score.citation_correctness == 1.0
    assert score.evidence_completeness == 1.0
    assert score.path_correctness == 1.0
    assert score.provenance_coverage == 1.0


# --- GraphRetriever integration: real traversal -> real scoring -----------------


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_graph_retriever_prediction_scores_correctly_against_its_own_data():
    """End-to-end: seed a tiny graph, retrieve, convert to Prediction, score --
    proves the pipeline is wired correctly, not a claim about real-world accuracy.
    """
    with _memory_session() as session:
        drug = Entity(type="drug", name="TestDrug", canonical_id="gtopdb:1")
        gene = Entity(type="gene", name="TestGene", canonical_id="hgnc:HGNC:1")
        session.add_all([drug, gene])
        session.flush()
        relation = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
        session.add(relation)
        session.flush()
        session.add(Evidence(relation_id=relation.id, source="gtopdb", claim_state=ClaimState.SUPPORTS))
        session.commit()

        retriever = GraphRetriever(session)
        result = retriever.retrieve(RetrievalQuery(root_ref="TestDrug", max_hops=1))
        prediction = graph_retrieval_to_prediction(result)

        item = _item(
            task_type=BenchmarkTaskType.SINGLE_HOP_FACTUAL_RETRIEVAL,
            gold_answer_canonical_ids=("hgnc:HGNC:1",),
            gold_evidence_path=(GoldEvidenceRef("gtopdb:1", "targets", "hgnc:HGNC:1", "gtopdb"),),
        )
        score = score_prediction(item, prediction)

    assert score.answer_correctness == 1.0
    assert score.citation_correctness == 1.0
    assert score.evidence_completeness == 1.0


def test_graph_retrieval_to_prediction_uses_principled_path_selection_not_whole_neighborhood():
    """A back-edge between two already-reached nodes must not be cited as
    evidence for any answer -- it explains no entity's reachability, so
    citing it would only hurt citation_correctness for no retrieval-quality
    reason. This is the exact failure mode docs/BENCHMARK_RUN_v2.md found
    (citation_correctness degrading with root-entity degree) and the fix
    this test locks in.
    """
    with _memory_session() as session:
        drug = Entity(type="drug", name="TestDrug", canonical_id="gtopdb:1")
        gene = Entity(type="gene", name="TestGene", canonical_id="hgnc:HGNC:1")
        session.add_all([drug, gene])
        session.flush()
        # The real, path-justifying edge.
        targets = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
        # A second, distinct-predicate edge between the SAME two (already
        # mutually reachable) nodes -- touched by the hop-2 BFS candidate
        # query but explains no new entity's reachability.
        back_edge = Relation(subject_id=gene.id, predicate="unrelated_back_reference", object_id=drug.id)
        session.add_all([targets, back_edge])
        session.flush()
        session.add(Evidence(relation_id=targets.id, source="gtopdb"))
        session.add(Evidence(relation_id=back_edge.id, source="some_other_source"))
        session.commit()

        result = GraphRetriever(session).retrieve(RetrievalQuery(root_ref="TestDrug", max_hops=2))
        # Sanity check: the BFS really did touch the back-edge.
        assert any(r["predicate"] == "unrelated_back_reference" for r in result.relations)

        prediction = graph_retrieval_to_prediction(result)

    cited_predicates = {ref.predicate for ref in prediction.evidence_refs}
    assert cited_predicates == {"targets"}  # the back-edge is never cited


# --- Retrieval-baseline scaffolding: explicitly not implemented -----------------
#
# VanillaGraphRetriever is excluded here -- it's a real ablation now (see
# test_vanilla_graph_retriever_* above), not a scaffold.


@pytest.mark.parametrize("retriever_cls", [LLMOnlyRetriever, VectorRAGRetriever])
def test_baseline_scaffolds_raise_not_implemented(retriever_cls):
    with pytest.raises(NotImplementedError):
        retriever_cls().retrieve(None)
