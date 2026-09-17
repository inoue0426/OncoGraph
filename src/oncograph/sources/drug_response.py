"""Drug-response / experimental-model adapter -- generic, source-agnostic.

**Scaffold, not wired to a specific vendor dataset.** DepMap/CCLE, GDSC,
PRISM, Cell Model Passports, and LINCS/L1000 are all real candidates, but
their full datasets are large (hundreds of MB to multi-GB) and not
appropriate to fetch/commit into this repository regardless of licensing;
verifying every one's current redistribution terms in detail was also out of
scope for this pass (see ``docs/DRUG_RESPONSE.md``). This adapter defines the
schema/predicate/context shape so a real source can be wired in later --
reading a small, locally-permitted export -- without a redesign.

Reads a local JSON list of response records::

    {
      "drug_namespace": "gtopdb", "drug_id": "4941", "drug_name": "gefitinib",
      "model_type": "cell_line",              # cell_line | pdx | organoid | cohort
      "model_namespace": "cellosaurus", "model_id": "CVCL_0023", "model_name": "A549",
      "disease": "lung adenocarcinoma", "tissue": "lung",
      "metric_type": "IC50",                  # IC50 | EC50 | AUC | VIABILITY | SENSITIVITY |
                                               # RESISTANCE | CR | PR | SD | PD
      "value": 0.42, "unit": "uM",            # for continuous metrics; omit for categorical ones
      "qualitative_label": null,               # e.g. "SENSITIVE" / "CR" for categorical metrics
      "assay": "CellTiter-Glo viability assay",
      "dose": "1 uM", "timepoint": "72h",
      "source_dataset": "GDSC2", "source_record_id": "...", "source_url": "..."
    }

Every response record becomes one ``tested_in`` edge (Drug -> Model), with
the measurement itself carried entirely in ``context`` -- never forced into
``confidence`` or any other cross-metric-comparable field, since IC50 (a
concentration), AUC (a unitless curve summary), viability (a percentage),
and RECIST-style categories (CR/PR/SD/PD) are not on the same scale and must
not be silently treated as if they were.
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

_VALID_MODEL_TYPES = {"cell_line", "pdx", "organoid", "cohort"}
_VALID_METRIC_TYPES = {
    "IC50",
    "EC50",
    "AUC",
    "VIABILITY",
    "SENSITIVITY",
    "RESISTANCE",
    "CR",
    "PR",
    "SD",
    "PD",
}


@registry.register
class DrugResponseAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="drug_response",
        name="Drug response (generic/scaffold)",
        homepage="https://depmap.org/",
        redistribution=RedistributionPolicy.UNKNOWN,
        notes=(
            "Schema/adapter scaffold only. No specific vendor dataset (DepMap/CCLE, GDSC, "
            "PRISM, Cell Model Passports, LINCS/L1000) is fetched or bundled -- those "
            "datasets are large and their current redistribution terms were not fully "
            "verified in this pass. Accepts a generic local file so a real, permitted "
            "source/export can be wired in without changing the predicate/context shape."
        ),
        source_type=SourceType.UNKNOWN,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def _models(self) -> dict[tuple[str, str], dict]:
        models: dict[tuple[str, str], dict] = {}
        for row in self._records():
            model_type = (row.get("model_type") or "").strip().lower()
            namespace = (row.get("model_namespace") or "").strip()
            value = (row.get("model_id") or "").strip()
            if model_type not in _VALID_MODEL_TYPES or not namespace or not value:
                continue
            key = (namespace, value)
            if key not in models:
                models[key] = {
                    "model_type": model_type,
                    "name": row.get("model_name"),
                    "disease": row.get("disease"),
                    "tissue": row.get("tissue"),
                }
        return models

    def iter_entities(self) -> Iterable[EntityRecord]:
        for (namespace, value), info in self._models().items():
            yield EntityRecord(
                entity_type=info["model_type"],
                name=info["name"] or value,
                identifiers=(ExternalIdentifier(namespace, value),),
                metadata={
                    "disease": info["disease"],
                    "tissue": info["tissue"],
                    "release": self.release,
                },
            )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for i, row in enumerate(self._records()):
            model_type = (row.get("model_type") or "").strip().lower()
            metric_type = (row.get("metric_type") or "").strip().upper()
            drug_namespace = (row.get("drug_namespace") or "").strip()
            drug_id = (row.get("drug_id") or "").strip()
            model_namespace = (row.get("model_namespace") or "").strip()
            model_id = (row.get("model_id") or "").strip()
            if (
                model_type not in _VALID_MODEL_TYPES
                or metric_type not in _VALID_METRIC_TYPES
                or not all((drug_namespace, drug_id, model_namespace, model_id))
            ):
                continue
            yield EdgeRecord(
                subject=ExternalIdentifier(drug_namespace, drug_id),
                predicate="tested_in",
                object=ExternalIdentifier(model_namespace, model_id),
                source_record_id=row.get("source_record_id") or str(i),
                source_url=row.get("source_url"),
                context={
                    "release": self.release,
                    "metric_type": metric_type,
                    "value": row.get("value"),
                    "unit": row.get("unit"),
                    "qualitative_label": row.get("qualitative_label"),
                    "disease": row.get("disease"),
                    "tissue": row.get("tissue"),
                    "assay": row.get("assay"),
                    "dose": row.get("dose"),
                    "timepoint": row.get("timepoint"),
                    "source_dataset": row.get("source_dataset"),
                },
                evidence_type=f"drug_response_{metric_type.lower()}",
            )
