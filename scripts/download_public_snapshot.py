"""Copy the published OncoGraph snapshot for the optional local Q&A site.

Run from the repository root: python scripts/download_public_snapshot.py
Downloads only three hard-coded public GitHub Pages JSON files over HTTPS.
"""

import json
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://inoue0426.github.io/OncoGraph/data/"
OUTPUT = Path("web/data")
FILES = {"search-index.json": list, "relations.json": list, "stats.json": dict}
MAX_FILE_BYTES = 250 * 1024 * 1024


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for filename, expected in FILES.items():
        target = OUTPUT / filename
        temporary = OUTPUT / (filename + ".download")
        total = 0
        try:
            with urlopen(Request(BASE + filename, headers={"User-Agent": "OncoGraph-local/0.1"}),
                         timeout=60) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_FILE_BYTES:
                        raise ValueError(f"{filename} exceeds the size limit")
                    output.write(block)
            with temporary.open(encoding="utf-8") as source:
                value = json.load(source)
            if not isinstance(value, expected) or not value:
                raise ValueError(f"{filename} is not a nonempty {expected.__name__}")
            temporary.replace(target)
            print(f"Saved {target} ({total} bytes)")
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
