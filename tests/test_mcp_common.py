"""oncograph.mcp._common: shared validation/limit/retrieval-strategy helpers."""

import pytest
from sqlmodel import Session, SQLModel, create_engine

from oncograph.mcp._common import (
    DEFAULT_RETRIEVAL_STRATEGY,
    MAX_HOPS,
    MAX_RESULT_LIMIT,
    RETRIEVAL_STRATEGIES,
    OncoGraphMCPError,
    clamp_hops,
    clamp_limit,
    entity_public_dict,
    make_retriever,
    validate_entity_type,
)
from oncograph.models import Entity
from oncograph.query import GraphRetriever
from oncograph.rank import HybridPathRanker, QueryConditionedRetriever


def test_clamp_limit_caps_at_max_result_limit():
    assert clamp_limit(MAX_RESULT_LIMIT + 1000) == MAX_RESULT_LIMIT


def test_clamp_limit_passes_through_within_range():
    assert clamp_limit(5) == 5


def test_clamp_limit_rejects_non_positive():
    with pytest.raises(OncoGraphMCPError):
        clamp_limit(0)
    with pytest.raises(OncoGraphMCPError):
        clamp_limit(-1)


def test_clamp_hops_caps_at_max_hops():
    assert clamp_hops(999) == MAX_HOPS
    assert MAX_HOPS == 5


def test_clamp_hops_rejects_non_positive():
    with pytest.raises(OncoGraphMCPError):
        clamp_hops(0)


def test_validate_entity_type_normalizes_case():
    assert validate_entity_type("DRUG") == "drug"
    assert validate_entity_type(None) is None


def test_validate_entity_type_rejects_unknown_type():
    with pytest.raises(OncoGraphMCPError, match="Unknown entity_type"):
        validate_entity_type("not_a_real_type")


def test_default_retrieval_strategy_is_query_conditioned():
    assert DEFAULT_RETRIEVAL_STRATEGY == "query_conditioned"
    assert DEFAULT_RETRIEVAL_STRATEGY in RETRIEVAL_STRATEGIES


def test_hybrid_experimental_is_a_valid_but_non_default_strategy():
    assert "hybrid_experimental" in RETRIEVAL_STRATEGIES
    assert "hybrid_experimental" != DEFAULT_RETRIEVAL_STRATEGY


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_make_retriever_maps_graph_strategy():
    with _memory_session() as session:
        retriever = make_retriever(session, "graph")
    assert isinstance(retriever, GraphRetriever)


def test_make_retriever_maps_query_conditioned_strategy():
    with _memory_session() as session:
        retriever = make_retriever(session, "query_conditioned")
    assert isinstance(retriever, QueryConditionedRetriever)


def test_make_retriever_maps_hybrid_experimental_strategy():
    with _memory_session() as session:
        retriever = make_retriever(session, "hybrid_experimental")
    assert isinstance(retriever, HybridPathRanker)


def test_make_retriever_rejects_unknown_strategy():
    with _memory_session() as session, pytest.raises(OncoGraphMCPError, match="Unknown retrieval_strategy"):
        make_retriever(session, "made_up_strategy")


def test_make_retriever_never_returns_hybrid_for_default_or_graph_or_query_conditioned():
    with _memory_session() as session:
        for strategy in ("graph", "query_conditioned"):
            assert not isinstance(make_retriever(session, strategy), HybridPathRanker)


def test_entity_public_dict_decodes_metadata_and_aliases():
    entity = Entity(type="gene", name="EGFR", canonical_id="hgnc:HGNC:3236", entity_metadata='{"aliases": ["ERBB1"]}')
    result = entity_public_dict(entity)
    assert result["aliases"] == ["ERBB1"]
    assert result["metadata"] == {"aliases": ["ERBB1"]}


def test_entity_public_dict_handles_missing_metadata_gracefully():
    entity = Entity(type="drug", name="TestDrug", canonical_id="gtopdb:1")
    result = entity_public_dict(entity)
    assert result["aliases"] is None
    assert result["metadata"] is None
