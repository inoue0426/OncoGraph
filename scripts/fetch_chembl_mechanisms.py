"""Fetch ChEMBL drug mechanism-of-action records for a list of drug names.

ChEMBL (https://www.ebi.ac.uk/chembl/) is released under CC BY-SA 3.0
(confirmed live). Uses only ChEMBL's public REST API (no key required):
molecule search (name -> ChEMBL ID), /mechanism (ChEMBL ID -> mechanism
records), and /target (target ChEMBL ID -> UniProt accession) -- never a
bulk database dump.

For each name: search -> take the top exact/preferred-name match -> fetch
its mechanisms -> resolve each mechanism's target to a UniProt accession.
Names with no ChEMBL molecule match, or a match with no recorded mechanism,
are skipped (recorded in the summary printed at the end) rather than guessed
at.

Run:
    python scripts/fetch_chembl_mechanisms.py --drug-names-file names.txt
    # or, to derive the name list from a deployed search-index.json:
    python scripts/fetch_chembl_mechanisms.py --from-search-index web/data/search-index.json
"""

import argparse
import http.client
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"
OUTPUT_PATH = Path("data/raw/chembl_mechanisms.json")
_USER_AGENT = "OncoGraph/0.1 research database"
_HTTP_TIMEOUT = 30
_REQUEST_DELAY_SECONDS = 0.2


def _get_json(url: str) -> dict | None:
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            return json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
        return None
    finally:
        time.sleep(_REQUEST_DELAY_SECONDS)


def _resolve_chembl_id(drug_name: str) -> str | None:
    data = _get_json(f"{BASE_URL}/molecule/search.json?q={quote(drug_name)}&limit=5")
    if not data:
        return None
    for molecule in data.get("molecules", []):
        if (molecule.get("pref_name") or "").lower() == drug_name.lower():
            return molecule.get("molecule_chembl_id")
    molecules = data.get("molecules", [])
    return molecules[0].get("molecule_chembl_id") if molecules else None


def _mechanisms_for(chembl_id: str) -> list[dict]:
    data = _get_json(f"{BASE_URL}/mechanism.json?molecule_chembl_id={chembl_id}&limit=25")
    return data.get("mechanisms", []) if data else []


def _target_uniprot_and_symbol(target_chembl_id: str) -> tuple[str | None, str | None]:
    data = _get_json(f"{BASE_URL}/target.json?target_chembl_id={target_chembl_id}")
    if not data:
        return None, None
    targets = data.get("targets", [])
    if not targets:
        return None, None
    components = targets[0].get("target_components", [])
    if not components:
        return None, None
    accession = components[0].get("accession")
    gene_symbol = next(
        (
            syn.get("component_synonym")
            for syn in components[0].get("target_component_synonyms", [])
            if syn.get("syn_type") == "GENE_SYMBOL"
        ),
        None,
    )
    return accession, gene_symbol


def _read_drug_names(args: argparse.Namespace) -> list[str]:
    if args.drug_names_file:
        return [line.strip() for line in Path(args.drug_names_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    entities = json.loads(Path(args.from_search_index).read_text(encoding="utf-8"))
    names = [e["name"] for e in entities if e.get("type", "").upper() == "DRUG"]
    if args.limit:
        names = names[: args.limit]
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--drug-names-file", type=str)
    group.add_argument("--from-search-index", type=str)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N drug names")
    args = parser.parse_args()

    names = _read_drug_names(args)
    records = []
    no_match = 0
    no_mechanism = 0
    target_cache: dict[str, tuple[str | None, str | None]] = {}

    for i, name in enumerate(names):
        chembl_id = _resolve_chembl_id(name)
        if not chembl_id:
            no_match += 1
            continue
        mechanisms = _mechanisms_for(chembl_id)
        if not mechanisms:
            no_mechanism += 1
            continue
        resolved_mechanisms = []
        for mechanism in mechanisms:
            target_chembl_id = mechanism.get("target_chembl_id")
            if not target_chembl_id:
                continue
            if target_chembl_id not in target_cache:
                target_cache[target_chembl_id] = _target_uniprot_and_symbol(target_chembl_id)
            uniprot, gene_symbol = target_cache[target_chembl_id]
            if not uniprot:
                continue
            resolved_mechanisms.append(
                {
                    "action_type": mechanism.get("action_type"),
                    "mechanism_of_action": mechanism.get("mechanism_of_action"),
                    "target_chembl_id": target_chembl_id,
                    "target_uniprot": uniprot,
                    "target_gene_symbol": gene_symbol,
                    "max_phase": mechanism.get("max_phase"),
                    "mec_id": mechanism.get("mec_id"),
                    "mechanism_refs": mechanism.get("mechanism_refs") or [],
                }
            )
        if resolved_mechanisms:
            records.append({"drug_name": name, "chembl_id": chembl_id, "mechanisms": resolved_mechanisms})
        if (i + 1) % 25 == 0:
            print(f"...{i + 1}/{len(names)} processed, {len(records)} with a resolved mechanism so far")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(
        f"Wrote {OUTPUT_PATH}: {len(records)}/{len(names)} drugs with a resolved mechanism "
        f"({no_match} no ChEMBL match, {no_mechanism} matched but no mechanism record)"
    )


if __name__ == "__main__":
    main()
