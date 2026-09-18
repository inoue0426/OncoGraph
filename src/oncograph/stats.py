"""Canonical knowledge-graph coverage statistics (Issue #12).

Pure functions over already-exported entity/relation dicts (the same shape
``scripts/build_static_site.py``'s ``read_entities``/``read_relations``
produce from a SQLite snapshot, and the MCP layer's ``get_graph_stats``
tool produces from a live session) -- this module has no I/O of its own,
so it works identically against a frozen static export or a live database.
Moved here (out of ``scripts/build_static_site.py``) so both the static
site build and ``oncograph.mcp`` can reuse the exact same counting logic
without duplicating it; ``scripts/build_static_site.py`` re-exports these
names for backward compatibility with its own CLI and existing tests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

BENCHMARKS_ROOT = Path("data/benchmarks")


def compute_entity_counts(entities: list[dict]) -> dict[str, int]:
    """Canonical entity counts by type, from an already-deduplicated export.

    Each row in ``entities`` is one canonical Entity (import-time dedup keys
    on ``canonical_id``; aliases live inside a Gene's ``metadata.aliases``,
    never as separate rows) -- so this is a plain group-by, not a dedup step.
    """
    counts: dict[str, int] = {}
    for entity in entities:
        entity_type = entity["type"].lower()
        counts[entity_type] = counts.get(entity_type, 0) + 1
    counts["total"] = len(entities)
    return counts


def compute_relation_stats(relations: list[dict]) -> dict[str, int]:
    """Relation/evidence/source counts, kept distinct from entity counts.

    ``evidence_records`` counts individual Evidence rows (a relation can
    carry several, one per contributing source); ``sources`` counts the
    distinct ``evidence.source`` values actually present, i.e. adapters
    that contributed data to this deployed snapshot -- not the full adapter
    registry, some of which (Reactome/CIViC/DGIdb/OncoKB/drug_response) are
    not wired into the scheduled refresh (see docs/BIOLOGICAL_SOURCES.md).
    """
    evidence_records = 0
    sources: set[str] = set()
    for relation in relations:
        for evidence in relation["evidence"]:
            evidence_records += 1
            if evidence.get("source"):
                sources.add(evidence["source"])
    return {
        "relations": len(relations),
        "evidence_records": evidence_records,
        "sources": len(sources),
    }


def read_benchmark_gold_paths(root: Path = BENCHMARKS_ROOT) -> dict[str, int] | None:
    """Count explicit curated path records from the versioned benchmark suite.

    A "path" here is one BenchmarkItem's non-empty ``gold_evidence_path`` --
    a stored, human-curated evidence chain used for benchmark grading (see
    docs/BENCHMARKING.md) -- never the count of all mathematically possible
    graph traversal paths, which is combinatorial and not a coverage metric.

    Returns ``None`` (not zero) when no benchmark file exists yet, so the
    caller can omit the "paths" stat entirely instead of showing a
    misleading count. Deduplicates by (version, item id) in case the same
    curated item ever appears in more than one benchmark file.

    A benchmark *version* directory can also hold non-item artifacts (e.g.
    ``run_benchmark.py``'s results logs, a single JSON object rather than a
    list of items) -- those are skipped rather than treated as items.
    """
    if not root.is_dir():
        return None
    seen: set[tuple[str, str]] = set()
    for file in sorted(root.glob("**/*.json")):
        items = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            continue  # not a benchmark-item file, e.g. a results log
        for item in items:
            if isinstance(item, dict) and item.get("gold_evidence_path"):
                seen.add((item.get("version") or file.parent.name, item["id"]))
    if not seen:
        return None
    return {"benchmark_gold": len(seen), "total": len(seen)}


def count_mechanistic_paths(relations: list[dict]) -> int:
    """Count real, stored mechanistic path records (DrugMechDB, Issue #10).

    Each ``implicated_in_mechanism_for`` relation carries its *entire*
    drug -> ... -> disease mechanism chain in its evidence context (see
    ``sources/drugmechdb.py``) -- this is a genuine curated path record,
    not a traversal computed at query time, so it belongs in the same
    ``paths`` accounting as the benchmark's gold-evidence paths.
    """
    return sum(1 for relation in relations if relation.get("predicate") == "implicated_in_mechanism_for")


def _graph_version(relations: list[dict]) -> str | None:
    """The latest per-adapter ``--release`` label recorded on any evidence row.

    Every source adapter accepts a caller-supplied ``release`` string (see
    ``oncograph import-source --release``, set to the refresh run's UTC
    timestamp in ``refresh-data.yml``) and stores it in ``evidence.context``.
    Reusing it here means stats.json's version label always matches the
    data it was actually built from, with no separate versioning scheme.
    """
    releases = {
        (relation_evidence.get("context") or {}).get("release")
        for relation in relations
        for relation_evidence in relation["evidence"]
    }
    releases.discard(None)
    return max(releases) if releases else None


def compute_stats(entities: list[dict], relations: list[dict], benchmarks_root: Path = BENCHMARKS_ROOT) -> dict:
    """Build the stats.json payload from an in-memory entity/relation export.

    Deliberately does not emit a category with no real data behind it (e.g.
    "publication" or "paths" when neither exists in the current snapshot) --
    see Issue #12: never fabricate a zero-valued stat just to fill a schema.
    """
    stats: dict = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "entities": compute_entity_counts(entities),
    }
    graph_version = _graph_version(relations)
    if graph_version:
        stats["graph_version"] = graph_version
    stats.update(compute_relation_stats(relations))

    paths: dict[str, int] = {}
    gold_paths = read_benchmark_gold_paths(benchmarks_root)
    if gold_paths:
        paths["benchmark_gold"] = gold_paths["benchmark_gold"]
    mechanistic_paths = count_mechanistic_paths(relations)
    if mechanistic_paths:
        paths["mechanistic"] = mechanistic_paths
    if paths:
        paths["total"] = sum(paths.values())
        stats["paths"] = paths
    return stats


__all__ = [
    "BENCHMARKS_ROOT",
    "compute_entity_counts",
    "compute_relation_stats",
    "compute_stats",
    "count_mechanistic_paths",
    "read_benchmark_gold_paths",
]
