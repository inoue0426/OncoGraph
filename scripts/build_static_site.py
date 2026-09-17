"""Build a browser-searchable public entity index."""

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("ONCOGRAPH_SQLITE_PATH", "oncograph.db"))
OUTPUT_PATH = Path("web/data/search-index.json")


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        OUTPUT_PATH.write_text("[]\n", encoding="utf-8")
        return
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT id, type, name, canonical_id FROM entity ORDER BY name"
        ).fetchall()
    finally:
        connection.close()
    OUTPUT_PATH.write_text(
        json.dumps([dict(row) for row in rows], separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
