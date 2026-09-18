"""Small, read-only MCP resources -- metadata/documentation only, never the
graph itself (see docs/MCP.md). Each delegates to existing package state
(``oncograph.models`` enums, ``oncograph.sources.registry``,
``oncograph.stats``) rather than hand-maintaining a second copy.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from ..models import ClaimState, EntityType, VerificationStatus
from ..sources import registry
from .tools import get_graph_stats


def stats_resource() -> dict[str, Any]:
    """Current canonical graph coverage statistics -- identical to the
    ``get_graph_stats`` tool, exposed as a resource for clients that prefer
    to read it without an explicit tool call."""
    return get_graph_stats()


def schema_resource() -> dict[str, Any]:
    """The graph's entity-type vocabulary and evidence-quality enums.
    Predicates are an intentionally open vocabulary (different sources
    describe similar claims with different real predicate strings, see
    docs/EVIDENCE.md) -- not a fixed enum, so none is listed here as if
    exhaustive."""
    return {
        "entity_types": sorted(t.value for t in EntityType),
        "claim_states": sorted(s.value for s in ClaimState),
        "verification_statuses": sorted(s.value for s in VerificationStatus),
        "predicates": "Open vocabulary (free strings) -- see docs/EVIDENCE.md and docs/QUERY_API.md. "
        "Use get_entity/get_neighbors on a real entity to discover the predicates actually "
        "present for it, rather than assuming a fixed list.",
        "identifier_namespaces": "See oncograph.normalization.NAMESPACE_ALIASES and docs/EVIDENCE.md "
        "for the full, evolving list of normalized external-identifier namespaces (hgnc, "
        "chembl, mondo, clinicaltrials.gov, ...).",
    }


def sources_resource() -> dict[str, Any]:
    """Every registered source adapter's license/provenance descriptor
    (``oncograph.sources.registry``) -- includes adapters that are
    scaffold-only or not wired into the scheduled refresh; see
    docs/SOURCES.md, docs/BIOLOGICAL_SOURCES.md, docs/MECHANISTIC_SOURCES.md,
    and docs/TREATMENT_RESPONSE_CONTEXT.md for the full investigation notes
    behind each one."""
    descriptors = [
        {
            "key": d.key,
            "name": d.name,
            "homepage": d.homepage,
            "license": d.license,
            "license_url": d.license_url,
            "redistribution": d.redistribution.value,
            "source_type": d.source_type.value,
            "notes": d.notes,
        }
        for d in registry.descriptors()
    ]
    descriptors.sort(key=lambda d: d["key"])
    return {"sources": descriptors, "source_count": len(descriptors)}


def _package_version() -> str:
    try:
        return version("oncograph")
    except PackageNotFoundError:
        return "unknown (not installed as a package)"


def version_resource() -> dict[str, Any]:
    """The oncograph package version plus the deployed graph's own
    ``graph_version`` (the latest per-adapter --release label recorded in
    evidence, see oncograph.stats) -- two different, complementary notions
    of "version": code vs. data."""
    stats = get_graph_stats()
    return {
        "package_version": _package_version(),
        "graph_version": stats.get("graph_version"),
        "stats_generated_at": stats.get("generated_at"),
    }
