"""Fetch redistributable gene/ontology sources and write a provenance manifest.

Sources:
- Gene Ontology go-basic.obo (CC BY 4.0)
- HGNC complete human gene set (CC0)

Run: python scripts/fetch_open_gene_sources.py
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

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
}


def download(url: str, destination: Path) -> str:
    request = Request(url, headers={"User-Agent": "OncoGraph/0.1 research database"})
    digest = hashlib.sha256()
    with urlopen(request, timeout=120) as response, destination.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    """Parse command-line paths.

    Returns:
        Parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory for downloaded upstream files (default: data/raw)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/raw/manifest.json"),
        help="Path for the JSON provenance manifest",
    )
    return parser.parse_args()


def main() -> None:
    """Download configured open sources and record checksums and licensing."""
    args = parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    manifest = {"schema_version": 1, "fetched_at": fetched_at, "sources": {}}
    for key, source in SOURCES.items():
        destination = args.raw_dir / source["filename"]
        print(f"Fetching {key} -> {destination}")
        sha256 = download(source["url"], destination)
        manifest["sources"][key] = {
            **source,
            "sha256": sha256,
            "bytes": destination.stat().st_size,
        }
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.manifest}")


if __name__ == "__main__":
    main()
