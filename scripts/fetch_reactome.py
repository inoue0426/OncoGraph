"""Fetch Reactome's official NCBI Gene-to-pathway mapping file.

Reactome data (the database and files derived from it) is CC0 -- see
https://reactome.org/license. Only the official flat mapping file is
fetched, not a bulk database dump.

Run:
    python scripts/fetch_reactome.py
"""

from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://reactome.org/download/current/NCBI2Reactome.txt"
OUTPUT_PATH = Path("data/raw/NCBI2Reactome.txt")
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
