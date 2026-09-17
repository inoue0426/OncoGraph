"""Build a browser-searchable public entity+relation index."""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DB_PATH = Path(os.getenv("ONCOGRAPH_SQLITE_PATH", "oncograph.db"))
ENTITIES_OUTPUT_PATH = Path("web/data/search-index.json")
RELATIONS_OUTPUT_PATH = Path("web/data/relations.json")
STATS_OUTPUT_PATH = Path("web/data/stats.json")
BENCHMARKS_ROOT = Path("data/benchmarks")


def read_entities(database: Path) -> list[dict]:
    """Read public entity fields from a permitted SQLite snapshot.

    Args:
        database: SQLite snapshot to read.

    Returns:
        Public entity records, or an empty list when the snapshot is absent.
        ``entity_metadata`` is only included for Publication ("PAPER")
        entities -- kept out of the export for other entity types so this
        stays a targeted addition rather than growing every entity's payload.
    """
    if not database.is_file():
        return []
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT id, type, name, canonical_id, description, entity_metadata "
            "FROM entity ORDER BY name"
        ).fetchall()
    finally:
        connection.close()

    entities = []
    for row in rows:
        entity = {key: row[key] for key in ("id", "type", "name", "canonical_id", "description")}
        entity["metadata"] = _exported_metadata(row["type"], row["entity_metadata"])
        entities.append(entity)
    return entities


def _exported_metadata(entity_type: str, raw_metadata: str | None) -> dict | None:
    """Type-specific allowlist so the export stays small for large entity types.

    Publications export their whole metadata blob (small population). Genes
    export only "aliases" (issue #8 wants alias search/display) -- not the
    rest of HGNC's per-gene metadata, which would meaningfully grow the
    export across ~45k gene entities for no UI benefit yet.
    """
    if not raw_metadata:
        return None
    metadata = json.loads(raw_metadata)
    if entity_type == "PAPER":
        return metadata
    if entity_type == "GENE":
        aliases = metadata.get("aliases")
        return {"aliases": aliases} if aliases else None
    return None


def read_relations(database: Path) -> list[dict]:
    """Read public relation and evidence fields from a permitted SQLite snapshot.

    Args:
        database: SQLite snapshot to read.

    Returns:
        Public relation records, each with its evidence list, or an empty
        list when the snapshot is absent.
    """
    if not database.is_file():
        return []
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT r.id AS relation_id, r.subject_id, r.predicate, r.object_id,
                   e.source, e.source_id, e.source_url, e.source_type, e.evidence_type,
                   e.confidence, e.license, e.publication_id, e.context,
                   e.claim_state, e.verification_status, e.retrieved_at
            FROM relation r
            LEFT JOIN evidence e ON e.relation_id = r.id
            ORDER BY r.id
            """
        ).fetchall()
    finally:
        connection.close()

    relations: dict[str, dict] = {}
    for row in rows:
        relation = relations.setdefault(
            row["relation_id"],
            {
                "subject_id": row["subject_id"],
                "predicate": row["predicate"],
                "object_id": row["object_id"],
                "evidence": [],
            },
        )
        if row["source"] is not None:
            context = json.loads(row["context"]) if row["context"] else None
            relation["evidence"].append(
                {
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "source_url": row["source_url"],
                    "source_type": row["source_type"],
                    "evidence_type": row["evidence_type"],
                    "confidence": row["confidence"],
                    "license": row["license"],
                    "publication_id": row["publication_id"],
                    "context": context,
                    "claim_state": row["claim_state"],
                    "verification_status": row["verification_status"],
                    "retrieved_at": row["retrieved_at"],
                }
            )
    return list(relations.values())


def compute_entity_counts(entities: list[dict]) -> dict[str, int]:
    """Canonical entity counts by type, from the already-deduplicated export.

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
    """Build the stats.json payload from the same in-memory export used for the site.

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
    paths = read_benchmark_gold_paths(benchmarks_root)
    if paths:
        stats["paths"] = paths
    return stats


def main() -> None:
    """Write the static search, relation, and stats indexes."""
    entities = read_entities(DB_PATH)
    relations = read_relations(DB_PATH)

    ENTITIES_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENTITIES_OUTPUT_PATH.write_text(
        json.dumps(entities, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    RELATIONS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELATIONS_OUTPUT_PATH.write_text(
        json.dumps(relations, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    STATS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_OUTPUT_PATH.write_text(
        json.dumps(
            compute_stats(entities, relations, benchmarks_root=BENCHMARKS_ROOT),
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
