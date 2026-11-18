"""Smoke tests for the provenance-preserving Lewis Lab source inventory."""
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_lewis_lr.py"
spec = importlib.util.spec_from_file_location("audit_lewis_lr", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_audit_collects_sources_without_merging_species(tmp_path):
    (tmp_path / "README.md").write_text("Original source citations", encoding="utf-8")
    for group in ("Human", "Mouse", "Others"):
        (tmp_path / group).mkdir()
    (tmp_path / "Human" / "human.csv").write_text(
        "ligand,receptor\nTGFB1,TGFBR1\n", encoding="utf-8"
    )
    (tmp_path / "Mouse" / "mouse.tsv").write_text(
        "ligand\treceptor\nTgfb1\tTgfbr1\n", encoding="utf-8"
    )
    result = audit.audit_repository(tmp_path)
    assert result["file_count"] == 2
    assert result["table_count"] == 2
    assert not result["errors"]
    assert {entry["group"] for entry in result["files"]} == {"Human", "Mouse"}
    assert all(len(entry["sha256"]) == 64 for entry in result["files"])
    assert result["license_status"] == "not_granted_by_repository_metadata"


def test_zip_members_are_inspected_without_extraction(tmp_path):
    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("../pairs.csv", "ligand,receptor\nA,B\n")
        target.writestr("notes.md", "not a dataset")
    result = audit.audit_file(archive)
    assert result["tables"][0]["rows_after_first"] == 1
    assert result["tables"][0]["first_row"] == ["ligand", "receptor"]
    assert not (tmp_path.parent / "pairs.csv").exists()


def test_missing_directory_is_reported(tmp_path):
    (tmp_path / "README.md").write_text("README", encoding="utf-8")
    report = audit.audit_repository(tmp_path)
    assert len(report["errors"]) == 3


def test_excel_sheet_is_inspected_if_available(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(["ligand", "receptor"])
    worksheet.append(["A", "B"])
    file = tmp_path / "test.xlsx"
    workbook.save(file)
    result = audit.audit_file(file)
    assert result["tables"][0]["rows_after_first"] == 1
