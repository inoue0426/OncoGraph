"""OncoGraph MCP server package.

A thin Model Context Protocol layer over the existing ``oncograph.query``/
``oncograph.rank``/``oncograph.stats`` graph API -- see docs/MCP.md.

    python -m oncograph.mcp.server
    # or, once installed:
    oncograph-mcp

Deliberately does not import ``oncograph.mcp.server`` here: doing so would
make ``python -m oncograph.mcp.server`` re-import that module under a
second name (Python warns "found in sys.modules ... prior to execution").
Import ``oncograph.mcp.server`` directly (``from oncograph.mcp.server
import mcp, main``) when you need the ``MCPServer`` instance or the entry
point from other code.
"""
