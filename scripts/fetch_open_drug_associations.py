"""Fetch drug-associated clinical trials and target-disease associations.

Builds two derived, drug/target-scoped snapshots from public APIs, on top of
the files ``scripts/fetch_open_gene_sources.py`` already fetched:

- ClinicalTrials.gov API v2: trials whose interventions name-match one of our
  GtoPdb approved drugs (registry metadata only: NCT ID, title, status,
  phase, conditions -- not full protocol text).
- Open Targets Platform GraphQL API: top-scoring disease associations for
  each HGNC target our GtoPdb import resolves (CC0).

Both are scoped to the small, curated approved-drug/target set already on
disk, so per-record API calls (rather than a bulk download) are a deliberate
and proportionate choice here -- see docs/SOURCES.md "Scale policy".

Run after scripts/fetch_open_gene_sources.py:
    python scripts/fetch_open_drug_associations.py
"""

import csv
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

RAW_DIR = Path("data/raw")
INTERACTIONS_CSV = RAW_DIR / "gtopdb_approved_drug_primary_target_interactions.csv"
HGNC_MAPPING_CSV = RAW_DIR / "gtopdb_hgnc_mapping.csv"
HGNC_TSV = RAW_DIR / "hgnc_complete_set.txt"

CLINICALTRIALS_TRIALS_JSON = RAW_DIR / "clinicaltrials_trials.json"
OPEN_TARGETS_DISEASES_JSON = RAW_DIR / "open_targets_target_diseases.json"

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
CTGOV_PAGE_SIZE = 20
CTGOV_MIN_NAME_LENGTH = 4  # skip drug names too short/generic to search reliably

OPEN_TARGETS_API = "https://api.platform.opentargets.org/api/v4/graphql"
OPEN_TARGETS_TOP_K = 10
OPEN_TARGETS_MIN_SCORE = 0.4

_USER_AGENT = "OncoGraph/0.1 research database"
_HTTP_TIMEOUT = 30
_REQUEST_PAUSE = 0.1
_RETRY_DELAYS = (1, 3, 6, None)

_ASSOCIATED_DISEASES_QUERY = """
query TargetDiseases($ensemblId: String!, $size: Int!) {
  target(ensemblId: $ensemblId) {
    associatedDiseases(page: {index: 0, size: $size}) {
      rows {
        score
        disease { id name }
      }
    }
  }
}
"""


def _read_rows(path: Path) -> list[dict]:
    """Read a GtoPdb CSV, skipping its leading '# GtoPdb Version: ...' comment line."""
    with path.open(encoding="utf-8", newline="") as handle:
        lines = handle.readlines()
    if lines and lines[0].lstrip().startswith('"#'):
        lines = lines[1:]
    return list(csv.DictReader(lines))


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


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    for delay in _RETRY_DELAYS:
        try:
            with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError):
            if delay is None:
                raise
            time.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def _approved_drugs() -> list[dict]:
    """Unique (ligand_id, ligand_name) pairs from the GtoPdb interactions file."""
    seen: dict[str, str] = {}
    for row in _read_rows(INTERACTIONS_CSV):
        ligand_id = (row.get("Ligand ID") or "").strip()
        ligand_name = (row.get("Ligand") or "").strip()
        if ligand_id and ligand_name and ligand_id not in seen:
            seen[ligand_id] = ligand_name
    return [{"ligand_id": lid, "ligand_name": name} for lid, name in seen.items()]


def _resolved_targets() -> list[dict]:
    """Unique HGNC targets (with Ensembl gene IDs) referenced by approved-drug interactions."""
    hgnc_id_by_target_id: dict[str, str] = {}
    for row in _read_rows(HGNC_MAPPING_CSV):
        target_id = (row.get("IUPHAR ID") or "").strip()
        hgnc_id = (row.get("HGNC ID") or "").strip()
        if target_id and hgnc_id:
            hgnc_id_by_target_id[target_id] = f"HGNC:{hgnc_id}"

    referenced_target_ids = {
        (row.get("Target ID") or "").strip()
        for row in _read_rows(INTERACTIONS_CSV)
        if (row.get("Target ID") or "").strip()
    }

    ensembl_by_hgnc_id: dict[str, str] = {}
    with HGNC_TSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            hgnc_id = (row.get("hgnc_id") or "").strip()
            ensembl_gene_id = (row.get("ensembl_gene_id") or "").strip()
            if hgnc_id and ensembl_gene_id:
                ensembl_by_hgnc_id[hgnc_id] = ensembl_gene_id

    targets: dict[str, dict] = {}
    for target_id in referenced_target_ids:
        hgnc_id = hgnc_id_by_target_id.get(target_id)
        if not hgnc_id or hgnc_id in targets:
            continue
        ensembl_gene_id = ensembl_by_hgnc_id.get(hgnc_id)
        if not ensembl_gene_id:
            continue
        targets[hgnc_id] = {"hgnc_id": hgnc_id, "ensembl_gene_id": ensembl_gene_id}
    return list(targets.values())


def _fetch_trials(drugs: list[dict]) -> list[dict]:
    """Fetch CT.gov trials per drug name, keeping only name-matched interventions."""
    fields = "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionName"
    records: list[dict] = []
    for drug in drugs:
        name = drug["ligand_name"]
        if len(name) < CTGOV_MIN_NAME_LENGTH:
            continue
        query = urlencode({"query.intr": name, "pageSize": CTGOV_PAGE_SIZE, "fields": fields})
        time.sleep(_REQUEST_PAUSE)
        try:
            payload = _get_json(f"{CTGOV_API}?{query}")
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"  ! ClinicalTrials.gov query failed for {name}: {exc}")
            continue

        lowered_name = name.lower()
        for study in payload.get("studies", []):
            protocol = study.get("protocolSection", {})
            interventions = protocol.get("armsInterventionsModule", {}).get("interventions", [])
            matched = next(
                (
                    intervention.get("name")
                    for intervention in interventions
                    if lowered_name in (intervention.get("name") or "").lower()
                ),
                None,
            )
            if matched is None:
                continue
            identification = protocol.get("identificationModule", {})
            nct_id = identification.get("nctId")
            if not nct_id:
                continue
            records.append(
                {
                    "ligand_id": drug["ligand_id"],
                    "ligand_name": name,
                    "nct_id": nct_id,
                    "brief_title": identification.get("briefTitle"),
                    "overall_status": protocol.get("statusModule", {}).get("overallStatus"),
                    "phases": protocol.get("designModule", {}).get("phases", []),
                    "conditions": protocol.get("conditionsModule", {}).get("conditions", []),
                    "matched_intervention": matched,
                }
            )
    return records


def _fetch_target_diseases(targets: list[dict]) -> list[dict]:
    """Fetch top-K, score-thresholded disease associations per HGNC target."""
    records: list[dict] = []
    for target in targets:
        time.sleep(_REQUEST_PAUSE)
        payload = {
            "query": _ASSOCIATED_DISEASES_QUERY,
            "variables": {"ensemblId": target["ensembl_gene_id"], "size": OPEN_TARGETS_TOP_K},
        }
        try:
            response = _post_json(OPEN_TARGETS_API, payload)
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"  ! Open Targets query failed for {target['ensembl_gene_id']}: {exc}")
            continue

        target_data = (response.get("data") or {}).get("target") or {}
        rows = (target_data.get("associatedDiseases") or {}).get("rows", [])
        for row in rows:
            score = row.get("score")
            if score is None or score < OPEN_TARGETS_MIN_SCORE:
                continue
            disease = row.get("disease") or {}
            disease_id = disease.get("id")
            if not disease_id:
                continue
            records.append(
                {
                    "hgnc_id": target["hgnc_id"],
                    "ensembl_gene_id": target["ensembl_gene_id"],
                    "disease_id": disease_id,
                    "disease_name": disease.get("name"),
                    "score": score,
                }
            )
    return records


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()

    drugs = _approved_drugs()
    print(f"Querying ClinicalTrials.gov for {len(drugs)} approved drugs...")
    trials = _fetch_trials(drugs)
    CLINICALTRIALS_TRIALS_JSON.write_text(json.dumps(trials, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {CLINICALTRIALS_TRIALS_JSON} ({len(trials)} drug-trial links)")

    targets = _resolved_targets()
    print(f"Querying Open Targets for {len(targets)} HGNC targets...")
    diseases = _fetch_target_diseases(targets)
    OPEN_TARGETS_DISEASES_JSON.write_text(json.dumps(diseases, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OPEN_TARGETS_DISEASES_JSON} ({len(diseases)} target-disease links)")

    manifest_path = RAW_DIR / "manifest_drug_associations.json"
    manifest_path.write_text(
        json.dumps(
            {
                "fetched_at": fetched_at,
                "clinicaltrials_gov": {
                    "query": "query.intr=<drug name>, name-match filtered",
                    "min_drug_name_length": CTGOV_MIN_NAME_LENGTH,
                    "drug_count": len(drugs),
                    "trial_link_count": len(trials),
                },
                "open_targets": {
                    "query": "target(ensemblId).associatedDiseases",
                    "top_k": OPEN_TARGETS_TOP_K,
                    "min_score": OPEN_TARGETS_MIN_SCORE,
                    "target_count": len(targets),
                    "association_count": len(diseases),
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
