"""Build a browser-searchable public entity+relation index."""

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("ONCOGRAPH_SQLITE_PATH", "oncograph.db"))
ENTITIES_OUTPUT_PATH = Path("web/data/search-index.json")
RELATIONS_OUTPUT_PATH = Path("web/data/relations.json")


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
        raw_metadata = row["entity_metadata"]
        entity["metadata"] = (
            json.loads(raw_metadata) if raw_metadata and row["type"] == "PAPER" else None
        )
        entities.append(entity)
    return entities


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
                   e.confidence, e.license, e.publication_id, e.context
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
                }
            )
    return list(relations.values())


def main() -> None:
    """Write the static search and relation indexes."""
    ENTITIES_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENTITIES_OUTPUT_PATH.write_text(
        json.dumps(read_entities(DB_PATH), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    RELATIONS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELATIONS_OUTPUT_PATH.write_text(
        json.dumps(read_relations(DB_PATH), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
