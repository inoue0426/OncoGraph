"""Validate one permitted local Lewis Lab source without writing graph data.

Example:
  uv run python scripts/validate_lewis_source.py \
    lewis_ramilowski_2015 /data/Human-2015-Ramilowski-LR-pairs.txt \
    --identifier-map /data/human-symbol-map.tsv --out /tmp/lewis-report.json

The command never fetches upstream files and never opens a database session.
It exits with status 1 when rows were skipped, unresolved, ambiguous, or
otherwise invalid so a review/CI job cannot mistake a partial parse for a
clean source validation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from oncograph.sources import registry


def main() -> None:
    """Parse one local source and write its validation report as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Registered Lewis source key")
    parser.add_argument("path", type=Path, help="Permission-cleared local source file")
    parser.add_argument("--identifier-map", required=True, type=Path)
    parser.add_argument("--release", default=None)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    adapter_class = registry.get(args.source)
    adapter = adapter_class(args.path, args.identifier_map, release=args.release)
    entities = list(adapter.iter_entities())
    edges = list(adapter.iter_edges())
    report = adapter.validation_report()
    payload = report.to_dict()
    payload.update({"entities_emitted": len(entities), "edges_emitted": len(edges)})
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{args.source}: {report.input_rows} rows, {report.emitted_interactions} interactions, "
        f"{report.skipped_rows} skipped, {report.unresolved_identifiers} unresolved, "
        f"{report.ambiguous_identifiers} ambiguous"
    )
    if not report.valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
