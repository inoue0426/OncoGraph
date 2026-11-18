"""Report local Lewis identifier coverage using approved HGNC symbols only.

Print JSON to stdout; never fetch datasets or open a graph database. Nonzero
exit status means at least one source is incomplete, invalid, or quarantined.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from oncograph.sources import registry
from oncograph.sources.base import ExternalIdentifier
from oncograph.sources.lewis_lab import HUMAN_TAXON, LewisResolvedIdentifier

HGNC_REVIEW_FIELDS = ("symbol", "alias_symbol", "prev_symbol")


@dataclass(frozen=True)
class HgncReviewCandidate:
    """An HGNC name match for human review, never an approved mapping."""

    hgnc_id: str
    approved_symbol: str
    matched_fields: tuple[str, ...]


def hgnc_review_index(path: Path) -> dict[str, tuple[HgncReviewCandidate, ...]]:
    """Index approved HGNC records by current, previous, and alias symbols.

    Args:
        path: Local complete-set TSV with explicit alias and previous-name fields.

    Returns:
        All candidate identities per normalized name, without resolving collisions.
    """
    matches: dict[str, dict[tuple[str, str], set[str]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {*HGNC_REVIEW_FIELDS, "hgnc_id", "status"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("HGNC review requires symbol, alias_symbol, prev_symbol, hgnc_id, status columns")
        for row in reader:
            if row["status"] != "Approved":
                continue
            identity = (row["hgnc_id"].strip(), row["symbol"].strip())
            if not all(identity):
                raise ValueError("Approved HGNC review row has an empty identity")
            for field in HGNC_REVIEW_FIELDS:
                for value in (row.get(field) or "").split("|"):
                    name = value.strip().upper()
                    if name:
                        matches.setdefault(name, {}).setdefault(identity, set()).add(field)
    return {
        name: tuple(HgncReviewCandidate(identifier, symbol, tuple(sorted(fields)))
                    for (identifier, symbol), fields in sorted(candidates.items()))
        for name, candidates in matches.items()
    }


def unresolved_review(
    values: list[str], index: dict[str, tuple[HgncReviewCandidate, ...]],
) -> list[dict[str, object]]:
    """Summarize unresolved occurrences and name-match candidates for review.

    Args:
        values: Unresolved parser values, including repeated occurrences.
        index: Human HGNC candidate index from the audited snapshot.

    Returns:
        Deterministic diagnostics; no generated identifier map or inferred species.
    """
    results: list[dict[str, object]] = []
    for value, occurrences in sorted(Counter(values).items()):
        candidates = index.get(value.strip().upper(), ())
        if len(candidates) > 1:
            status = "ambiguous_hgnc_candidates"
        elif candidates:
            status = "unique_hgnc_candidate_requires_review"
        elif re.fullmatch(r"HMDB\d{7}", value.strip(), flags=re.IGNORECASE):
            status = "hmdb_identifier_requires_metabolite_mapping"
        else:
            status = "no_hgnc_name_match"
        results.append({"input_value": value, "occurrences": occurrences, "status": status,
                        "candidates": [asdict(candidate) for candidate in candidates]})
    return results


def sha256(path: Path) -> str:
    """Fingerprint an input file.

    Args:
        path: Local input.

    Returns:
        SHA-256 digest of its bytes.
    """
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def approved_mapping(path: Path) -> dict:
    """Load approved symbols, retaining collisions as ambiguous candidates.

    Args:
        path: HGNC complete-set TSV.

    Returns:
        Human symbol mapping without alias or previous-symbol inference.
    """
    mapping: dict = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"symbol", "hgnc_id", "status"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("HGNC input requires symbol, hgnc_id, status columns")
        for row in reader:
            if row["status"] != "Approved":
                continue
            symbol, identifier = row["symbol"].strip(), row["hgnc_id"].strip()
            if not symbol or not identifier:
                raise ValueError("Approved HGNC row has an empty symbol or identifier")
            mapping.setdefault((HUMAN_TAXON, symbol.upper()), []).append(
                LewisResolvedIdentifier(ExternalIdentifier("hgnc", identifier), "gene")
            )
    return mapping


def main() -> None:
    """Audit selected local sources and print reproducible coverage diagnostics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("human_directory", type=Path)
    parser.add_argument("hgnc_complete_set", type=Path)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--review-unresolved", action="store_true",
                        help="Add HGNC alias/previous-symbol candidates for manual review only")
    args = parser.parse_args()
    hgnc_hash = sha256(args.hgnc_complete_set)
    mapping = approved_mapping(args.hgnc_complete_set)
    review_index = hgnc_review_index(args.hgnc_complete_set) if args.review_unresolved else None
    results = []
    for key in args.source:
        if not key.startswith("lewis_"):
            parser.error("Only Lewis sources can be audited")
        cls = registry.get(key)
        path = args.human_directory / cls.profile.filename
        result = {"source_key": key, "source_file": path.name, "valid": False}
        try:
            result["source_sha256"] = sha256(path)
            result.update(cls(path, mapping).validation_report().to_dict())
            if review_index is not None:
                result["unresolved_review"] = unresolved_review(result["unresolved_values"], review_index)
            if sha256(path) != result["source_sha256"]:
                raise ValueError("Source changed during audit")
        except (OSError, ValueError, RuntimeError) as exc:
            result.update(valid=False, errors=[str(exc)])
        results.append(result)
    if sha256(args.hgnc_complete_set) != hgnc_hash:
        raise ValueError("HGNC input changed during audit")
    print(json.dumps({"hgnc_sha256": hgnc_hash, "mapping_policy": "approved_symbols_only",
                      "taxon_id": HUMAN_TAXON, "sources": results}, indent=2, sort_keys=True))
    if not all(result["valid"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
