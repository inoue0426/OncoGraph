"""Fetch accepted CIViC clinical evidence for a small, curated gene list.

CIViC data is released under the Creative Commons Public Domain Dedication
(CC0 1.0 Universal License): "We provide CIViC data freely to all ... Data
can be ... accessed through our fully open and documented API." No API key
is required. This script queries CIViC's public GraphQL API for ACCEPTED
evidence items on a small, curated set of well-studied cancer genes --
scoped like this deliberately, rather than pulling the entire database, to
keep the fetched snapshot small and reviewable.

Run:
    python scripts/fetch_civic_evidence.py
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

CIVIC_API = "https://civicdb.org/api/graphql"
OUTPUT_PATH = Path("data/raw/civic_evidence.json")
_USER_AGENT = "OncoGraph/0.1 research database"
_HTTP_TIMEOUT = 30

# A small, curated set of well-studied oncogenes/tumor suppressors -- not an
# attempt to mirror all of CIViC.
GENES = ["EGFR", "BRAF", "KRAS", "ALK", "ERBB2", "TP53", "PIK3CA", "BRCA1", "BRCA2"]

_QUERY = """
query GeneEvidence($symbols: [String!]) {
  genes(entrezSymbols: $symbols) {
    nodes {
      name
      entrezId
      variants {
        nodes {
          id
          name
          ... on GeneVariant {
            molecularProfiles {
              nodes {
                id
                name
                evidenceItems {
                  nodes {
                    id
                    status
                    evidenceType
                    evidenceDirection
                    evidenceLevel
                    evidenceRating
                    variantHgvs
                    significance
                    therapies { name ncitId }
                    disease { name doid }
                    source { citationId sourceType sourceUrl }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _post_json(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = Request(
        CIVIC_API,
        data=body,
        headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
        return json.load(response)


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = _post_json(_QUERY, {"symbols": GENES})
    if payload.get("errors"):
        raise RuntimeError(f"CIViC GraphQL query failed: {payload['errors']}")
    genes = ((payload.get("data") or {}).get("genes") or {}).get("nodes", [])
    if not genes:
        raise RuntimeError("CIViC returned no genes; refusing to publish an empty snapshot")

    records: list[dict] = []
    for gene in genes:
        gene_name = gene.get("name")
        gene_entrez_id = gene.get("entrezId")
        for variant in (gene.get("variants") or {}).get("nodes", []):
            for profile in (variant.get("molecularProfiles") or {}).get("nodes", []):
                molecular_profile = profile.get("name")
                for item in (profile.get("evidenceItems") or {}).get("nodes", []):
                    if item.get("status") != "ACCEPTED" or not item.get("id"):
                        continue
                    source = item.get("source") or {}
                    disease = item.get("disease") or {}
                    records.append(
                        {
                            "evidence_id": item.get("id"),
                            "gene_name": gene_name,
                            "gene_entrez_id": gene_entrez_id,
                            "variant_id": variant.get("id"),
                            "variant_name": variant.get("name"),
                            "variant_hgvs": item.get("variantHgvs"),
                            "evidence_type": item.get("evidenceType"),
                            "evidence_direction": item.get("evidenceDirection"),
                            "evidence_level": item.get("evidenceLevel"),
                            "evidence_rating": item.get("evidenceRating"),
                            "significance": item.get("significance"),
                            "therapies": [
                                {"name": t.get("name"), "ncit_id": t.get("ncitId")}
                                for t in (item.get("therapies") or [])
                            ],
                            "disease_name": disease.get("name"),
                            "disease_doid": disease.get("doid"),
                            "molecular_profile": molecular_profile,
                            "molecular_profile_id": profile.get("id"),
                            "source_type": source.get("sourceType"),
                            "citation_id": source.get("citationId"),
                            "source_url": (
                                f"https://civicdb.org/links/evidence/{item['id']}"
                                if item.get("id") else source.get("sourceUrl")
                            ),
                            "citation_url": source.get("sourceUrl"),
                        }
                    )

    if not records:
        raise RuntimeError("CIViC returned no accepted evidence; refusing an empty snapshot")
    profile_variants: dict[str, set[str]] = {}
    for record in records:
        profile_variants.setdefault(str(record["molecular_profile_id"]), set()).add(
            f"{record['gene_name']} {record['variant_name']}"
        )
    for record in records:
        record["profile_variants"] = sorted(profile_variants[str(record["molecular_profile_id"])])
    OUTPUT_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "source": "CIViC",
        "homepage": "https://civicdb.org/",
        "license_url": "https://docs.civicdb.org/en/latest/about.html",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "genes_requested": GENES,
        "gene_count_returned": len(genes),
        "accepted_evidence_records": len(records),
        "filename": OUTPUT_PATH.name,
        "sha256": hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest(),
    }
    (OUTPUT_PATH.parent / "manifest_civic.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OUTPUT_PATH} ({len(records)} evidence items for {len(genes)} genes)")


if __name__ == "__main__":
    main()
