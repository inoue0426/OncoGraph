"""Shared helpers for the MCP tool layer -- session management, validation,
limits, and retrieval-strategy selection. No graph/query logic lives here;
everything delegates to oncograph.query / oncograph.rank / oncograph.benchmark.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager

from sqlmodel import Session

from ..db import engine
from ..models import EntityType
from ..query import GraphRetriever, Retriever
from ..rank import HybridPathRanker, QueryConditionedRetriever

# Hard caps -- every tool clamps to these regardless of what a caller asks
# for, so a single call can never dump the whole graph.
MAX_RESULT_LIMIT = 200
MAX_HOPS = 5

# The relative_threshold value dev-calibrated and held-out-validated in
# docs/BENCHMARK_RUN_v3_ranked.md/docs/BENCHMARK_RUN_v3_hybrid.md -- reused
# here rather than oncograph.rank's own generic DEFAULT_RELATIVE_THRESHOLD
# (0.5), which was never itself validated as a good operating point.
VALIDATED_RELATIVE_THRESHOLD = 0.3

# "graph" (evidence-aware, no ranking) and "query_conditioned" (lexical
# ranking, dev-calibrated and held-out-validated -- see
# docs/BENCHMARK_RUN_v3_ranked.md) are both safe defaults/choices.
# "hybrid_experimental" (docs/BENCHMARK_RUN_v3_hybrid.md) underperformed
# query_conditioned and regressed answer coverage on held-out in its own
# evaluation -- it is offered for callers who explicitly want to try it,
# never chosen automatically.
DEFAULT_RETRIEVAL_STRATEGY = "query_conditioned"
RETRIEVAL_STRATEGIES = ("graph", "query_conditioned", "hybrid_experimental")

VALID_ENTITY_TYPES = frozenset(t.value for t in EntityType)


class OncoGraphMCPError(ValueError):
    """A validation failure a tool caught and wants reported back cleanly
    (unknown entity, invalid entity type, invalid retrieval strategy, ...).
    Tool wrappers in server.py convert this to an MCP ToolError."""


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """One Session per tool call -- mirrors oncograph.db.get_session's
    per-request lifecycle, adapted for MCP's request/response tool calls
    rather than FastAPI's dependency injection."""
    with Session(engine) as session:
        yield session


def clamp_limit(limit: int, maximum: int = MAX_RESULT_LIMIT) -> int:
    if limit < 1:
        raise OncoGraphMCPError(f"limit must be >= 1, got {limit}")
    return min(limit, maximum)


def clamp_hops(max_hops: int, maximum: int = MAX_HOPS) -> int:
    if max_hops < 1:
        raise OncoGraphMCPError(f"max_hops must be >= 1, got {max_hops}")
    return min(max_hops, maximum)


def validate_entity_type(entity_type: str | None) -> str | None:
    if entity_type is None:
        return None
    normalized = entity_type.strip().lower()
    if normalized not in VALID_ENTITY_TYPES:
        raise OncoGraphMCPError(
            f"Unknown entity_type {entity_type!r}. Valid values: {sorted(VALID_ENTITY_TYPES)}"
        )
    return normalized


def make_retriever(session: Session, strategy: str) -> Retriever:
    """Build the requested Retriever. Never falls back silently -- an
    unrecognized strategy name is a validation error (OncoGraphMCPError),
    not a quiet default."""
    if strategy not in RETRIEVAL_STRATEGIES:
        raise OncoGraphMCPError(
            f"Unknown retrieval_strategy {strategy!r}. Valid values: {list(RETRIEVAL_STRATEGIES)}"
        )
    if strategy == "graph":
        return GraphRetriever(session)
    if strategy == "query_conditioned":
        return QueryConditionedRetriever(session, relative_threshold=VALIDATED_RELATIVE_THRESHOLD)
    return HybridPathRanker(session, relative_threshold=VALIDATED_RELATIVE_THRESHOLD)


def entity_public_dict(entity) -> dict:
    """The public-facing shape for one Entity row -- name/canonical_id/type
    plus decoded metadata (aliases, etc.), never the raw ORM object."""
    metadata = json.loads(entity.entity_metadata) if entity.entity_metadata else None
    return {
        "id": str(entity.id),
        "type": str(entity.type).lower(),
        "name": entity.name,
        "canonical_id": entity.canonical_id,
        "description": entity.description,
        "aliases": (metadata or {}).get("aliases") if isinstance(metadata, dict) else None,
        "metadata": metadata,
    }
