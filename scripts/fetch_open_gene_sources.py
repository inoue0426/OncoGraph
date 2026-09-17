"""Fetch redistributable gene/ontology sources into data/raw.

Sources:
- Gene Ontology go-basic.obo (CC BY 4.0)
- HGNC complete human gene set (CC0)

Run: python scripts/fetch_open_gene_sources.py
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import json

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


def main() -> None:
    root = Path("data/raw")
    root.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat()
    manifest = {"fetched_at": fetched_at, "sources": {}}
    for key, source in SOURCES.items():
        destination = root / source["filename"]
        print(f"Fetching {key} -> {destination}")
        sha256 = download(source["url"], destination)
        manifest["sources"][key] = {**source, "sha256": sha256}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Wrote data/raw/manifest.json")


if __name__ == "__main__":
    main()
