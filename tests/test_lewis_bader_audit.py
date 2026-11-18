"""Regression tests for review-only BaderLab diagnostics."""

import csv
import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_lewis_bader.py"
SPEC = importlib.util.spec_from_file_location("audit_lewis_bader", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def write_table(path: Path, rows: list[list[str]]) -> None:
    """Write a compressed synthetic table with the audited column layout.

    Args:
        path: Destination for the fixture.
        rows: Source rows, including any deliberately malformed ones.

    Returns:
        None.
    """
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(audit.EXPECTED_COLUMNS)
        writer.writerows(rows)


def test_audit_does_not_promote_human_pairs_to_lr_edges(tmp_path: Path) -> None:
    """Retain source categories and separate absent taxonomy from explicit human rows."""
    path = tmp_path / "source.txt.zip"
    rows = []
    for tax_a, tax_b, interaction in (
        ("taxid:9606(Homo sapiens)", "taxid:9606", "MI:0407(direct interaction)"),
        ("taxid:10090(Mouse)", "taxid:9606", "controls-expression-of"),
        ("", "-", "in-complex-with"),
        ("9606", "taxid:9606", "MI:0469(intact)"),
    ):
        row = {key: "-" for key in audit.EXPECTED_COLUMNS}
        row.update(AliasA="A", AliasB="A", taxa=tax_a, taxb=tax_b, interactionType=interaction)
        rows.append([row[key] for key in audit.EXPECTED_COLUMNS])
    rows.append(["truncated", "row"])
    write_table(path, rows)

    report = audit.audit_source(path)
    assert report["audit_complete"] is True
    assert report["import_ready"] is False
    assert report["graph_records_emitted"] == 0
    assert report["input_rows"] == 5
    assert report["malformed_width_rows"] == 1
    assert report["explicit_human_pair_rows"] == 1
    assert report["taxon_pair_counts"] == {
        "human/human": 1,
        "nonhuman/human": 1,
        "missing/missing": 1,
        "malformed/human": 1,
    }
    assert report["interaction_type_counts"]["controls-expression-of"] == 1
    assert report["interaction_type_counts"]["MI:0469(intact)"] == 1
    assert report["missing_field_counts"]["pmids"] == 4
    assert report["same_alias_rows"] == 4
    assert report["source_sha256"] == audit.file_sha256(path)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("taxid:9606|taxid:9606(Human)", "human"),
        ("taxid:9606|taxid:10090", "nonhuman"),
        ("taxid:9606|-", "malformed"),
        ("taxid:9606foo", "malformed"),
        ("taxid:96060", "nonhuman"),
        ("-", "missing"),
    ],
)
def test_taxonomy_requires_complete_explicit_terms(value: str, expected: str) -> None:
    """Reject partial, unknown, and mixed-species matches as human-only evidence."""
    assert audit.taxon_status(value) == expected


@pytest.mark.parametrize("payload", [b"not gzip", gzip.compress(b"wrong\theader\n")])
def test_command_reports_fatal_failures(
    tmp_path: Path, monkeypatch, capsys, payload: bytes
) -> None:
    """Make invalid inputs visible to both shell callers and JSON consumers."""
    path = tmp_path / "source.zip"
    path.write_bytes(payload)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(path)])
    with pytest.raises(SystemExit) as exc:
        audit.main()
    assert exc.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["audit_complete"] is False
    assert report["import_ready"] is False


def test_audit_detects_source_changes(tmp_path: Path, monkeypatch) -> None:
    """Do not attach a stable fingerprint to a file changed during inspection."""
    path = tmp_path / "source.zip"
    write_table(path, [])
    hashes = iter(("before", "after"))
    monkeypatch.setattr(audit, "file_sha256", lambda _: next(hashes))
    with pytest.raises(ValueError, match="changed"):
        audit.audit_source(path)
