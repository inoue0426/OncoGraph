"""Build a browser-searchable public entity index from a curated SQLite snapshot."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INDEX_SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    """Calculate a file checksum without loading the file into memory.

    Args:
        path: File to hash.

    Returns:
        Lowercase SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_entities(database: Path) -> list[dict[str, Any]]:
    """Read public entity fields and evidence summary counts from SQLite.

    Args:
        database: Curated SQLite graph snapshot.

    Returns:
        JSON-serializable entity records sorted for deterministic output.

    Raises:
        ValueError: If the database does not contain the expected entity table.
    """
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'entity'"
        ).fetchone()
        if table is None:
            raise ValueError(f"SQLite snapshot has no entity table: {database}")

        rows = connection.execute(
            """
            WITH relation_summary AS (
                SELECT entity_id,
                       COUNT(DISTINCT relation_id) AS relation_count,
                       COUNT(evidence_id) AS evidence_count
                FROM (
                    SELECT relation.subject_id AS entity_id,
                           relation.id AS relation_id,
                           evidence.id AS evidence_id
                    FROM relation
                    LEFT JOIN evidence ON evidence.relation_id = relation.id
                    UNION ALL
                    SELECT relation.object_id AS entity_id,
                           relation.id AS relation_id,
                           evidence.id AS evidence_id
                    FROM relation
                    LEFT JOIN evidence ON evidence.relation_id = relation.id
                )
                GROUP BY entity_id
            )
            SELECT CAST(entity.id AS TEXT) AS id,
                   CAST(entity.type AS TEXT) AS type,
                   entity.name,
                   entity.canonical_id,
                   entity.description,
                   COALESCE(relation_summary.relation_count, 0) AS relation_count,
                   COALESCE(relation_summary.evidence_count, 0) AS evidence_count
            FROM entity
            LEFT JOIN relation_summary ON relation_summary.entity_id = entity.id
            ORDER BY lower(entity.name), entity.id
            """
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def build_index(database: Path, source_label: str) -> dict[str, Any]:
    """Create an index payload, returning a valid empty index when input is absent.

    Args:
        database: Curated public SQLite snapshot.
        source_label: Safe provenance label for the published snapshot.

    Returns:
        JSON-serializable index payload.
    """
    generated_at = datetime.now(UTC).isoformat()
    if not database.is_file():
        return {
            "schema_version": INDEX_SCHEMA_VERSION,
            "generated_at": generated_at,
            "source": {"label": source_label, "status": "not_found", "sha256": None},
            "counts": {"entities": 0},
            "entities": [],
        }

    entities = read_entities(database)
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": generated_at,
        "source": {
            "label": source_label,
            "status": "ready",
            "sha256": sha256_file(database),
        },
        "counts": {"entities": len(entities)},
        "entities": entities,
    }


def write_index(payload: dict[str, Any], output: Path) -> None:
    """Write a JSON index atomically.

    Args:
        payload: Public index payload.
        output: Destination JSON path.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
