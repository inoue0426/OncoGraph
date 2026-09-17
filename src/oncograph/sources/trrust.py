"""TRRUST curated transcription-factor regulation adapter.

Reads TRRUST's official human raw-data TSV (``TF``, ``Target``, ``Mode``,
``PMID`` columns) plus the same HGNC complete-set file already used
elsewhere in this repository, to resolve TRRUST's bare gene *symbols* to
stable HGNC identifiers before emitting anything -- TRRUST itself carries no
identifier, only symbols, and this repository's identifier-first policy
(docs/EVIDENCE.md) never matches entities by name/symbol alone. A symbol
TRRUST uses that HGNC's current symbol/alias/previous-symbol columns don't
resolve is skipped, not guessed at.

TRRUST is released under CC BY-SA 4.0 (confirmed live at grnpedia.org).

Represents a transcription factor as a Gene entity with its regulatory role
carried only in the predicate/evidence -- not a separate entity type, since
a transcription factor is still fundamentally a gene/protein product.
"""

import csv
from collections.abc import Iterable
from pathlib import Path

from .base import (
    EdgeRecord,
    EntityRecord,
    ExternalIdentifier,
    RedistributionPolicy,
    SourceAdapter,
    SourceDescriptor,
    SourceType,
)
from .registry import registry

_MODE_PREDICATES = {
    "Activation": "positively_regulates_expression_of",
    "Repression": "negatively_regulates_expression_of",
    "Unknown": "regulates_expression_of",
}


def _build_symbol_index(hgnc_path: Path) -> dict[str, str]:
    """Symbol/alias/previous-symbol -> canonical HGNC ID, from the official file only."""
    index: dict[str, str] = {}
    with hgnc_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            hgnc_id = (row.get("hgnc_id") or "").strip()
            if not hgnc_id:
                continue
            symbols = [row.get("symbol", "")]
            symbols += row.get("alias_symbol", "").split("|")
            symbols += row.get("prev_symbol", "").split("|")
            for symbol in symbols:
                symbol = symbol.strip()
                # A current, unambiguous symbol always wins; never overwrite
                # it with a stale alias/previous-symbol pointing elsewhere.
                if symbol and (symbol not in index or symbol == row.get("symbol", "").strip()):
                    index[symbol] = hgnc_id
    return index


@registry.register
class TrrustAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="trrust",
        name="TRRUST",
        homepage="https://www.grnpedia.org/trrust/",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        redistribution=RedistributionPolicy.OPEN,
        notes=(
            "CC BY-SA 4.0 (confirmed live at grnpedia.org). Gene symbols are resolved to "
            "HGNC IDs via the official HGNC complete-set file before import; unresolvable "
            "symbols are skipped rather than matched by name."
        ),
        source_type=SourceType.CURATED_DATABASE,
        license="CC BY-SA 4.0",
    )

    def __init__(self, trrust_tsv_path: str | Path, hgnc_path: str | Path, release: str | None = None):
        self.trrust_tsv_path = Path(trrust_tsv_path)
        self.hgnc_path = Path(hgnc_path)
        self.release = release

    def _rows(self) -> Iterable[dict]:
        with self.trrust_tsv_path.open(encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle, delimiter="\t", fieldnames=("tf", "target", "mode", "pmids"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        symbol_to_hgnc = _build_symbol_index(self.hgnc_path)
        seen: set[str] = set()
        for row in self._rows():
            for column in ("tf", "target"):
                symbol = (row.get(column) or "").strip()
                hgnc_id = symbol_to_hgnc.get(symbol)
                if not hgnc_id or hgnc_id in seen:
                    continue
                seen.add(hgnc_id)
                yield EntityRecord(
                    entity_type="gene",
                    name=symbol,
                    identifiers=(ExternalIdentifier("hgnc", hgnc_id),),
                    metadata={"release": self.release},
                )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        symbol_to_hgnc = _build_symbol_index(self.hgnc_path)
        for row in self._rows():
            tf_id = symbol_to_hgnc.get((row.get("tf") or "").strip())
            target_id = symbol_to_hgnc.get((row.get("target") or "").strip())
            if not tf_id or not target_id:
                continue
            mode = (row.get("mode") or "").strip()
            pmids = [p.strip() for p in (row.get("pmids") or "").split(";") if p.strip()]
            yield EdgeRecord(
                subject=ExternalIdentifier("hgnc", tf_id),
                predicate=_MODE_PREDICATES.get(mode, "regulates_expression_of"),
                object=ExternalIdentifier("hgnc", target_id),
                source_record_id=f"{tf_id}:{target_id}",
                evidence_type="trrust_tf_target_regulation",
                publication=ExternalIdentifier("pmid", pmids[0]) if pmids else None,
                context={"mode": mode, "pmids": pmids, "release": self.release},
            )
