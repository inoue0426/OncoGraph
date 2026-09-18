"""OncoGraph MCP server: registers the tools/resources in ``tools.py``/
``resources.py`` with the official MCP Python SDK (``mcp``, stdio
transport) and provides the ``oncograph-mcp`` / ``python -m
oncograph.mcp.server`` entry point.

This module only wires things together -- no graph/query logic lives here.
See docs/MCP.md for the full tool/resource reference, provenance
semantics, and research-use-only disclaimer.
"""

from __future__ import annotations

import functools

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import resources, tools
from ._common import OncoGraphMCPError

INSTRUCTIONS = """\
OncoGraph is a research-only, evidence-first oncology knowledge graph. \
Every tool call returns structured data with provenance (source, \
evidence_type, claim_state, verification_status) attached -- treat a \
relation's predicate literally (e.g. "studied_in" is trial registration, \
not proven efficacy; "associated_with" is not "causes"). Do not present \
tool output as medical advice or a clinical recommendation. The default \
retrieval_strategy ("query_conditioned") is the one validated on this \
project's own benchmark (docs/BENCHMARK_RUN_v3_ranked.md); \
"hybrid_experimental" is offered for comparison only and is documented to \
underperform on that same benchmark (docs/BENCHMARK_RUN_v3_hybrid.md) -- \
never switch to it silently on a caller's behalf.\
"""

mcp = MCPServer(
    name="oncograph",
    title="OncoGraph",
    description="Evidence-first oncology knowledge graph -- research use only.",
    instructions=INSTRUCTIONS,
)

_TOOLS = (
    tools.search_entities,
    tools.get_entity,
    tools.get_neighbors,
    tools.get_evidence,
    tools.traverse_graph,
    tools.find_drugs_for_disease,
    tools.find_trials,
    tools.find_drug_mechanism,
    tools.find_mechanism_paths,
    tools.find_combination_treatments,
    tools.find_contextual_response_evidence,
    tools.get_graph_stats,
)

_RESOURCES = (
    ("oncograph://stats", resources.stats_resource, "Graph coverage statistics"),
    ("oncograph://schema", resources.schema_resource, "Entity-type and evidence-quality vocabulary"),
    ("oncograph://sources", resources.sources_resource, "Registered source adapters and their licensing"),
    ("oncograph://version", resources.version_resource, "Package and graph data version"),
)


def _wrap_validation_errors(fn):
    """OncoGraphMCPError (invalid entity/type/strategy/limit/hops, unknown
    entity) becomes a ToolError -- the MCP SDK returns it to the caller as
    a structured, anticipated tool failure (is_error=True with the
    message), never a raw traceback.

    ``functools.wraps`` (not a manual attribute copy) is required here: it
    sets ``__wrapped__``, which makes ``inspect.signature(..., follow_wrapped=True)``
    -- what the MCP SDK uses to build each tool's schema -- resolve straight
    through to ``fn``. ``tools.py`` uses ``from __future__ import
    annotations`` (so every annotation is a string, evaluated against the
    function's own ``__globals__``); without following through to ``fn``,
    the SDK would instead try to evaluate ``tools.py``'s annotations against
    *this* module's globals, which don't import the same names (e.g. ``Any``)
    and would fail.
    """

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except OncoGraphMCPError as exc:
            raise ToolError(str(exc)) from exc

    return wrapped


for _tool_fn in _TOOLS:
    mcp.add_tool(_wrap_validation_errors(_tool_fn))

for _uri, _resource_fn, _description in _RESOURCES:
    mcp.resource(_uri, description=_description)(_resource_fn)


def main() -> None:
    """Entry point for ``oncograph-mcp`` / ``python -m oncograph.mcp.server``.
    Runs the stdio MCP transport (the only transport this pass supports --
    see docs/MCP.md)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
