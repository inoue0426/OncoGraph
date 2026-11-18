"""Original-source adapters used by SIGMA-KG, not its unavailable pruned graph.

Only explicit source polarity is imported. A LINCS consensus z-score is not a
binding measurement, direct target claim, or patient-specific causal effect.
"""

import csv
import gzip
import hashlib
import math
import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from ..signed_molecular import SIGNED_RELATIONS, SignedImportReport, stable_digest
from .base import (
    EdgeRecord,
    EntityRecord,
    ExternalIdentifier,
    RedistributionPolicy,
    SourceDescriptor,
    SourceType,
)

LINCS_URL = "https://maayanlab.cloud/static/hdfs/harmonizome/data/l1000chempert/"
LINCS_DATASET = "LINCS L1000 CMAP Chemical Perturbation Consensus Signatures"
LINCS_DESCRIPTOR = SourceDescriptor(
    key="harmonizome_lincs_consensus",
    name=LINCS_DATASET,
    homepage="https://maayanlab.cloud/Harmonizome/dataset/" + quote(LINCS_DATASET),
    license_url="https://maayanlab.cloud/Harmonizome/terms",
    license="CC BY-NC-SA 4.0",
    redistribution=RedistributionPolicy.RESTRICTED,
    source_type=SourceType.COMPUTED,
    notes="Local research import only; not SIGMA-KG harmonization or balance pruning.",
)
GTOPDB_DESCRIPTOR = SourceDescriptor(
    key="gtopdb_signed_function",
    name="GtoPdb signed human functional interactions",
    homepage="https://www.guidetopharmacology.org/download.jsp",
    license_url="https://www.guidetopharmacology.org/about.jsp#license",
    license="ODbL (database) / CC BY-SA 4.0 (content)",
    redistribution=RedistributionPolicy.OPEN,
    source_type=SourceType.CURATED_DATABASE,
)
# Ambiguous, partial, biased, allosteric and binding-only actions are excluded.
ACTION_PREDICATES = {
    "Activation": "activates",
    "Agonist": "activates",
    "Full agonist": "activates",
    "Inhibition": "inhibits",
    "Antagonist": "inhibits",
    "Inverse agonist": "inhibits",
    "Irreversible inhibition": "inhibits",
}
SMALL_MOLECULE_TYPES = {"Synthetic organic", "Metabolite", "Natural product", "Inorganic"}


def file_sha256(path: Path) -> str:
    """Fingerprint the original bytes, including compression.

    Args:
        path: Downloaded input file.

    Returns:
        SHA-256 hex digest.
    """
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def table_rows(path: Path, *, gtopdb: bool = False) -> Iterator[dict]:
    """Stream a source table with explicit header validation in the caller.

    Args:
        path: Plain or gzip-compressed table.
        gtopdb: Whether to skip the required GtoPdb release comment.

    Returns:
        Iterator of original rows.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        if gtopdb and "GtoPdb Version:" not in next(handle, ""):
            raise ValueError("Missing GtoPdb release header")
        yield from csv.DictReader(handle, delimiter="," if gtopdb else "\t")


def gtopdb_release(path: Path) -> str:
    """Read the release from the source, never a guessed current version.

    Args:
        path: Official GtoPdb CSV.

    Returns:
        Original version/date header.
    """
    with path.open(encoding="utf-8") as handle:
        line = handle.readline().strip().strip('"')
    if not line.startswith("# GtoPdb Version:"):
        raise ValueError("Missing GtoPdb release")
    return line.removeprefix("# ")


def lincs_compound_mapping(path: Path) -> tuple[dict[str, set[str]], list[EntityRecord]]:
    """Map exact LINCS keys using the official GSE92742 perturbagen metadata.

    Both pert_id and pert_iname are source-local keys, not OncoGraph names.
    Multiple CIDs remain ambiguous, including conflicts between those columns.

    Args:
        path: GSE92742_Broad_LINCS_pert_info.txt.gz.

    Returns:
        Token-to-CID sets and unique PubChem drug entities.
    """
    mapping = defaultdict(set)
    labels = {}
    for row in table_rows(path):
        if not {"pert_id", "pert_iname", "pert_type", "pubchem_cid"} <= row.keys():
            raise ValueError("Unrecognized LINCS perturbagen metadata schema")
        if row["pert_type"] != "trt_cp":
            continue
        cid = row["pubchem_cid"].strip()
        if not cid.isdigit() or int(cid) <= 0:
            continue
        cid = str(int(cid))
        for key in (row["pert_id"], row["pert_iname"]):
            if key and key != "-666":
                mapping[key].add(cid)
        labels.setdefault(cid, row["pert_iname"])
    digest = file_sha256(path)
    records = [
        EntityRecord(
            entity_type="drug",
            name=name,
            identifiers=(ExternalIdentifier("pubchem", cid),),
            metadata={
                "source": "GSE92742",
                "mapping_file_sha256": digest,
                "mapping_release": "GSE92742 perturbagen metadata snapshot",
            },
        )
        for cid, name in sorted(labels.items())
    ]
    return dict(mapping), records


class LincsConsensusAdapter:
    """Stream Harmonizome's original edge export with a transparent optional scope."""

    descriptor = LINCS_DESCRIPTOR

    def __init__(
        self,
        path: Path,
        mapping: dict[str, set[str]],
        *,
        release: str,
        mapping_sha256: str,
        gene_ids: set[str] | None = None,
    ):
        """Configure a local source import.

        Args:
            path: Original gene_attribute_edges.txt.gz download.
            mapping: Exact source-local LINCS keys to PubChem CID candidates.
            release: Snapshot label; an unknown upstream release must say so.
            mapping_sha256: Fingerprint of the metadata supplying the crosswalk.
            gene_ids: Optional explicit NCBI gene scope; None means all genes.
        """
        self.path, self.mapping, self.release = path, mapping, release
        self.mapping_sha256, self.gene_ids = mapping_sha256, gene_ids
        self.report = SignedImportReport()
        self.mapping_diagnostics = {}

    def iter_edges(self) -> Iterator[EdgeRecord]:
        """Preserve source row IDs, z-scores and unavailable experimental context.

        Returns:
            Typed Drug -> Gene expression observations, not binding edges.
        """
        self.report.reset()
        self.mapping_diagnostics.clear()
        digest = file_sha256(self.path)
        required = {"", "Gene", "Gene ID", "Chemical Perturbation", "Z-score", "Threshold Value"}
        for row in table_rows(self.path):
            if not required <= row.keys():
                raise ValueError("Unrecognized Harmonizome LINCS edge schema")
            self.report.input_records += 1
            try:
                score = float(row["Z-score"])
                sign = int(row["Threshold Value"])
                gene = row["Gene ID"].strip()
                token = row["Chemical Perturbation"].strip()
                if (
                    not math.isfinite(score)
                    or sign not in {-1, 1}
                    or score * sign <= 0
                    or not gene.isdigit()
                    or int(gene) <= 0
                    or not token
                    or not row[""]
                ):
                    raise ValueError("Invalid signed record")
            except (ValueError, TypeError):
                self.report.skipped["invalid_source_row"] += 1
                continue
            self.report.parsed_records += 1
            if self.gene_ids is not None and gene not in self.gene_ids:
                self.report.skipped["outside_gene_scope"] += 1
                continue
            self.report.scoped_records += 1
            cids = self.mapping.get(token, set())
            status = "matched" if len(cids) == 1 else "ambiguous" if cids else "unmatched"
            self.mapping_diagnostics[token] = {"status": status, "candidates": sorted(cids)}
            if status != "matched":
                self.report.skipped[f"compound_{status}"] += 1
                continue
            predicate = "upregulates" if sign == 1 else "downregulates"
            yield EdgeRecord(
                subject=ExternalIdentifier("pubchem", next(iter(cids))),
                predicate=predicate,
                object=ExternalIdentifier("ncbigene", gene),
                source_record_id=row[""],
                source_url=LINCS_DESCRIPTOR.homepage,
                evidence_type="drug_induced_transcription",
                extraction_method="consensus_transform",
                context={
                    "original_source_dataset": LINCS_DATASET,
                    "release": self.release,
                    "file_sha256": digest,
                    "original_predicate": (
                        "positively regulated by" if sign == 1 else "negatively regulated by"
                    ),
                    "original_orientation": "gene -> chemical perturbation (regulated by)",
                    "effect_sign": sign,
                    "biological_relationship": "drug_induced_transcription",
                    "original_score": score,
                    "original_score_type": "gene-wise z-score",
                    "original_threshold_value": sign,
                    "source_chemical_key": token,
                    "source_gene_symbol": row["Gene"],
                    "mapping_source": "GSE92742",
                    "mapping_file_sha256": self.mapping_sha256,
                    "taxon_id": 9606,
                    "observation_status": "transformed",
                    "model_generated": False,
                    "direct_target_binding": False,
                    "causal_scope": "consensus_perturbation_response",
                    "experimental_context": None,
                    "context_availability": "not supplied in export",
                    "sigma_balance_pruned": False,
                    "local_only": True,
                },
            )


def gtopdb_drug_entities(path: Path) -> list[EntityRecord]:
    """Read explicit PubChem/ChEMBL/GtoPdb cross-references without name matching.

    Args:
        path: Official ligand_id_mapping.csv.

    Returns:
        Source identity records for small molecules; ambiguous IDs stay visible.
    """
    records = []
    release, digest = gtopdb_release(path), file_sha256(path)
    for row in table_rows(path, gtopdb=True):
        if row["Type"] not in SMALL_MOLECULE_TYPES:
            continue
        identifiers = [ExternalIdentifier("gtopdb", row["Ligand id"])]
        conflicts = {}
        for column, namespace in (
            ("PubChem CID", "pubchem"),
            ("ChEMBl ID", "chembl"),
            ("DrugBank ID", "drugbank"),
        ):
            value = row[column].strip()
            if value and ("|" in value or ";" in value):
                conflicts[column] = value
            elif value:
                identifiers.append(ExternalIdentifier(namespace, value))
        records.append(
            EntityRecord(
                entity_type="drug",
                name=re.sub("<[^>]+>", "", row["Name"]),
                identifiers=tuple(identifiers),
                metadata={
                    "source": "gtopdb",
                    "release": release,
                    "mapping_file_sha256": digest,
                    "identifier_mapping_conflicts": conflicts,
                },
            )
        )
    return records


class GtoPdbSignedAdapter:
    """Retain explicit human, single-protein functional modulation only."""

    descriptor = GTOPDB_DESCRIPTOR

    def __init__(self, path: Path):
        """Configure the local interaction export.

        Args:
            path: Official interactions.csv file.
        """
        self.path = path
        self.report = SignedImportReport()

    def protein_entities(self) -> list[EntityRecord]:
        """Register separate human proteins; gene IDs are metadata, not aliases.

        Returns:
            Unique human UniProt protein entities.
        """
        proteins = {}
        release = gtopdb_release(self.path)
        for row in table_rows(self.path, gtopdb=True):
            accession = row["Target UniProt ID"].strip()
            if row["Target Species"] == "Human" and re.fullmatch(r"[A-Z0-9]{6,10}", accession):
                proteins.setdefault(
                    accession,
                    EntityRecord(
                        entity_type="protein",
                        name=row["Target"],
                        identifiers=(ExternalIdentifier("uniprot", accession),),
                        metadata={
                            "taxon_id": 9606,
                            "source": "gtopdb",
                            "encoded_by_ensembl": row["Target Ensembl Gene ID"],
                            "release": release,
                        },
                    ),
                )
        return list(proteins.values())

    def iter_edges(self) -> Iterator[EdgeRecord]:
        """Keep source assays and references without inventing biological context.

        Returns:
            Signed Drug -> Protein functional observations.
        """
        self.report.reset()
        digest, release = file_sha256(self.path), gtopdb_release(self.path)
        for row in table_rows(self.path, gtopdb=True):
            self.report.input_records += 1
            if not {"Target Species", "Action", "Ligand ID", "Target UniProt ID"} <= row.keys():
                raise ValueError("Unrecognized GtoPdb interaction schema")
            self.report.parsed_records += 1
            reason = None
            if row["Target Species"] != "Human":
                reason = "non_human_or_unspecified_species"
            elif row["Ligand Type"] not in SMALL_MOLECULE_TYPES:
                reason = "not_small_molecule"
            elif row["Action"] not in ACTION_PREDICATES:
                reason = "unsupported_or_unsigned_action"
            elif row["Target Subunit IDs"] or not re.fullmatch(
                r"[A-Z0-9]{6,10}", row["Target UniProt ID"]
            ):
                reason = "complex_or_missing_protein"
            if reason:
                self.report.skipped[reason] += 1
                continue
            self.report.scoped_records += 1
            predicate = ACTION_PREDICATES[row["Action"]]
            # No native interaction ID is shipped: content hash is an explicit
            # surrogate, identical duplicate rows cannot inflate evidence counts.
            source_id = stable_digest(row)
            yield EdgeRecord(
                subject=ExternalIdentifier("gtopdb", row["Ligand ID"]),
                predicate=predicate,
                object=ExternalIdentifier("uniprot", row["Target UniProt ID"]),
                source_record_id=source_id,
                evidence_type="protein_functional_modulation",
                source_url=(
                    "https://www.guidetopharmacology.org/GRAC/LigandDisplayForward"
                    f"?ligandId={row['Ligand ID']}"
                ),
                extraction_method="curated_functional_action_transform",
                context={
                    "original_source_dataset": "IUPHAR/BPS Guide to PHARMACOLOGY interactions",
                    "release": release,
                    "file_sha256": digest,
                    "original_predicate": row["Action"],
                    "original_type": row["Type"],
                    "effect_sign": SIGNED_RELATIONS[predicate][2],
                    "biological_relationship": "protein_functional_modulation",
                    "observation_status": "transformed",
                    "model_generated": False,
                    "taxon_id": 9606,
                    "source_record_id_kind": "sha256_of_original_row",
                    "source_native_record_id": None,
                    "original_row": row,
                    "experimental_context": {
                        key: row[key]
                        for key in ("Assay Description", "Ligand Context", "Action comment")
                        if row[key]
                    },
                    "causal_scope": "source_curated_functional_modulation",
                    "sigma_balance_pruned": False,
                    "local_only": True,
                },
            )
