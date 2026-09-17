"""Fetch TRRUST's official human transcription-factor-target TSV.

TRRUST (https://www.grnpedia.org/trrust/) is released under CC BY-SA 4.0
(confirmed live). Fetches only the official raw-data file, not a scrape of
the browsing UI.

Run:
    python scripts/fetch_trrust.py
"""

from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://www.grnpedia.org/trrust/data/trrust_rawdata.human.tsv"
OUTPUT_PATH = Path("data/raw/trrust_rawdata.human.tsv")
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
