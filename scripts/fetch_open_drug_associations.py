"""Fetch drug-associated clinical trials, target-disease associations, and
approved drug indications.

Builds three derived, drug/target-scoped snapshots from public APIs, on top
of the files ``scripts/fetch_open_gene_sources.py`` already fetched:

- ClinicalTrials.gov API v2: trials whose interventions name-match one of our
  GtoPdb approved drugs (registry metadata only: NCT ID, title, status,
  phase, conditions -- not full protocol text). A trial registration is
  evidence a drug was *studied* for a condition, not that it works or is
  approved.
- Open Targets Platform GraphQL API: top-scoring disease associations for
  each HGNC target our GtoPdb import resolves (CC0). A computed evidence
  aggregate, not a clinical indication.
- Open Targets Platform GraphQL API: approved (max clinical stage
  "APPROVAL") drug-disease indications, resolved from each GtoPdb drug name
  via Open Targets' own ``search`` (CC0). The strongest disease-evidence tier
  OncoGraph carries.

All three are scoped to the small, curated approved-drug/target set already
on disk, so per-record API calls (rather than a bulk download) are a
deliberate and proportionate choice here -- see docs/SOURCES.md "Scale
policy".

Run after scripts/fetch_open_gene_sources.py:
    python scripts/fetch_open_drug_associations.py
"""

import concurrent.futures
import csv
import hashlib
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
OPEN_TARGETS_INDICATIONS_JSON = RAW_DIR / "open_targets_drug_indications.json"

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
CTGOV_PAGE_SIZE = 20
CTGOV_MIN_NAME_LENGTH = 4  # skip drug names too short/generic to search reliably

OPEN_TARGETS_API = "https://api.platform.opentargets.org/api/v4/graphql"
OPEN_TARGETS_TOP_K = 10
OPEN_TARGETS_MIN_SCORE = 0.4
OPEN_TARGETS_MIN_DRUG_NAME_LENGTH = 4  # skip drug names too short/generic to search reliably
OPEN_TARGETS_APPROVAL_STAGE = "APPROVAL"
OPEN_TARGETS_MAX_INDICATIONS = 300  # per drug; approved drugs rarely have more real indications

_USER_AGENT = "OncoGraph/0.1 research database"
_HTTP_TIMEOUT = 30
_REQUEST_PAUSE = 0.1
_RETRY_DELAYS = (1, 3, 6, None)
_MAX_WORKERS = 8  # modest client-side concurrency; each item still retries/backs off on its own
_PROGRESS_EVERY = 50

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

_DRUG_SEARCH_QUERY = """
query DrugSearch($name: String!) {
  search(queryString: $name, entityNames: ["drug"], page: {index: 0, size: 1}) {
    hits { id name entity }
  }
}
"""

_DRUG_INDICATIONS_QUERY = """
query DrugIndications($chemblId: String!) {
  drug(chemblId: $chemblId) {
    indications {
      rows {
        maxClinicalStage
        disease { id name }
      }
    }
  }
}
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_rows(path: Path) -> list[dict]:
    """Read a GtoPdb CSV, skipping its leading '# GtoPdb Version: ...' comment line."""
    with path.open(encoding="utf-8", newline="") as handle:
        lines = handle.readlines()
    if lines and lines[0].lstrip().startswith('"#'):
        lines = lines[1:]
    return list(csv.DictReader(lines))


def _retry_wait(exc: Exception, fallback_delay: float) -> float:
    """Honor a 429 response's Retry-After header when present, else use the normal backoff."""
    if isinstance(exc, HTTPError) and exc.code == 429 and exc.headers:
        retry_after = exc.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return fallback_delay


def _get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    for delay in _RETRY_DELAYS:
        try:
            with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            if delay is None:
                raise
            time.sleep(_retry_wait(exc, delay))
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
        except (HTTPError, URLError, TimeoutError) as exc:
            if delay is None:
                raise
            time.sleep(_retry_wait(exc, delay))
    raise RuntimeError("unreachable")  # pragma: no cover


def _parallel_map(items: list, worker, label: str) -> list[dict]:
    """Run worker(item) -> list[dict] across items with modest concurrency.

    Logs periodic progress, since these fetches are otherwise a long silent
    stretch in CI -- see the "Refresh data" workflow's Actions log.
    """
    records: list[dict] = []
    total = len(items)
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = [executor.submit(worker, item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            records.extend(future.result())
            completed += 1
            if completed % _PROGRESS_EVERY == 0 or completed == total:
                print(f"  {label}: {completed}/{total}", flush=True)
    return records


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


_TRIAL_FIELDS = "NCTId,BriefTitle,OverallStatus,Phase,Condition,InterventionName,WhyStopped"


def _trial_worker(drug: dict) -> list[dict]:
    """Fetch one drug's CT.gov trials, keeping only name-matched interventions."""
    name = drug["ligand_name"]
    if len(name) < CTGOV_MIN_NAME_LENGTH:
        return []

    query = urlencode({"query.intr": name, "pageSize": CTGOV_PAGE_SIZE, "fields": _TRIAL_FIELDS})
    time.sleep(_REQUEST_PAUSE)
    try:
        payload = _get_json(f"{CTGOV_API}?{query}")
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"  ! ClinicalTrials.gov query failed for {name}: {exc}")
        return []

    records: list[dict] = []
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
                "why_stopped": protocol.get("statusModule", {}).get("whyStopped"),
                "phases": protocol.get("designModule", {}).get("phases", []),
                "conditions": protocol.get("conditionsModule", {}).get("conditions", []),
                "matched_intervention": matched,
            }
        )
    return records


def _fetch_trials(drugs: list[dict]) -> list[dict]:
    return _parallel_map(drugs, _trial_worker, "ClinicalTrials.gov")


def _target_disease_worker(target: dict) -> list[dict]:
    """Fetch one target's top-K, score-thresholded disease associations."""
    time.sleep(_REQUEST_PAUSE)
    payload = {
        "query": _ASSOCIATED_DISEASES_QUERY,
        "variables": {"ensemblId": target["ensembl_gene_id"], "size": OPEN_TARGETS_TOP_K},
    }
    try:
        response = _post_json(OPEN_TARGETS_API, payload)
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"  ! Open Targets query failed for {target['ensembl_gene_id']}: {exc}")
        return []

    records: list[dict] = []
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


def _fetch_target_diseases(targets: list[dict]) -> list[dict]:
    return _parallel_map(targets, _target_disease_worker, "Open Targets target-disease")


def _drug_indication_worker(drug: dict) -> list[dict]:
    """Resolve one drug to a ChEMBL ID via search, then keep only its APPROVAL-stage indications."""
    name = drug["ligand_name"]
    if len(name) < OPEN_TARGETS_MIN_DRUG_NAME_LENGTH:
        return []

    time.sleep(_REQUEST_PAUSE)
    try:
        search_response = _post_json(
            OPEN_TARGETS_API, {"query": _DRUG_SEARCH_QUERY, "variables": {"name": name}}
        )
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"  ! Open Targets drug search failed for {name}: {exc}")
        return []
    hits = ((search_response.get("data") or {}).get("search") or {}).get("hits", [])
    chembl_id = next((hit["id"] for hit in hits if hit.get("entity") == "drug"), None)
    if not chembl_id:
        return []

    time.sleep(_REQUEST_PAUSE)
    try:
        indications_response = _post_json(
            OPEN_TARGETS_API,
            {
                "query": _DRUG_INDICATIONS_QUERY,
                "variables": {"chemblId": chembl_id},
            },
        )
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"  ! Open Targets indications query failed for {chembl_id} ({name}): {exc}")
        return []

    records: list[dict] = []
    drug_data = (indications_response.get("data") or {}).get("drug") or {}
    rows = (drug_data.get("indications") or {}).get("rows", [])[:OPEN_TARGETS_MAX_INDICATIONS]
    for row in rows:
        if row.get("maxClinicalStage") != OPEN_TARGETS_APPROVAL_STAGE:
            continue
        disease = row.get("disease") or {}
        disease_id = disease.get("id")
        if not disease_id:
            continue
        records.append(
            {
                "ligand_id": drug["ligand_id"],
                "ligand_name": name,
                "chembl_id": chembl_id,
                "disease_id": disease_id,
                "disease_name": disease.get("name"),
                "max_clinical_stage": row.get("maxClinicalStage"),
            }
        )
    return records


def _fetch_drug_indications(drugs: list[dict]) -> list[dict]:
    return _parallel_map(drugs, _drug_indication_worker, "Open Targets drug indications")


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

    print(f"Querying Open Targets for approved indications of {len(drugs)} approved drugs...")
    indications = _fetch_drug_indications(drugs)
    OPEN_TARGETS_INDICATIONS_JSON.write_text(
        json.dumps(indications, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OPEN_TARGETS_INDICATIONS_JSON} ({len(indications)} approved indications)")

    manifest_path = RAW_DIR / "manifest_drug_associations.json"
    manifest_path.write_text(
        json.dumps(
            {
                "fetched_at": fetched_at,
                "clinicaltrials_gov": {
                    "homepage": "https://clinicaltrials.gov/",
                    "license_url": None,
                    "notes": "Public registry metadata only; preserve NCT identifiers.",
                    "query": "query.intr=<drug name>, name-match filtered",
                    "min_drug_name_length": CTGOV_MIN_NAME_LENGTH,
                    "drug_count": len(drugs),
                    "trial_link_count": len(trials),
                    "filename": CLINICALTRIALS_TRIALS_JSON.name,
                    "sha256": _sha256(CLINICALTRIALS_TRIALS_JSON),
                },
                "open_targets": {
                    "homepage": "https://platform.opentargets.org/",
                    "license_url": "https://platform-docs.opentargets.org/licence",
                    "notes": "CC0. Association scores are a computed evidence aggregate, not a clinical indication.",
                    "query": "target(ensemblId).associatedDiseases",
                    "top_k": OPEN_TARGETS_TOP_K,
                    "min_score": OPEN_TARGETS_MIN_SCORE,
                    "target_count": len(targets),
                    "association_count": len(diseases),
                    "filename": OPEN_TARGETS_DISEASES_JSON.name,
                    "sha256": _sha256(OPEN_TARGETS_DISEASES_JSON),
                },
                "open_targets_indications": {
                    "homepage": "https://platform.opentargets.org/",
                    "license_url": "https://platform-docs.opentargets.org/licence",
                    "notes": (
                        "CC0. Only indications at the 'APPROVAL' maximum clinical stage are "
                        "kept; drug names are resolved to ChEMBL IDs via Open Targets' own "
                        "search endpoint."
                    ),
                    "query": "search(drug name) -> drug(chemblId).indications, APPROVAL only",
                    "min_drug_name_length": OPEN_TARGETS_MIN_DRUG_NAME_LENGTH,
                    "drug_count": len(drugs),
                    "indication_count": len(indications),
                    "filename": OPEN_TARGETS_INDICATIONS_JSON.name,
                    "sha256": _sha256(OPEN_TARGETS_INDICATIONS_JSON),
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
