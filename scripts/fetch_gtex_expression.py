"""Fetch GTEx per-tissue median gene-expression summaries for a gene list.

GTEx (https://gtexportal.org/) describes this level of data (aggregate,
per-tissue median TPM) as open access on its public portal. Uses only
GTEx's public REST API v2 -- ``/reference/gene`` (symbol -> GENCODE ID) and
``/expression/medianGeneExpression`` (GENCODE ID -> per-tissue median TPM)
-- never GTEx's separately-governed individual-level genotype/sample data.

Deliberately scoped to a curated gene list (oncology-relevant druggable
targets already present in this repository's graph, by default), not all
~55,000 GENCODE genes -- mirroring this repository's existing practice for
CIViC (docs/BIOLOGICAL_SOURCES.md: "a small curated gene list") rather than
an exhaustive per-gene crawl.

Run:
    python scripts/fetch_gtex_expression.py --gene-symbols-file genes.txt
    python scripts/fetch_gtex_expression.py   # uses the built-in oncology gene list
"""

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE_URL = "https://gtexportal.org/api/v2"
OUTPUT_PATH = Path("data/raw/gtex_median_expression.json")
DATASET_ID = "gtex_v8"
_USER_AGENT = "OncoGraph/0.1 research database"
_HTTP_TIMEOUT = 30
_REQUEST_DELAY_SECONDS = 0.2

# A representative, real, checked set of oncology-relevant druggable target
# genes -- not exhaustive; see the module docstring.
DEFAULT_GENE_SYMBOLS = [
    "EGFR", "ERBB2", "BRAF", "KRAS", "TP53", "PIK3CA", "PTEN", "ALK", "ROS1", "MET",
    "RET", "NTRK1", "FGFR1", "FGFR2", "FGFR3", "CDK4", "CDK6", "MDM2", "VEGFA", "KDR",
    "PDGFRA", "PDGFRB", "ABL1", "JAK2", "BTK", "BCL2", "PARP1", "ESR1", "AR", "MTOR",
    "AKT1", "SRC", "STAT3", "MYC", "CCND1", "RB1", "BRCA1", "BRCA2", "ATM", "CHEK2",
    "IDH1", "IDH2", "EZH2", "SMO", "PTCH1", "NOTCH1", "CTNNB1", "APC", "SMAD4", "KIT",
]


def _get_json(url: str) -> dict | None:
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            return json.loads(response.read())
    except (HTTPError, URLError, TimeoutError):
        return None
    finally:
        time.sleep(_REQUEST_DELAY_SECONDS)


def _gencode_id_for(symbol: str) -> str | None:
    data = _get_json(f"{BASE_URL}/reference/gene?geneId={quote(symbol)}&format=json")
    if not data:
        return None
    genes = data.get("data", [])
    exact = next((g for g in genes if g.get("geneSymbol") == symbol), None)
    gene = exact or (genes[0] if genes else None)
    return gene.get("gencodeId") if gene else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gene-symbols-file", type=str, default=None)
    args = parser.parse_args()

    if args.gene_symbols_file:
        symbols = [line.strip() for line in Path(args.gene_symbols_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        symbols = DEFAULT_GENE_SYMBOLS

    records = []
    unresolved = []
    for i, symbol in enumerate(symbols):
        gencode_id = _gencode_id_for(symbol)
        if not gencode_id:
            unresolved.append(symbol)
            continue
        data = _get_json(f"{BASE_URL}/expression/medianGeneExpression?gencodeId={gencode_id}&datasetId={DATASET_ID}")
        for row in (data or {}).get("data", []):
            records.append(
                {
                    "gene_symbol": symbol,
                    "ensembl_gene_id": gencode_id.split(".")[0],
                    "tissue_id": row.get("tissueSiteDetailId"),
                    "tissue_uberon_id": row.get("ontologyId"),
                    "median_tpm": row.get("median"),
                    "unit": row.get("unit"),
                    "dataset_id": row.get("datasetId"),
                }
            )
        if (i + 1) % 10 == 0:
            print(f"...{i + 1}/{len(symbols)} genes processed")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}: {len(records)} (gene, tissue) rows for {len(symbols) - len(unresolved)} genes")
    if unresolved:
        print(f"Unresolved gene symbols (no GTEx GENCODE match): {unresolved}")


if __name__ == "__main__":
    main()
