"""Backward-compatible entry point for building the public entity index."""

import os
from pathlib import Path

from oncograph.public_index import build_index, write_index

DB_PATH = Path(os.getenv("ONCOGRAPH_SQLITE_PATH", "oncograph.db"))
OUTPUT_PATH = Path("web/data/entities.json")


def main() -> None:
    """Build the new public index using the legacy environment variable."""
    payload = build_index(DB_PATH, "curated public graph snapshot")
    write_index(payload, OUTPUT_PATH)
    print(f"Wrote {payload['counts']['entities']} entities to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
