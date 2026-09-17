"""Fetch redistributable gene/ontology/drug sources into data/raw.

Sources:
- Gene Ontology go-basic.obo (CC BY 4.0)
- HGNC complete human gene set (CC0)
- GtoPdb approved drugs with primary targets, plus its target-to-HGNC mapping
  (database: ODbL; content: CC BY-SA 4.0). Only these two small, official
  files are fetched -- not the full ligand/interaction dump or the Postgres
  export.

Run: python scripts/fetch_open_gene_sources.py
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

GTOPDB_LICENSE = "ODbL (database) / CC BY-SA 4.0 (content)"
GTOPDB_LICENSE_URL = "https://opendatacommons.org/licenses/odbl/; http://creativecommons.org/licenses/by-sa/4.0/"

SOURCES = {
    "gene_ontology": {
        "url": "https://purl.obolibrary.org/obo/go/go-basic.obo",
        "filename": "go-basic.obo",
        "license": "CC BY 4.0",
        "license_url": "https://geneontology.org/docs/go-citation-policy/",
    },
    "hgnc": {
        "url": "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt",
        "filename": "hgnc_complete_set.txt",
        "license": "CC0",
        "license_url": "https://www.genenames.org/about/license/",
    },
    "gtopdb_approved_drug_targets": {
        "url": "https://www.guidetopharmacology.org/DATA/approved_drug_primary_target_interactions.csv",
        "filename": "gtopdb_approved_drug_primary_target_interactions.csv",
        "license": GTOPDB_LICENSE,
        "license_url": GTOPDB_LICENSE_URL,
    },
    "gtopdb_hgnc_mapping": {
        "url": "https://www.guidetopharmacology.org/DATA/GtP_to_HGNC_mapping.csv",
        "filename": "gtopdb_hgnc_mapping.csv",
        "license": GTOPDB_LICENSE,
        "license_url": GTOPDB_LICENSE_URL,
    },
}

_GTOPDB_VERSION_RE = re.compile(r'GtoPdb Version:\s*([^"-]+?)\s*-\s*published:\s*([\d-]+)')


def download(url: str, destination: Path) -> str:
    request = Request(url, headers={"User-Agent": "OncoGraph/0.1 research database"})
    digest = hashlib.sha256()
    with urlopen(request, timeout=120) as response, destination.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def _gtopdb_release(destination: Path) -> str | None:
    """Read the release version GtoPdb prints as the file's first comment line."""
    with destination.open(encoding="utf-8") as handle:
        first_line = handle.readline()
    match = _GTOPDB_VERSION_RE.search(first_line)
    if not match:
        return None
    version, published = match.groups()
    return f"{version.strip()} (published {published.strip()})"


def main() -> None:
    root = Path("data/raw")
    root.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    manifest = {"fetched_at": fetched_at, "sources": {}}
    for key, source in SOURCES.items():
        destination = root / source["filename"]
        print(f"Fetching {key} -> {destination}")
        sha256 = download(source["url"], destination)
        entry = {**source, "sha256": sha256}
        if key.startswith("gtopdb"):
            release = _gtopdb_release(destination)
            if release:
                entry["release"] = release
        manifest["sources"][key] = entry
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Wrote data/raw/manifest.json")


if __name__ == "__main__":
    main()
