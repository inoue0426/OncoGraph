"""Build a browser-searchable public entity+relation index."""

import json
import os
import sqlite3
from pathlib import Path

from oncograph.stats import BENCHMARKS_ROOT, compute_stats

DB_PATH = Path(os.getenv("ONCOGRAPH_SQLITE_PATH", "oncograph.db"))
ENTITIES_OUTPUT_PATH = Path("web/data/search-index.json")
RELATIONS_OUTPUT_PATH = Path("web/data/relations.json")
STATS_OUTPUT_PATH = Path("web/data/stats.json")


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
