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
_HGVS_NULL_ERROR = "Cannot return null for non-nullable field EvidenceItem.variantHgvs"

# A small, curated set of well-studied oncogenes/tumor suppressors -- not an
# attempt to mirror all of CIViC.
GENES = ["EGFR", "BRAF", "KRAS", "ALK", "ERBB2", "TP53", "PIK3CA", "BRCA1", "BRCA2"]

_EVIDENCE_FIELDS = """
  id status evidenceType evidenceDirection evidenceLevel evidenceRating
  variantHgvs significance
  therapies { name ncitId }
  disease { name doid }
  source { citationId sourceType sourceUrl }
"""
_PROFILE_FIELDS = f"""
  id name
  variants {{ id name feature {{ name }} }}
  evidenceItems(first: 100) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_EVIDENCE_FIELDS} }}
  }}
"""
_VARIANT_FIELDS = f"""
  id name
  ... on GeneVariant {{
    molecularProfiles(first: 100) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_PROFILE_FIELDS} }}
    }}
  }}
"""
_GENE_FIELDS = f"""
  name entrezId
  variants(first: 100) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_VARIANT_FIELDS} }}
  }}
"""
_QUERY = f"""
query GeneEvidence($symbols: [String!], $after: String) {{
  genes(entrezSymbols: $symbols, first: 100, after: $after) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_GENE_FIELDS} }}
  }}
}}
"""
_VARIANTS_QUERY = f"""
query VariantPage($symbol: String!, $after: String) {{
  gene(entrezSymbol: $symbol) {{
    variants(first: 100, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_VARIANT_FIELDS} }}
    }}
  }}
}}
"""
_PROFILES_QUERY = f"""
query ProfilePage($id: Int!, $after: String) {{
  variant(id: $id) {{
    ... on GeneVariant {{
      molecularProfiles(first: 100, after: $after) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {_PROFILE_FIELDS} }}
      }}
    }}
  }}
}}
"""
_EVIDENCE_QUERY = f"""
query EvidencePage($id: Int!, $after: String) {{
  molecularProfile(id: $id) {{
    evidenceItems(first: 100, after: $after) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_EVIDENCE_FIELDS} }}
    }}
  }}
}}
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


def require_complete_connections(value: object, path: str = "data") -> None:
    """Reject truncated GraphQL connections before writing a source snapshot.

    Args:
        value: Nested GraphQL data containing connection objects.
        path: Diagnostic path to the current object.

    Returns:
        None.

    Raises:
        RuntimeError: Pagination is incomplete or its completeness is unknown.
    """
    if isinstance(value, dict):
        if "nodes" in value:
            page_info = value.get("pageInfo") or {}
            if page_info.get("hasNextPage") is not False:
                raise RuntimeError(
                    f"CIViC pagination incomplete or unverified at {path}; "
                    "refusing to publish a truncated snapshot"
                )
        for key, item in value.items():
            require_complete_connections(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            require_complete_connections(item, f"{path}[{index}]")


def request_data(query: str, variables: dict, omitted_fields: set[str]) -> dict:
    """Request a complete GraphQL response with a narrowly scoped HGVS fallback.

    Args:
        query: GraphQL document.
        variables: Variables for this request.
        omitted_fields: Run-level record of unavailable optional fields.

    Returns:
        Successful GraphQL data, never the partial data of an error response.
    """
    if omitted_fields:
        query = query.replace("variantHgvs", "")
    payload = _post_json(query, variables)
    errors = payload.get("errors") or []
    if errors and all(error.get("message") == _HGVS_NULL_ERROR for error in errors):
        omitted_fields.add("EvidenceItem.variantHgvs")
        payload = _post_json(query.replace("variantHgvs", ""), variables)
    if payload.get("errors"):
        raise RuntimeError(f"CIViC GraphQL query failed: {payload['errors']}")
    if not isinstance(payload.get("data"), dict):
        raise RuntimeError("CIViC returned no GraphQL data")  # noqa: TRY004
    return payload["data"]


def complete_connection(
    connection: dict,
    query: str,
    variables: dict,
    path: tuple[str, ...],
    omitted_fields: set[str],
) -> None:
    """Follow cursors and reject missing metadata, repeated pages, or ID overlap.

    Args:
        connection: First page, replaced in place with the combined result.
        query: Query for subsequent pages.
        variables: Stable parent selector for the connection.
        path: Keys locating this connection in a successful response.
        omitted_fields: Run-level optional field diagnostics.

    Returns:
        None.
    """
    page = connection
    nodes = []
    seen_ids = set()
    seen_cursors = set()
    while True:
        info = page.get("pageInfo") or {}
        more = info.get("hasNextPage")
        if not isinstance(more, bool) or not isinstance(page.get("nodes"), list):
            raise RuntimeError(f"CIViC pagination incomplete or unverified at {path}")  # noqa: TRY004
        for node in page["nodes"]:
            identity = node.get("id", node.get("name"))
            if identity is None or identity in seen_ids:
                raise RuntimeError(f"CIViC duplicate or missing node identity at {path}")
            seen_ids.add(identity)
            nodes.append(node)
        if not more:
            break
        cursor = info.get("endCursor")
        if not cursor or cursor in seen_cursors or not page["nodes"]:
            raise RuntimeError(f"CIViC pagination incomplete: stalled cursor at {path}")
        seen_cursors.add(cursor)
        page = request_data(query, {**variables, "after": cursor}, omitted_fields)
        for key in path:
            page = page[key]
    connection.update(nodes=nodes, pageInfo={"hasNextPage": False})


def profile_variant_labels(profile: dict) -> list[str]:
    """Read full profile membership, including features outside the requested genes.

    Args:
        profile: A molecular profile with its full, nonpaginated variants list.

    Returns:
        Sorted source-derived feature/variant labels.
    """
    variants = profile.get("variants")
    if not isinstance(variants, list) or not variants:
        raise RuntimeError("CIViC molecular profile has no verified variant membership")
    labels = []
    for variant in variants:
        feature = (variant.get("feature") or {}).get("name")
        if not feature or not variant.get("name"):
            raise RuntimeError("CIViC profile member lacks a feature or variant name")
        labels.append(f"{feature} {variant['name']}")
    return sorted(set(labels))


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    omitted_fields: set[str] = set()
    payload = request_data(_QUERY, {"symbols": GENES}, omitted_fields)
    connection = payload["genes"]
    complete_connection(connection, _QUERY, {"symbols": GENES}, ("genes",), omitted_fields)
    genes = connection["nodes"]
    if {gene["name"] for gene in genes} != set(GENES):
        raise RuntimeError("CIViC did not return exactly the requested gene set")
    for gene in genes:
        complete_connection(
            gene["variants"],
            _VARIANTS_QUERY,
            {"symbol": gene["name"]},
            ("gene", "variants"),
            omitted_fields,
        )
        for variant in gene["variants"]["nodes"]:
            profiles = variant.get("molecularProfiles")
            if profiles is None:
                raise RuntimeError("CIViC gene variant lacks molecular profiles")
            complete_connection(
                profiles,
                _PROFILES_QUERY,
                {"id": variant["id"]},
                ("variant", "molecularProfiles"),
                omitted_fields,
            )
            for profile in profiles["nodes"]:
                complete_connection(
                    profile["evidenceItems"],
                    _EVIDENCE_QUERY,
                    {"id": profile["id"]},
                    ("molecularProfile", "evidenceItems"),
                    omitted_fields,
                )
    require_complete_connections(payload)
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
                            "profile_variants": profile_variant_labels(profile),
                            "source_type": source.get("sourceType"),
                            "citation_id": source.get("citationId"),
                            "source_url": (
                                f"https://civicdb.org/links/evidence/{item['id']}"
                                if item.get("id")
                                else source.get("sourceUrl")
                            ),
                            "citation_url": source.get("sourceUrl"),
                        }
                    )

    if not records:
        raise RuntimeError("CIViC returned no accepted evidence; refusing an empty snapshot")
    OUTPUT_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "source": "CIViC",
        "homepage": "https://civicdb.org/",
        "license_url": "https://docs.civicdb.org/en/latest/about.html",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "genes_requested": GENES,
        "gene_count_returned": len(genes),
        "pagination_complete": True,
        "profile_membership_complete": True,
        "accepted_evidence_records": len(records),
        "filename": OUTPUT_PATH.name,
        "sha256": hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest(),
        "omitted_fields": sorted(omitted_fields),
        "omission_reason": _HGVS_NULL_ERROR if omitted_fields else None,
    }
    (OUTPUT_PATH.parent / "manifest_civic.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OUTPUT_PATH} ({len(records)} evidence items for {len(genes)} genes)")


if __name__ == "__main__":
    main()
