"""DepMap gene-dependency adapter -- SCAFFOLD ONLY, no real data.

DepMap's CRISPR dependency scores are distributed as large
genes-by-cell-lines matrices (Figshare releases, hundreds of MB) -- exactly
the "large raw data matrix" this repository's stated policy (docs/SOURCES.md,
Issue #10's own "prefer compact context-level summaries... never large
matrices in git or GitHub Pages") says not to commit or fetch wholesale.

This adapter therefore:

- reads a **local**, already-compacted export the caller must produce
  themselves (e.g. per gene-cell_line the single dependency score that
  matters, not the full matrix) -- it never downloads from DepMap/Figshare
  itself;
- is not registered with any fetch script, and is not wired into the
  scheduled data-refresh pipeline;
- represents a Cellosaurus-keyed cell line as the context, not a new graph
  entity type, reusing the existing ``cell_line`` EntityType (Issue #6).
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
class DepMapAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="depmap",
        name="DepMap",
        homepage="https://depmap.org/portal/",
        license_url="https://depmap.org/portal/data_page/?tab=overview",
        redistribution=RedistributionPolicy.UNKNOWN,
        notes=(
            "Distributed as large genes-by-cell-lines dependency matrices; this repository "
            "does not commit or fetch raw matrices. This adapter reads a local, "
            "caller-supplied *compact* export (one score per gene/cell-line pair that "
            "matters) only; not wired into any pipeline."
        ),
        source_type=SourceType.CURATED_DATABASE,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        """Expected local record shape (one per gene-cell_line dependency row)::

        {
          "hgnc_id": "HGNC:3236", "gene_symbol": "EGFR",
          "cellosaurus_id": "CVCL_0023", "cell_line_name": "A549",
          "dependency_score": -0.87, "dataset": "CRISPR_(DepMap_Public_23Q4)"
        }
        """
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen_genes: set[str] = set()
        seen_lines: set[str] = set()
        for row in self._records():
            hgnc_id = (row.get("hgnc_id") or "").strip()
            if hgnc_id and hgnc_id not in seen_genes:
                seen_genes.add(hgnc_id)
                yield EntityRecord(
                    entity_type="gene",
                    name=row.get("gene_symbol") or hgnc_id,
                    identifiers=(ExternalIdentifier("hgnc", hgnc_id),),
                    metadata={"release": self.release},
                )
            cvcl_id = (row.get("cellosaurus_id") or "").strip()
            if cvcl_id and cvcl_id not in seen_lines:
                seen_lines.add(cvcl_id)
                yield EntityRecord(
                    entity_type="cell_line",
                    name=row.get("cell_line_name") or cvcl_id,
                    identifiers=(ExternalIdentifier("cellosaurus", cvcl_id),),
                    metadata={"release": self.release},
                )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            hgnc_id = (row.get("hgnc_id") or "").strip()
            cvcl_id = (row.get("cellosaurus_id") or "").strip()
            if not hgnc_id or not cvcl_id:
                continue
            score = row.get("dependency_score")
            yield EdgeRecord(
                subject=ExternalIdentifier("hgnc", hgnc_id),
                predicate="essential_in",
                object=ExternalIdentifier("cellosaurus", cvcl_id),
                source_record_id=f"{hgnc_id}:{cvcl_id}:{row.get('dataset')}",
                evidence_type="depmap_dependency",
                confidence=None,  # a dependency score is not a 0-1 confidence; kept in context
                context={"dependency_score": score, "dataset": row.get("dataset"), "release": self.release},
            )
