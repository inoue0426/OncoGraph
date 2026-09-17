"""Fetch DGIdb drug-gene interactions for a small, curated gene list.

DGIdb's GraphQL API is open and requires no API key. See
``oncograph.sources.dgidb`` for why this source is nonetheless treated as
redistribution-conservative (no explicit data license found for the
aggregated interaction data), and why this is not wired into the scheduled
data-refresh pipeline.

Run:
    python scripts/fetch_dgidb_interactions.py
"""

import json
from pathlib import Path
from urllib.request import Request, urlopen

DGIDB_API = "https://dgidb.org/api/graphql"
OUTPUT_PATH = Path("data/raw/dgidb_interactions.json")
_USER_AGENT = "OncoGraph/0.1 research database"
_HTTP_TIMEOUT = 30

# Same curated set used by fetch_civic_evidence.py, for comparable coverage.
GENES = ["EGFR", "BRAF", "KRAS", "ALK", "ERBB2", "TP53", "PIK3CA", "BRCA1", "BRCA2"]

_QUERY = """
query GeneInteractions($names: [String!]) {
  genes(names: $names) {
    nodes {
      name
      conceptId
      interactions {
        drug { name conceptId }
        interactionScore
        interactionTypes { type }
        sources { sourceDbName }
      }
    }
  }
}
"""


def _post_json(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = Request(
        DGIDB_API,
        data=body,
        headers={"User-Agent": _USER_AGENT, "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
        return json.load(response)


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = _post_json(_QUERY, {"names": GENES})
    genes = ((payload.get("data") or {}).get("genes") or {}).get("nodes", [])

    records: list[dict] = []
    for gene in genes:
        gene_concept_id = gene.get("conceptId")
        for interaction in gene.get("interactions") or []:
            drug = interaction.get("drug") or {}
            records.append(
                {
                    "gene_name": gene.get("name"),
                    "gene_concept_id": gene_concept_id,
                    "drug_name": drug.get("name"),
                    "drug_concept_id": drug.get("conceptId"),
                    "interaction_score": interaction.get("interactionScore"),
                    "interaction_types": [
                        t.get("type") for t in (interaction.get("interactionTypes") or [])
                    ],
                    "sources": [
                        s.get("sourceDbName") for s in (interaction.get("sources") or [])
                    ],
                }
            )

    OUTPUT_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(records)} interactions for {len(genes)} genes)")


if __name__ == "__main__":
    main()
