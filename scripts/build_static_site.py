"""Build a browser-searchable public entity index."""

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("ONCOGRAPH_SQLITE_PATH", "oncograph.db"))
OUTPUT_PATH = Path("web/data/search-index.json")


def read_entities(database: Path) -> list[dict]:
    """Read public entity fields from a permitted SQLite snapshot.

    Args:
        database: SQLite snapshot to read.

    Returns:
        Public entity records, or an empty list when the snapshot is absent.
    """
    if not database.is_file():
        return []
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT id, type, name, canonical_id FROM entity ORDER BY name"
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def main() -> None:
    """Write the static search index."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(read_entities(DB_PATH), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
