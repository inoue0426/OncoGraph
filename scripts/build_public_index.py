"""Build the browser-searchable public entity index from a curated SQLite snapshot."""

import argparse
from pathlib import Path

from oncograph.public_index import build_index, write_index

DEFAULT_DATABASE = Path("data/public/oncograph.db")
DEFAULT_OUTPUT = Path("web/data/entities.json")


def parse_args() -> argparse.Namespace:
    """Parse public-index build options.

    Returns:
        Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--source-label",
        default="curated public graph snapshot",
        help="Non-sensitive description included in index provenance",
    )
    return parser.parse_args()


def main() -> None:
    """Build and write the public entity index."""
    args = parse_args()
    payload = build_index(args.database, args.source_label)
    write_index(payload, args.output)
    print(f"Wrote {payload['counts']['entities']} entities to {args.output}")


if __name__ == "__main__":
    main()
