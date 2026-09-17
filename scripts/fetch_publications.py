"""Fetch Europe PMC bibliographic metadata for a curated set of cited PMIDs.

Reads ``data/curated/publication_citations.json`` (a small, hand-curated list
of which PMID supports which existing relation -- original curation, not
fetched, and committed to the repository) and fetches, for each unique PMID,
only bibliographic metadata (title, journal, year, authors, publication
type, DOI, PMCID) from the Europe PMC REST API. Never fetches or stores an
abstract or full text.

Run:
    python scripts/fetch_publications.py
"""

import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CITATIONS_PATH = Path("data/curated/publication_citations.json")
OUTPUT_PATH = Path("data/raw/publications.json")

EUROPE_PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_USER_AGENT = "OncoGraph/0.1 research database"
_HTTP_TIMEOUT = 30
_REQUEST_PAUSE = 0.2
_RETRY_DELAYS = (1, 3, None)


def _unique_pmids() -> list[str]:
    citations = json.loads(CITATIONS_PATH.read_text(encoding="utf-8"))
    seen: list[str] = []
    for row in citations:
        pmid = (row.get("pmid") or "").strip()
        if pmid and pmid not in seen:
            seen.append(pmid)
    return seen


def _get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    for delay in _RETRY_DELAYS:
        try:
            with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError):
            if delay is None:
                raise
            time.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def _fetch_one(pmid: str) -> dict | None:
    """Fetch one PMID's bibliographic metadata only -- no abstract, no full text."""
    query = urlencode(
        {"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "resultType": "core"}
    )
    payload = _get_json(f"{EUROPE_PMC_API}?{query}")
    results = (payload.get("resultList") or {}).get("result", [])
    if not results:
        return None
    result = results[0]

    authors = None
    author_list = (result.get("authorList") or {}).get("author", [])
    if author_list:
        authors = [a.get("fullName") for a in author_list if a.get("fullName")]

    return {
        "pmid": pmid,
        "doi": result.get("doi"),
        "pmcid": result.get("pmcid"),
        "title": result.get("title"),
        "journal": (result.get("journalInfo") or {}).get("journal", {}).get("title"),
        "year": result.get("pubYear"),
        "authors": authors,
        "pub_types": (result.get("pubTypeList") or {}).get("pubType", []),
        "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pmids = _unique_pmids()
    print(f"Fetching Europe PMC metadata for {len(pmids)} cited PMIDs...")

    records: list[dict] = []
    for pmid in pmids:
        time.sleep(_REQUEST_PAUSE)
        try:
            record = _fetch_one(pmid)
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"  ! Europe PMC fetch failed for PMID {pmid}: {exc}")
            continue
        if record is None:
            print(f"  ! No Europe PMC record found for PMID {pmid}")
            continue
        records.append(record)

    OUTPUT_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(records)} publications)")


if __name__ == "__main__":
    main()
