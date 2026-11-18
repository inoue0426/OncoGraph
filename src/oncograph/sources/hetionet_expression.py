"""Source-backed STARGEO expression associations from Hetionet v1.0.

This is one input used by SIGMA-KG, not a reconstruction of its disease layer.
Direction is normalized to Gene -> Disease; differential expression is an
association and never a claim that the gene causes the disease.
"""

import bz2
from collections.abc import Iterator
from pathlib import Path

from ..signed_molecular import SignedImportReport, stable_digest
from .base import (
    EdgeRecord,
    EntityRecord,
    ExternalIdentifier,
    RedistributionPolicy,
    SourceDescriptor,
    SourceType,
)
from .sigma_sources import file_sha256

HETIONET_URL = (
    "https://github.com/hetio/hetionet/raw/refs/heads/main/hetnet/json/hetionet-v1.0.json.bz2"
)
HETIONET_DESCRIPTOR = SourceDescriptor(
    key="hetionet_stargeo_expression",
    name="Hetionet v1.0 STARGEO disease expression associations",
    homepage="https://github.com/hetio/hetionet",
    license="CC0 1.0 (selected STARGEO edges)",
    license_url="https://github.com/hetio/hetionet/blob/main/README.md#license",
    redistribution=RedistributionPolicy.OPEN,
    source_type=SourceType.COMPUTED,
    notes="Per-edge CC0 required; disease node labels separately carry CC BY 3.0.",
)


def json_items(path: Path, prefix: str) -> Iterator[dict]:
    """Stream selected top-level JSON arrays without loading the whole graph.

    Args:
        path: Official compressed JSON graph.
        prefix: ijson prefix for node or edge array elements.

    Returns:
        Iterator of source JSON objects, preserving numeric score values.
    """
    import ijson

    with bz2.open(path, "rb") as handle:
        yield from ijson.items(handle, prefix, use_float=True)


class HetionetExpressionAdapter:
    """Import only licensed Disease up/downregulates Gene observations."""

    descriptor = HETIONET_DESCRIPTOR

    def __init__(self, path: Path):
        """Configure a local Hetionet v1.0 snapshot.

        Args:
            path: Original hetionet-v1.0.json.bz2.
        """
        self.path = path
        self.report = SignedImportReport()

    def disease_entities(self) -> Iterator[EntityRecord]:
        """Keep Disease Ontology identifiers, names and their independent license.

        Returns:
            Disease entities; no semantic or fuzzy disease-name harmonization.
        """
        digest = file_sha256(self.path)
        for node in json_items(self.path, "nodes.item"):
            if node["kind"] != "Disease":
                continue
            if (
                not str(node["identifier"]).startswith("DOID:")
                or node["data"].get("license") != "CC BY 3.0"
            ):
                raise ValueError("Unexpected Hetionet disease identity or licensing")
            yield EntityRecord(
                "disease",
                node["name"],
                (ExternalIdentifier("doid", node["identifier"]),),
                metadata={
                    "source": "Hetionet v1.0 / Disease Ontology",
                    "release": "v1.0",
                    "file_sha256": digest,
                    "original_node": node,
                    "license": "CC BY 3.0",
                },
            )

    def iter_edges(self) -> Iterator[EdgeRecord]:
        """Retain source statistics and normalize statement direction explicitly.

        Returns:
            Gene -> Disease expression associations with their original provenance.
        """
        self.report.reset()
        digest = file_sha256(self.path)
        for row in json_items(self.path, "edges.item"):
            self.report.input_records += 1
            if not {"source_id", "target_id", "kind", "data", "direction"} <= row.keys():
                raise ValueError("Unrecognized Hetionet edge schema")
            self.report.parsed_records += 1
            if (
                row["source_id"][0] != "Disease"
                or row["target_id"][0] != "Gene"
                or row["kind"] not in {"upregulates", "downregulates"}
            ):
                self.report.skipped["outside_disease_expression_scope"] += 1
                continue
            self.report.scoped_records += 1
            data = row["data"]
            if data.get("source") != "STARGEO" or data.get("license") != "CC0 1.0":
                self.report.skipped["unreviewed_source_or_license"] += 1
                continue
            sign = 1 if row["kind"] == "upregulates" else -1
            predicate = "upregulated_in" if sign == 1 else "downregulated_in"
            yield EdgeRecord(
                subject=ExternalIdentifier("ncbigene", str(row["target_id"][1])),
                predicate=predicate,
                object=ExternalIdentifier("doid", row["source_id"][1]),
                source_record_id=stable_digest(row),
                source_url=HETIONET_DESCRIPTOR.homepage,
                evidence_type="disease_expression_association",
                extraction_method="source_expression_association_transform",
                context={
                    "original_source_dataset": "STARGEO via Hetionet v1.0",
                    "release": "Hetionet v1.0",
                    "file_sha256": digest,
                    "original_predicate": row["kind"],
                    "original_direction": row["direction"],
                    "original_orientation": "Disease -> Gene",
                    "effect_sign": sign,
                    "biological_relationship": "disease_expression_association",
                    "observation_status": "transformed",
                    "model_generated": False,
                    "source_record_id_kind": "sha256_of_original_edge",
                    "source_native_record_id": None,
                    "original_row": row,
                    "original_score": data.get("log2_fold_change"),
                    "original_score_type": "log2_fold_change",
                    "taxon_id": 9606,
                    "causal_scope": "differential_expression_association_only",
                    "experimental_context": None,
                    "context_availability": "not supplied in edge export",
                    "sigma_balance_pruned": False,
                    "local_only": True,
                },
            )
