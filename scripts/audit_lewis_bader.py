"""Audit a local Lewis/BaderLab gzip table without creating graph records.

Usage: uv run python scripts/audit_lewis_bader.py /path/to/source.txt.zip

JSON is written to stdout. Exit 0 means the audit completed, not that the
source is importable. No identifiers, species, or LR directions are inferred.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

EXPECTED_COLUMNS = (
    "AliasA",
    "AliasB",
    "uidA",
    "uidB",
    "altA",
    "altB",
    "aliasA",
    "aliasB",
    "method",
    "author",
    "pmids",
    "taxa",
    "taxb",
    "interactionType",
    "sourcedb",
    "interactionIdentifier",
    "confidence",
)
TAXON_PATTERN = re.compile(r"taxid:(\d+)(?:\([^()]+\))?")
MISSING_VALUES = {"", "-"}
UNASSESSED_ROLES = (
    "Endpoint roles and ligand-to-receptor direction require a version-matched "
    "role map; AliasA/AliasB are molecule aliases, not ligand/receptor columns."
)


def file_sha256(path: Path) -> str:
    """Fingerprint the compressed source bytes.

    Args:
        path: Local source file.

    Returns:
        SHA-256 digest.
    """
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def taxon_status(value: str) -> str:
    """Classify explicit taxonomy without consulting aliases or folder names.

    Args:
        value: Raw MITAB taxon field, optionally containing pipe-separated terms.

    Returns:
        Human, nonhuman, missing, or malformed status. Mixed species are nonhuman.
    """
    value = value.strip()
    if value in MISSING_VALUES:
        return "missing"
    matches = [TAXON_PATTERN.fullmatch(term.strip()) for term in value.split("|")]
    if not all(matches):
        return "malformed"
    return "human" if all(match.group(1) == "9606" for match in matches) else "nonhuman"


def audit_source(path: Path) -> dict[str, object]:
    """Count source-shape, taxonomy, and provenance diagnostics in one pass.

    Args:
        path: Local gzip-compressed BaderLab table, including ZIP-suffixed files.

    Returns:
        Aggregate diagnostics with separate audit and import-readiness status.

    Raises:
        ValueError: The compression, header, or input stability check fails.
    """
    digest = file_sha256(path)
    with path.open("rb") as handle:
        if handle.read(2) != b"\x1f\x8b":
            raise ValueError("Expected a gzip payload, even when the suffix is .zip")
    widths: Counter[int] = Counter()
    taxon_pairs: Counter[str] = Counter()
    interaction_types: Counter[str] = Counter()
    missing_fields: Counter[str] = Counter()
    row_count = 0
    self_alias_rows = 0
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", strict=True)
        if tuple(next(reader, ())) != EXPECTED_COLUMNS:
            raise ValueError("Unexpected BaderLab columns or column order")
        for values in reader:
            row_count += 1
            widths[len(values)] += 1
            if len(values) != len(EXPECTED_COLUMNS):
                continue
            row = dict(zip(EXPECTED_COLUMNS, values, strict=True))
            # Keep source endpoint order; a taxonomy match does not establish LR roles.
            pair = f"{taxon_status(row['taxa'])}/{taxon_status(row['taxb'])}"
            taxon_pairs[pair] += 1
            interaction_types[row["interactionType"].strip() or "<empty>"] += 1
            for field in (
                "AliasA",
                "AliasB",
                "uidA",
                "uidB",
                "pmids",
                "sourcedb",
                "interactionIdentifier",
                "interactionType",
            ):
                if row[field].strip() in MISSING_VALUES:
                    missing_fields[field] += 1
            alias_a, alias_b = row["AliasA"].strip(), row["AliasB"].strip()
            if alias_a not in MISSING_VALUES and alias_a == alias_b:
                self_alias_rows += 1
    if file_sha256(path) != digest:
        raise ValueError("Source changed during the audit")
    well_formed = widths[len(EXPECTED_COLUMNS)]
    return {
        "audit_complete": True,
        "import_ready": False,
        "source_file": path.name,
        "source_sha256": digest,
        "archive_format": "gzip-delimited",
        "input_rows": row_count,
        "row_width_counts": {str(key): value for key, value in sorted(widths.items())},
        "well_formed_rows": well_formed,
        "malformed_width_rows": row_count - well_formed,
        "taxon_pair_counts": dict(sorted(taxon_pairs.items())),
        "explicit_human_pair_rows": taxon_pairs["human/human"],
        "interaction_type_counts": dict(sorted(interaction_types.items())),
        "missing_field_counts": dict(sorted(missing_fields.items())),
        "same_alias_rows": self_alias_rows,
        "graph_records_emitted": 0,
        "limitations": [
            UNASSESSED_ROLES,
            "Taxonomy counts cover well-formed rows only and do not validate molecular identity.",
            "Interaction types are retained as source labels, not approved LR predicates.",
            "Same aliases are a diagnostic, not proof of identical resolved entities.",
            "Source reuse permissions remain unverified.",
        ],
    }


def main() -> None:
    """Print audit diagnostics, reporting fatal read errors with a nonzero exit.

    Args:
        None.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Local BaderLab gzip-delimited source")
    args = parser.parse_args()
    try:
        report = audit_source(args.path)
    except (OSError, EOFError, ValueError, csv.Error) as exc:
        print(
            json.dumps(
                {
                    "audit_complete": False,
                    "import_ready": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from exc
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
