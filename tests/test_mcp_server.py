"""oncograph.mcp.server: MCP server registration and end-to-end tool calls
over the real MCPServer object (still no network/stdio transport, no live
external calls -- oncograph.mcp.server.mcp.call_tool() is an in-process
call). Uses a small seeded in-memory database, matching test_mcp_tools.py's
fixture style.
"""

import asyncio
import tempfile

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlmodel import Session, SQLModel, create_engine

import oncograph.mcp._common as common_module
from oncograph.mcp.server import mcp
from oncograph.models import Entity, Evidence, Relation

EXPECTED_TOOL_NAMES = {
    "search_entities",
    "get_entity",
    "get_neighbors",
    "get_evidence",
    "traverse_graph",
    "find_drugs_for_disease",
    "find_trials",
    "find_drug_mechanism",
    "find_mechanism_paths",
    "find_combination_treatments",
    "find_contextual_response_evidence",
    "get_graph_stats",
}

EXPECTED_RESOURCE_URIS = {
    "oncograph://stats",
    "oncograph://schema",
    "oncograph://sources",
    "oncograph://version",
}


def _run(coro):
    return asyncio.run(coro)


def test_server_registers_every_required_tool():
    tools = _run(mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOL_NAMES


def test_server_registers_every_required_resource():
    resources = _run(mcp.list_resources())
    assert {str(r.uri) for r in resources} == EXPECTED_RESOURCE_URIS


def test_server_name_and_instructions_mention_research_use_only():
    assert mcp.name == "oncograph"
    assert "research" in mcp.instructions.lower()


@pytest.fixture
def seeded_engine(monkeypatch):
    # A pure in-memory "sqlite://" DB is per-connection -- session_scope()
    # opens a fresh Session(engine) per tool call and would see an empty,
    # tableless database. A file-based temp DB is shared across connections.
    engine = create_engine(f"sqlite:///{tempfile.mktemp(suffix='.db')}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        drug = Entity(type="drug", name="TestDrug", canonical_id="gtopdb:1")
        gene = Entity(type="gene", name="TestGene", canonical_id="hgnc:HGNC:1")
        session.add_all([drug, gene])
        session.flush()
        relation = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
        session.add(relation)
        session.flush()
        session.add(Evidence(relation_id=relation.id, source="gtopdb", source_type="curated_database", evidence_type="target_interaction"))
        session.commit()
    monkeypatch.setattr(common_module, "engine", engine)
    return engine


def test_search_entities_tool_call_end_to_end(seeded_engine):
    result = _run(mcp.call_tool("search_entities", {"query": "TestDrug"}))
    assert result.is_error is False
    assert result.structured_content["results"][0]["canonical_id"] == "gtopdb:1"


def test_traverse_graph_defaults_to_query_conditioned_over_the_wire(seeded_engine):
    result = _run(mcp.call_tool("traverse_graph", {"entity_id": "gtopdb:1"}))
    assert result.is_error is False
    assert result.structured_content["retrieval_strategy"] == "query_conditioned"


def test_traverse_graph_never_uses_hybrid_experimental_unless_explicitly_requested(seeded_engine):
    # No retrieval_strategy argument at all -- the tool's own default applies.
    result = _run(mcp.call_tool("traverse_graph", {"entity_id": "gtopdb:1", "max_hops": 2}))
    assert result.structured_content["retrieval_strategy"] != "hybrid_experimental"

    # Explicitly requesting it is the only way it is used.
    explicit = _run(
        mcp.call_tool("traverse_graph", {"entity_id": "gtopdb:1", "max_hops": 2, "retrieval_strategy": "hybrid_experimental"})
    )
    assert explicit.structured_content["retrieval_strategy"] == "hybrid_experimental"


def test_unknown_entity_raises_tool_error_over_the_wire(seeded_engine):
    with pytest.raises(ToolError, match="No entity found"):
        _run(mcp.call_tool("get_entity", {"entity_id": "does-not-exist"}))


def test_invalid_entity_type_raises_tool_error_over_the_wire(seeded_engine):
    with pytest.raises(ToolError, match="Unknown entity_type"):
        _run(mcp.call_tool("search_entities", {"query": "x", "entity_type": "not_a_type"}))


def test_hop_limit_is_enforced_over_the_wire(seeded_engine):
    result = _run(mcp.call_tool("traverse_graph", {"entity_id": "gtopdb:1", "max_hops": 999}))
    assert result.structured_content["max_hops"] == 5


def test_result_limit_is_enforced_over_the_wire(seeded_engine):
    result = _run(mcp.call_tool("search_entities", {"query": "Test", "limit": 100000}))
    # Clamped internally; must not error and must not return an absurd count
    # (there are only 2 entities in the fixture either way).
    assert result.is_error is False
    assert len(result.structured_content["results"]) <= 2


def test_get_graph_stats_tool_call_end_to_end(seeded_engine):
    result = _run(mcp.call_tool("get_graph_stats", {}))
    assert result.is_error is False
    assert result.structured_content["entities"]["drug"] == 1
    assert result.structured_content["relations"] == 1
