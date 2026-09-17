"""GTEx normal-tissue gene-expression adapter.

Reads a local JSON export produced by ``scripts/fetch_gtex_expression.py``
(GTEx's public ``/api/v2/expression/medianGeneExpression`` endpoint, no key
required) -- per-tissue **median** expression (TPM) for a gene, not
sample-level or genotype data. GTEx's public portal explicitly describes
this level of data as open access; this adapter only ever requests the
aggregate median-expression endpoint, never GTEx's restricted
individual-level genotype data.

Represents each GTEx tissue as its own Tissue entity (keyed by the tissue's
UBERON ontology ID, which GTEx's API already returns) rather than folding
tissue into edge metadata, so tissue entities can be queried/reused
independently -- e.g. for interpreting an ADC antigen target's normal-tissue
expression, per Issue #10.
"""

import json
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


@registry.register
class GtexAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="gtex",
        name="GTEx",
        homepage="https://gtexportal.org/",
        license_url="https://gtexportal.org/home/license",
        redistribution=RedistributionPolicy.OPEN,
        notes=(
            "GTEx's public portal describes gene-expression data as open access. Only "
            "aggregate per-tissue median expression (TPM) is fetched, never "
            "individual-level genotype/sample data, which GTEx separately restricts."
        ),
        source_type=SourceType.CURATED_DATABASE,
        license="GTEx open access (aggregate expression only)",
    )

    def __init__(self, expression_path: str | Path, release: str | None = None):
        self.expression_path = Path(expression_path)
        self.release = release

    def _records(self) -> list[dict]:
        return json.loads(self.expression_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen_genes: set[str] = set()
        seen_tissues: set[str] = set()
        for row in self._records():
            gene_id = row.get("ensembl_gene_id")
            if gene_id and gene_id not in seen_genes:
                seen_genes.add(gene_id)
                yield EntityRecord(
                    entity_type="gene",
                    name=row.get("gene_symbol") or gene_id,
                    identifiers=(ExternalIdentifier("ensembl", gene_id),),
                    metadata={"release": self.release},
                )
            tissue_uberon = row.get("tissue_uberon_id")
            if tissue_uberon and tissue_uberon not in seen_tissues:
                seen_tissues.add(tissue_uberon)
                yield EntityRecord(
                    entity_type="tissue",
                    name=(row.get("tissue_id") or tissue_uberon).replace("_", " "),
                    identifiers=(ExternalIdentifier("uberon", tissue_uberon),),
                    metadata={"release": self.release},
                )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            gene_id = row.get("ensembl_gene_id")
            tissue_uberon = row.get("tissue_uberon_id")
            if not gene_id or not tissue_uberon:
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier("ensembl", gene_id),
                predicate="expressed_in",
                object=ExternalIdentifier("uberon", tissue_uberon),
                source_record_id=f"{gene_id}:{tissue_uberon}:{row.get('dataset_id')}",
                evidence_type="gtex_median_expression",
                context={
                    "median_tpm": row.get("median_tpm"),
                    "unit": row.get("unit"),
                    "dataset_id": row.get("dataset_id"),
                    "release": self.release,
                },
            )
