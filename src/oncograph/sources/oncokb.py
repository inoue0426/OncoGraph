"""OncoKB clinical actionability adapter -- SCAFFOLD ONLY, no real data.

Verified during Issue #5 review: OncoKB's public ``/api/v1/info`` endpoint is
open, but actual gene/variant/actionability endpoints (e.g. ``/api/v1/genes``)
return ``401 Unauthorized`` without a registered API token
(https://www.oncokb.org/account/register), and OncoKB's terms require a data
usage agreement for any redistribution beyond individual, permitted use --
not something this repository can satisfy by fetching data automatically.

This adapter therefore:

- reads a **local** JSON file the caller must already have (e.g. exported via
  their own token-authenticated OncoKB API access, under their own OncoKB
  data usage agreement) -- it never calls OncoKB's API itself;
- is not registered with any fetch script, and is not wired into the
  scheduled data-refresh pipeline;
- exists so the mapping to OncoGraph's schema is designed and testable now,
  without committing or redistributing any actual OncoKB content.

OncoKB annotations (evidence levels, actionability) are curated
clinical/actionability calls distinct from CIViC's community curation and
from DGIdb's aggregated interaction scores -- kept under their own
``source="oncokb"`` / ``source_type=CURATED_DATABASE`` and never merged into
either of those.
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
class OncoKbAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="oncokb",
        name="OncoKB",
        homepage="https://www.oncokb.org/",
        license_url="https://www.oncokb.org/terms",
        redistribution=RedistributionPolicy.RESTRICTED,
        notes=(
            "Data endpoints require a registered API token (verified: /api/v1/genes "
            "returns 401 without one) and OncoKB's terms require a data usage agreement "
            "for redistribution. This adapter reads a local, caller-supplied export only; "
            "it never fetches from OncoKB itself and is not wired into any pipeline."
        ),
        source_type=SourceType.CURATED_DATABASE,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        """Expected local record shape (one per gene-variant-drug-level-of-evidence row)::

        {
          "hugo_symbol": "EGFR", "entrez_gene_id": 1956,
          "alteration": "L858R",
          "drug_name": "Osimertinib", "ncit_id": "C112993",
          "level_of_evidence": "LEVEL_1",
          "cancer_type": "Non-Small Cell Lung Cancer",
          "citation_pmids": ["31151970"]
        }
        """
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen: set[tuple[str, str]] = set()
        for row in self._records():
            ncit_id = (row.get("ncit_id") or "").strip()
            if ncit_id and ("ncit", ncit_id) not in seen:
                seen.add(("ncit", ncit_id))
                yield EntityRecord(
                    entity_type="drug",
                    name=row.get("drug_name") or ncit_id,
                    identifiers=(ExternalIdentifier("ncit", ncit_id),),
                    metadata={"release": self.release},
                )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            ncit_id = (row.get("ncit_id") or "").strip()
            entrez_gene_id = row.get("entrez_gene_id")
            if not ncit_id or not entrez_gene_id:
                continue
            pmids = row.get("citation_pmids") or []
            yield EdgeRecord(
                subject=ExternalIdentifier("ncit", ncit_id),
                predicate="clinically_actionable_for",
                object=ExternalIdentifier("ncbigene", str(entrez_gene_id)),
                source_record_id=f"{ncit_id}:{entrez_gene_id}:{row.get('alteration')}",
                context={
                    "release": self.release,
                    "alteration": row.get("alteration"),
                    "level_of_evidence": row.get("level_of_evidence"),
                    "cancer_type": row.get("cancer_type"),
                },
                evidence_type="oncokb_actionability",
                publication=ExternalIdentifier("pmid", pmids[0]) if pmids else None,
            )
