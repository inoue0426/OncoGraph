"""oncograph.rank: query-conditioned relation/path selection.

Unit tests over synthetic data (fast) plus one real-traversal integration
test. No test here peeks at a benchmark item's gold answer/evidence when
scoring -- only question text and graph structure, matching the module's
own no-leakage design.
"""

from sqlmodel import Session, SQLModel, create_engine

from oncograph.models import Entity, Evidence, Relation
from oncograph.query import GraphRetriever, RetrievalQuery
from oncograph.rank import QueryConditionedRetriever, _tokenize, score_entity

# --- _tokenize -------------------------------------------------------------


def test_tokenize_lowercases_and_splits_on_non_alnum():
    assert _tokenize("What gene does gefitinib Target?") >= {"gene", "gefitinib", "target"}


def test_tokenize_strips_generic_stopwords_but_keeps_content_words():
    tokens = _tokenize("Which drugs are combined in the treatment tested in X?")
    assert "in" not in tokens
    assert "the" not in tokens
    assert "which" not in tokens
    assert "drug" in tokens  # stemmed content word survives
    assert "tested" in tokens
    assert "combined" in tokens


def test_tokenize_strips_trailing_s_for_basic_plural_matching():
    tokens = _tokenize("targets")
    assert "target" in tokens  # stemmed
    assert "targets" in tokens  # original kept too


def test_tokenize_handles_underscored_predicate_text():
    tokens = _tokenize("is_a".replace("_", " "))
    assert tokens >= {"is", "a"}


# --- score_entity ------------------------------------------------------------


def _relation(rel_id, subject_id, predicate, object_id, source_type="registry"):
    return {
        "id": rel_id,
        "subject_id": subject_id,
        "object_id": object_id,
        "predicate": predicate,
        "evidence": [{"source_type": source_type}],
    }


def test_score_entity_rewards_predicate_question_overlap():
    relations_by_id = {
        "r1": _relation("r1", "root", "targets", "gene1"),
        "r2": _relation("r2", "root", "studied_in", "trial1"),
    }
    degree_by_entity = {"root": 2, "gene1": 1, "trial1": 1}
    question_tokens = _tokenize("What gene does the drug target?")

    target_score = score_entity(question_tokens, ["r1"], relations_by_id, degree_by_entity)
    trial_score = score_entity(question_tokens, ["r2"], relations_by_id, degree_by_entity)
    assert target_score > trial_score


def test_score_entity_penalizes_high_local_degree():
    relations_by_id = {"r1": _relation("r1", "root", "studied_in", "trial1")}
    low_degree = score_entity(set(), ["r1"], relations_by_id, {"root": 2, "trial1": 2})
    high_degree = score_entity(set(), ["r1"], relations_by_id, {"root": 2, "trial1": 200})
    assert low_degree > high_degree


def test_score_entity_zero_for_root_itself_empty_path():
    assert score_entity({"x"}, [], {}, {}) == 0.0


def test_score_entity_rewards_curated_tier_over_computed():
    relations_by_id = {
        "r1": _relation("r1", "root", "associated_with", "gene1", source_type="curated_database"),
        "r2": _relation("r2", "root", "associated_with", "gene2", source_type="computed"),
    }
    degree_by_entity = {"root": 2, "gene1": 1, "gene2": 1}
    curated_score = score_entity(set(), ["r1"], relations_by_id, degree_by_entity)
    computed_score = score_entity(set(), ["r2"], relations_by_id, degree_by_entity)
    assert curated_score > computed_score


# --- QueryConditionedRetriever: real traversal --------------------------------


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_star_graph(session: Session) -> None:
    """One drug root with one relevant "targets" edge and several
    irrelevant "studied_in" edges -- the exact star shape that degraded
    citation_correctness in docs/BENCHMARK_RUN_v3.md."""
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


def test_query_conditioned_retriever_suppresses_irrelevant_star_edges():
    with _memory_session() as session:
        _seed_star_graph(session)
        result = QueryConditionedRetriever(session, relative_threshold=0.5).retrieve(
            RetrievalQuery(root_ref="TestDrug", max_hops=1, question_text="What gene does TestDrug target?")
        )
    kept_names = {e["name"] for e in result.entities}
    assert "TestGene" in kept_names
    assert kept_names & {f"Trial{i}" for i in range(5)} == set()  # all 5 irrelevant trials dropped


def test_query_conditioned_retriever_keeps_everything_with_no_question_text():
    """No question text -> no lexical signal -> honest fallback: keep the
    whole neighborhood, same recall as GraphRetriever."""
    with _memory_session() as session:
        _seed_star_graph(session)
        ranked = QueryConditionedRetriever(session, relative_threshold=0.5).retrieve(
            RetrievalQuery(root_ref="TestDrug", max_hops=1)
        )
        aware = GraphRetriever(session).retrieve(RetrievalQuery(root_ref="TestDrug", max_hops=1))
    assert {e["id"] for e in ranked.entities} == {e["id"] for e in aware.entities}


def test_query_conditioned_retriever_returns_empty_result_for_unresolvable_root():
    with _memory_session() as session:
        result = QueryConditionedRetriever(session).retrieve(RetrievalQuery(root_ref="does-not-exist"))
    assert result.root is None
    assert result.entities == []


def test_query_conditioned_retriever_never_drops_root_even_at_max_threshold():
    with _memory_session() as session:
        _seed_star_graph(session)
        result = QueryConditionedRetriever(session, relative_threshold=1.0).retrieve(
            RetrievalQuery(root_ref="TestDrug", max_hops=1, question_text="What gene does TestDrug target?")
        )
    assert result.root is not None
    assert result.root["name"] == "TestDrug"
