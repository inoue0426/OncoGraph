"""HGNC complete-set TSV adapter (HGNC data are CC0)."""

import csv
from collections.abc import Iterable
from pathlib import Path

from .base import (
    EntityRecord,
    ExternalIdentifier,
    RedistributionPolicy,
    SourceAdapter,
    SourceDescriptor,
    SourceType,
)
from .registry import registry


@registry.register
class HGNCAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="hgnc",
        name="HGNC",
        homepage="https://www.genenames.org/",
        license_url="https://www.genenames.org/about/license/",
        redistribution=RedistributionPolicy.OPEN,
        notes="HGNC data are released under CC0; attribution is recommended.",
        source_type=SourceType.CURATED_DATABASE,
        license="CC0",
    )

    def __init__(self, tsv_path: str | Path, release: str | None = None):
        self.tsv_path = Path(tsv_path)
        self.release = release

    def iter_entities(self) -> Iterable[EntityRecord]:
        with self.tsv_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                hgnc_id = row.get("hgnc_id", "").strip()
                symbol = row.get("symbol", "").strip()
                if not hgnc_id or not symbol:
                    continue
                identifiers = [ExternalIdentifier("hgnc", hgnc_id)]
                mappings = {
                    "entrez_id": "ncbigene",
                    "ensembl_gene_id": "ensembl",
                    "uniprot_ids": "uniprot",
                }
                for column, namespace in mappings.items():
                    for value in row.get(column, "").split("|"):
                        value = value.strip()
                        if value:
                            identifiers.append(ExternalIdentifier(namespace, value))
                aliases = [
                    value.strip()
                    for column in ("alias_symbol", "prev_symbol")
                    for value in row.get(column, "").split("|")
                    if value.strip()
                ]
                yield EntityRecord(
                    entity_type="gene",
                    name=symbol,
                    identifiers=tuple(identifiers),
                    description=row.get("name") or None,
                    metadata={
                        "status": row.get("status"),
                        "locus_type": row.get("locus_type"),
                        "location": row.get("location"),
                        "alias_symbol": row.get("alias_symbol"),
                        "prev_symbol": row.get("prev_symbol"),
                        # Names/former symbols are aliases, never identity --
                        # entity resolution always keys on canonical_id above.
                        "aliases": aliases or None,
                        "release": self.release,
                    },
                )

    def iter_edges(self):
        return iter(())
