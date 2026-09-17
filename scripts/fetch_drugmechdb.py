"""Fetch DrugMechDB's official curated drug-mechanism-path export.

DrugMechDB (https://github.com/SuLab/DrugMechDB) is released under CC0
(confirmed via the repository's GitHub license metadata) -- no restriction
on redistribution. Fetches only the single ``indication_paths.json`` file,
not a repository clone.

Run:
    python scripts/fetch_drugmechdb.py
"""

from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://raw.githubusercontent.com/SuLab/DrugMechDB/main/indication_paths.json"
OUTPUT_PATH = Path("data/raw/drugmechdb_indication_paths.json")
_USER_AGENT = "OncoGraph/0.1 research database"
_HTTP_TIMEOUT = 120


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    request = Request(URL, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=_HTTP_TIMEOUT) as response, OUTPUT_PATH.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
