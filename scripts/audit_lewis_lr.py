"""Audit Lewis Lab ligand–receptor source files without redistributing them.

Run against a separately obtained local copy:
  python scripts/audit_lewis_lr.py /path/to/Ligand-Receptor-Pairs --out report.json

This script does not fetch, upload, or commit upstream datasets. Counts are
*table rows*, not validated ligand–receptor pairs. Review the source-specific
columns before adding an ingestion mapping.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

DATA_EXTS = {".csv", ".tsv", ".txt", ".xlsx", ".zip"}
MAX_MEMBER_BYTES = 100 * 1024 * 1024


def _audit_table(data: bytes, name: str) -> list[dict]:
    suffix = Path(name).suffix.lower()
    if suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("Install openpyxl to inspect Excel workbooks") from exc
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        results = []
        try:
            for sheet in workbook:
                iterator = sheet.iter_rows(values_only=True)
                header = next(iterator, ())
                rows = sum(any(value is not None for value in row) for row in iterator)
                results.append({
                    "table": name, "sheet": sheet.title, "rows_after_first": rows,
                    "first_row": [str(value) if value is not None else "" for value in header],
                })
        finally:
            workbook.close()
        return results
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode {name}")
    sample = text[:8192]
    delimiter = "\t" if suffix in {".tsv", ".txt"} else ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, [])
    return [{
        "table": name, "rows_after_first": sum(bool(row) for row in reader),
        "first_row": header, "delimiter": delimiter,
    }]


def audit_file(path: Path) -> dict:
    data = path.read_bytes()
    result = {"file": path.name, "bytes": len(data),
              "sha256": hashlib.sha256(data).hexdigest(), "tables": []}
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if member.is_dir() or Path(member.filename).suffix.lower() not in DATA_EXTS - {".zip"}:
                    continue
                if member.file_size > MAX_MEMBER_BYTES:
                    raise ValueError(f"Oversized archive member: {member.filename}")
                result["tables"].extend(_audit_table(archive.read(member), member.filename))
    else:
        result["tables"] = _audit_table(data, path.name)
    return result


def audit_repository(root: Path) -> dict:
    if not (root / "README.md").is_file():
        raise ValueError("Expected a Lewis Lab checkout containing README.md")
    report = {"upstream": "LewisLabUCSD/Ligand-Receptor-Pairs",
              "license_status": "not_granted_by_repository_metadata",
              "files": [], "errors": []}
    for species in ("Human", "Mouse", "Others"):
        directory = root / species
        if not directory.is_dir():
            report["errors"].append({"path": species, "error": "missing directory"})
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in DATA_EXTS:
                continue
            try:
                entry = audit_file(path)
                entry["group"] = species
                report["files"].append(entry)
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
                report["errors"].append({"path": str(path.relative_to(root)), "error": str(exc)})
    report["file_count"] = len(report["files"])
    report["table_count"] = sum(len(x["tables"]) for x in report["files"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Local checkout of LewisLabUCSD/Ligand-Receptor-Pairs")
    parser.add_argument("--out", type=Path, required=True, help="Write local JSON audit report")
    args = parser.parse_args()
    report = audit_repository(args.root)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Audited {report['file_count']} files / {report['table_count']} tables; "
          f"{len(report['errors'])} errors")
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
