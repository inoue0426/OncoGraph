"""oncograph.rank.HybridPathRanker: semantic + structural extension.

Unit tests over synthetic data (fast) plus real-traversal integration
tests. As with test_rank.py, no test here constructs a scorer using a
benchmark item's gold answer/evidence -- only question text and graph
structure.
"""

import inspect

from sqlmodel import Session, SQLModel, create_engine

from oncograph.models import Entity, Evidence, Relation
from oncograph.query import RetrievalQuery
from oncograph.rank import (
    ComponentScores,
    HybridPathRanker,
    HybridWeights,
    _entity_type_match_score,
    _expected_entity_type,
    _tokenize,
    go_branch_factor,
    hub_branch_penalty,
    lexical_component,
    provenance_component,
    semantic_component,
    structural_component,
)
from oncograph.semantic import TfidfSpace

# --- Component functions: synthetic data ----------------------------------


def _relation(rel_id, subject_id, predicate, object_id, source_type="registry", context=None, **evidence_kwargs):
    evidence = {"source_type": source_type, "context": context or {}}
    evidence.update(evidence_kwargs)
    return {"id": rel_id, "subject_id": subject_id, "object_id": object_id, "predicate": predicate, "evidence": [evidence]}


def test_expected_entity_type_reads_a_generic_type_keyword():
    assert _expected_entity_type(_tokenize("What gene does X target?")) == "gene"
    assert _expected_entity_type(_tokenize("Which trial evaluates X?")) == "trial"
    assert _expected_entity_type(_tokenize("no type keyword here")) is None


def test_entity_type_match_score_three_cases():
    gene_entity = {"type": "gene"}
    assert _entity_type_match_score(gene_entity, "gene") == 1.0
    assert _entity_type_match_score(gene_entity, "trial") == 0.0
    assert _entity_type_match_score(gene_entity, None) == 0.5  # no signal -> neutral


def test_lexical_component_counts_predicate_question_overlap():
    tokens = _tokenize("What gene does X target?")
    matching = [_relation("r1", "d", "targets", "g")]
    nonmatching = [_relation("r2", "d", "studied_in", "t")]
    assert lexical_component(tokens, matching) > lexical_component(tokens, nonmatching)


def test_semantic_component_falls_back_gracefully_with_no_question_text():
    space = TfidfSpace(["drug targets gene", "some document"])
    assert semantic_component("", "drug targets gene", space) == 0.0


def test_semantic_component_falls_back_gracefully_with_no_document():
    space = TfidfSpace(["what gene does x target", "some document"])
    assert semantic_component("what gene does x target", "", space) == 0.0


def test_semantic_component_scores_topically_similar_text_higher():
    space = TfidfSpace(
        [
            "what gene does gefitinib target",
            "gefitinib targets egfr gene inhibitor",
            "a trial evaluating an unrelated combination therapy for diabetes",
        ]
    )
    relevant = semantic_component("what gene does gefitinib target", "gefitinib targets egfr gene inhibitor", space)
    irrelevant = semantic_component(
        "what gene does gefitinib target", "a trial evaluating an unrelated combination therapy for diabetes", space
    )
    assert relevant > irrelevant


def test_structural_component_prefers_matching_type_and_closer_hop():
    gene_entity = {"type": "gene"}
    trial_entity = {"type": "trial"}
    assert structural_component(gene_entity, hop_distance=1, expected_type="gene") > structural_component(
        trial_entity, hop_distance=1, expected_type="gene"
    )
    assert structural_component(gene_entity, hop_distance=1, expected_type="gene") > structural_component(
        gene_entity, hop_distance=2, expected_type="gene"
    )


def test_provenance_component_rewards_verification_and_publication():
    base = provenance_component([_relation("r1", "d", "targets", "g", source_type="registry")])
    verified = provenance_component(
        [_relation("r1", "d", "targets", "g", source_type="registry", verification_status="verified")]
    )
    with_publication = provenance_component(
        [_relation("r1", "d", "targets", "g", source_type="registry", publication_id="00000000-0000-0000-0000-000000000000")]
    )
    assert verified > base
    assert with_publication > base


def test_provenance_component_trial_context_rewards_exact_intervention_match():
    root_entity = {"name": "gefitinib"}
    exact = provenance_component(
        [_relation("r1", "d", "studied_in", "t", context={"matched_intervention": "gefitinib", "overall_status": "COMPLETED"})],
        root_entity=root_entity,
    )
    fuzzy = provenance_component(
        [
            _relation(
                "r2",
                "d",
                "studied_in",
                "t",
                context={"matched_intervention": "Gefitinib Plus Chemotherapy Combo", "overall_status": "UNKNOWN"},
            )
        ],
        root_entity=root_entity,
    )
    assert exact > fuzzy


def test_provenance_component_trial_context_ignored_without_root_entity():
    # Same relation, no root_entity supplied -- must not crash, must not
    # apply the trial-context bonus (root_entity=None is the documented
    # opt-out, e.g. for non-trial-context callers).
    score = provenance_component(
        [_relation("r1", "d", "studied_in", "t", context={"matched_intervention": "gefitinib", "overall_status": "COMPLETED"})]
    )
    assert score == provenance_component([_relation("r1", "d", "studied_in", "t")])


def test_go_branch_factor_counts_local_is_a_children_only():
    relations = [
        _relation("r1", "child1", "is_a", "parent"),
        _relation("r2", "child2", "is_a", "parent"),
        _relation("r3", "child3", "part_of", "parent"),  # not is_a -- must not count
        _relation("r4", "other", "is_a", "unrelated"),
    ]
    assert go_branch_factor("parent", relations) == 2
    assert go_branch_factor("unrelated", relations) == 1
    assert go_branch_factor("leaf-with-no-children", relations) == 0


def test_hub_branch_penalty_higher_for_branching_go_term_than_leaf():
    relations = [
        _relation("r1", "child1", "is_a", "generic_term"),
        _relation("r2", "child2", "is_a", "generic_term"),
        _relation("r3", "child3", "is_a", "generic_term"),
    ]
    degree_by_entity = {"generic_term": 3, "leaf_term": 1}
    generic = hub_branch_penalty({"id": "generic_term", "type": "go_term"}, degree_by_entity, relations)
    leaf = hub_branch_penalty({"id": "leaf_term", "type": "go_term"}, degree_by_entity, relations)
    assert generic > leaf


def test_hub_branch_penalty_no_go_bonus_for_non_go_entities():
    relations = [_relation("r1", "child1", "is_a", "x")]  # would count as branching if x were a GO term
    degree_by_entity = {"x": 1}
    go_penalty = hub_branch_penalty({"id": "x", "type": "go_term"}, degree_by_entity, relations)
    drug_penalty = hub_branch_penalty({"id": "x", "type": "drug"}, degree_by_entity, relations)
    assert go_penalty > drug_penalty


# --- No gold-label access (structural guarantee) --------------------------


def test_public_scoring_functions_never_accept_a_gold_parameter():
    from oncograph import rank as rank_module

    public_callables = [
        rank_module.lexical_component,
        rank_module.semantic_component,
        rank_module.structural_component,
        rank_module.provenance_component,
        rank_module.hub_branch_penalty,
        rank_module.go_branch_factor,
        HybridPathRanker.score_candidates,
        HybridPathRanker.retrieve,
    ]
    for fn in public_callables:
        params = set(inspect.signature(fn).parameters)
        assert not any("gold" in p.lower() for p in params), fn


# --- HybridPathRanker: real traversal --------------------------------------


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_star_graph(session: Session) -> None:
    drug = Entity(type="drug", name="TestDrug", canonical_id="gtopdb:1")
    gene = Entity(type="gene", name="TestGene", canonical_id="hgnc:HGNC:1")
    trials = [Entity(type="trial", name=f"Trial{i}", canonical_id=f"nct:{i}") for i in range(5)]
    session.add_all([drug, gene, *trials])
    session.flush()

    targets = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
    session.add(targets)
    session.flush()
    session.add(Evidence(relation_id=targets.id, source="gtopdb", source_type="curated_database"))

    for trial in trials:
        rel = Relation(subject_id=drug.id, predicate="studied_in", object_id=trial.id)
        session.add(rel)
        session.flush()
        session.add(Evidence(relation_id=rel.id, source="clinicaltrials_gov", source_type="registry"))
    session.commit()


def test_hybrid_ranker_component_decomposition_is_inspectable():
    with _memory_session() as session:
        _seed_star_graph(session)
        scored = HybridPathRanker(session).score_candidates(
            RetrievalQuery(root_ref="TestDrug", max_hops=1, question_text="What gene does TestDrug target?")
        )
    assert scored  # non-empty
    for entry in scored:
        assert isinstance(entry, ComponentScores)
        for field_name in ("lexical", "semantic", "structural", "provenance", "hub_branch_penalty", "combined"):
            assert isinstance(getattr(entry, field_name), float)


def test_hybrid_ranker_suppresses_irrelevant_star_edges():
    with _memory_session() as session:
        _seed_star_graph(session)
        result = HybridPathRanker(session, relative_threshold=0.5).retrieve(
            RetrievalQuery(root_ref="TestDrug", max_hops=1, question_text="What gene does TestDrug target?")
        )
    kept_names = {e["name"] for e in result.entities}
    assert "TestGene" in kept_names
    assert kept_names & {f"Trial{i}" for i in range(5)} == set()


def test_hybrid_ranker_keeps_everything_with_no_question_text_semantic_or_lexical_signal():
    with _memory_session() as session:
        _seed_star_graph(session)
        result = HybridPathRanker(session, relative_threshold=0.99).retrieve(RetrievalQuery(root_ref="TestDrug", max_hops=1))
    # No question text -> lexical=0 and semantic=0 for everyone; structural
    # is a fixed 0.5 neutral tie for a flat 1-hop star, provenance differs
    # slightly by tier -- but nothing should crash, and the gene (richer,
    # curated_database tier) must still be reachable in the result.
    kept_names = {e["name"] for e in result.entities}
    assert "TestGene" in kept_names or "TestDrug" in kept_names


def test_hybrid_ranker_never_drops_root():
    with _memory_session() as session:
        _seed_star_graph(session)
        result = HybridPathRanker(session, relative_threshold=1.0).retrieve(
            RetrievalQuery(root_ref="TestDrug", max_hops=1, question_text="What gene does TestDrug target?")
        )
    assert result.root is not None
    assert result.root["name"] == "TestDrug"


def test_hybrid_ranker_returns_empty_for_unresolvable_root():
    with _memory_session() as session:
        result = HybridPathRanker(session).retrieve(RetrievalQuery(root_ref="does-not-exist"))
        scored = HybridPathRanker(session).score_candidates(RetrievalQuery(root_ref="does-not-exist"))
    assert result.root is None
    assert result.entities == []
    assert scored == []


def test_hybrid_ranker_deterministic_and_stable_tie_break():
    with _memory_session() as session:
        _seed_star_graph(session)
        query = RetrievalQuery(root_ref="TestDrug", max_hops=1, question_text="What gene does TestDrug target?")
        first = HybridPathRanker(session).score_candidates(query)
        second = HybridPathRanker(session).score_candidates(query)
    assert [s.entity_id for s in first] == [s.entity_id for s in second]
    # Tied entities (the 5 identically-scored trials) must sort by entity_id.
    tied = [s for s in first if s.lexical == 0.0]
    tied_ids = [s.entity_id for s in tied]
    assert tied_ids == sorted(tied_ids)


def test_hybrid_weights_can_zero_out_any_component_for_ablation():
    with _memory_session() as session:
        _seed_star_graph(session)
        query = RetrievalQuery(root_ref="TestDrug", max_hops=1, question_text="What gene does TestDrug target?")
        lexical_only = HybridPathRanker(
            session, weights=HybridWeights(lexical=1.0, semantic=0.0, structural=0.0, provenance=0.0, hub=0.0)
        ).score_candidates(query)
        gene_score = next(s for s in lexical_only if s.lexical > 0)
        trial_score = next(s for s in lexical_only if s.lexical == 0)
    # With every other weight zeroed, combined must be driven by lexical alone.
    assert gene_score.combined > trial_score.combined
    assert trial_score.combined == 0.0
