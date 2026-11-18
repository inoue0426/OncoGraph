"""Database-free audit must expose unresolved identifiers and source hashes."""

import json
import subprocess
import sys
from pathlib import Path


def test_audit_preserves_ambiguity_and_ignores_unapproved_symbols(tmp_path):
    hgnc = tmp_path / "hgnc.tsv"
    hgnc.write_text(
        "symbol\thgnc_id\tstatus\nA\tHGNC:1\tApproved\n"
        "A\tHGNC:2\tApproved\nB\tHGNC:3\tEntry Withdrawn\n",
        encoding="utf-8",
    )
    source = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    source.write_text(
        "Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\nA\tB\n", encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts/audit_lewis_identifiers.py"
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path), str(hgnc),
         "--source", "lewis_ramilowski_2015"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert len(report["hgnc_sha256"]) == 64
    row = report["sources"][0]
    assert len(row["source_sha256"]) == 64
    assert row["ambiguous_values"] == ["A"]
    assert row["unresolved_values"] == ["B"]
    assert row["emitted_interactions"] == 0
    assert row["valid"] is False


def test_review_reports_candidates_without_importing_or_guessing(tmp_path):
    """Review suggestions preserve collisions and cannot increase emitted coverage."""
    hgnc = tmp_path / "hgnc.tsv"
    hgnc.write_text(
        "symbol\thgnc_id\tstatus\talias_symbol\tprev_symbol\n"
        "A\tHGNC:1\tApproved\tOLD|MULTI\tOLD\n"
        "B\tHGNC:2\tApproved\tMULTI\t\n"
        "R\tHGNC:3\tApproved\t\t\n"
        "W\tHGNC:4\tEntry Withdrawn\tUNKNOWN\t\n",
        encoding="utf-8",
    )
    source = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    source.write_text(
        "Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\n"
        "OLD\tR\nOLD\tR\nMULTI\tR\nHMDB0000001\tR\nUNKNOWN\tR\n",
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts/audit_lewis_identifiers.py"
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path), str(hgnc),
         "--source", "lewis_ramilowski_2015", "--review-unresolved"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["mapping_policy"] == "approved_symbols_only"
    row = report["sources"][0]
    assert row["emitted_interactions"] == 0
    assert row["unresolved_identifiers"] == row["skipped_rows"] == 5
    assert row["valid"] is False
    reviews = {item["input_value"]: item for item in row["unresolved_review"]}
    assert reviews["OLD"]["occurrences"] == 2
    assert reviews["OLD"]["status"] == "unique_hgnc_candidate_requires_review"
    assert reviews["OLD"]["candidates"] == [{
        "hgnc_id": "HGNC:1", "approved_symbol": "A",
        "matched_fields": ["alias_symbol", "prev_symbol"],
    }]
    assert reviews["MULTI"]["status"] == "ambiguous_hgnc_candidates"
    assert {item["hgnc_id"] for item in reviews["MULTI"]["candidates"]} == {"HGNC:1", "HGNC:2"}
    assert reviews["HMDB0000001"]["status"] == "hmdb_identifier_requires_metabolite_mapping"
    assert reviews["UNKNOWN"]["status"] == "no_hgnc_name_match"
    assert reviews["UNKNOWN"]["candidates"] == []
