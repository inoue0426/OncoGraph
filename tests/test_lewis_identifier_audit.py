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
