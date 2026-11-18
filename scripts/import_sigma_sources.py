"""Fetch and import available SIGMA-KG source observations into local SQLite.

The full pruned SIGMA-KG is not distributed by the official repository. This
command does not publish data or modify the Pages refresh. See docs/SIGMA_KG.md.
"""

import argparse
import json
import resource
import sys
import time
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from sqlmodel import Session, SQLModel, create_engine

from oncograph.signed_molecular import TypedCrosswalk, import_signed_observations
from oncograph.sources.hetionet_expression import HETIONET_URL, HetionetExpressionAdapter
from oncograph.sources.hgnc import HGNCAdapter
from oncograph.sources.lincs_identity import COMPOUNDINFO_URL, compound_resolutions
from oncograph.sources.sigma_sources import (
    LINCS_URL,
    GtoPdbSignedAdapter,
    LincsConsensusAdapter,
    file_sha256,
    gtopdb_drug_entities,
    lincs_compound_mapping,
)

INPUTS = {
    "hetionet-v1.0.json.bz2": HETIONET_URL,
    "lincs_edges.tsv.gz": LINCS_URL + "gene_attribute_edges.txt.gz",
    "lincs_pert_info.txt.gz": (
        "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE92nnn/GSE92742/suppl/"
        "GSE92742_Broad_LINCS_pert_info.txt.gz"
    ),
    "hgnc.tsv": "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt",
    "gtopdb_interactions.csv": "https://www.guidetopharmacology.org/DATA/interactions.csv",
    "ligand_id_mapping.csv": "https://www.guidetopharmacology.org/DATA/ligand_id_mapping.csv",
}


def download_inputs(root: Path) -> dict:
    """Download official source files atomically and record byte-level provenance.

    Args:
        root: Local directory outside the Git checkout.

    Returns:
        Manifest with timestamps, URLs and checksums.
    """
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"retrieved_at": datetime.now(UTC).isoformat(), "files": {}}
    for name, url in INPUTS.items():
        destination = root / name
        temporary = root / (name + ".partial")
        request = Request(url, headers={"User-Agent": "OncoGraph research importer"})
        with urlopen(request, timeout=180) as response, temporary.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
        if temporary.stat().st_size == 0:
            raise ValueError(f"Empty download: {url}")
        temporary.replace(destination)
        manifest["files"][name] = {"url": url, "sha256": file_sha256(destination)}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def run_import(
    root: Path,
    database: Path,
    gene_ids: set[str] | None,
    sources: list[str],
    snapshot: str,
    lincs_compoundinfo: Path | None = None,
) -> dict:
    """Import original sources, retaining exact statistics and crosswalk diagnostics.

    Args:
        root: Local raw input directory.
        database: Local SQLite destination, never a published artifact.
        gene_ids: Optional NCBI gene scope for LINCS; all when None.
        sources: Source adapters to execute.
        snapshot: Explicit downloaded-snapshot label, not an upstream version claim.
        lincs_compoundinfo: Optional frozen official LINCS2020 chemical metadata.

    Returns:
        JSON-compatible audit report for this execution.
    """
    started = time.monotonic()
    result = {
        "snapshot": snapshot,
        "sigma_kg_imported": False,
        "local_only": True,
        "lincs_gene_scope": sorted(gene_ids) if gene_ids else "all",
        "inputs": {},
        "identity_registration": {},
        "sources": {},
    }
    for name, url in INPUTS.items():
        path = root / name
        if path.exists():
            result["inputs"][name] = {"url": url, "sha256": file_sha256(path)}
    engine = create_engine(f"sqlite:///{database}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        crosswalk = TypedCrosswalk(session)
        # Keep existing HGNC parsing, but never put UniProt protein accessions
        # on a gene identity. Product mappings remain available in metadata.
        genes = []
        for record in HGNCAdapter(root / "hgnc.tsv", release=snapshot).iter_entities():
            if record.metadata.get("status") != "Approved":
                continue
            genes.append(
                replace(
                    record,
                    identifiers=tuple(i for i in record.identifiers if i.namespace != "uniprot"),
                    metadata={
                        **record.metadata,
                        "source": "hgnc",
                        "taxon_id": 9606,
                        "protein_products": [
                            i.value for i in record.identifiers if i.namespace == "uniprot"
                        ],
                    },
                )
            )
        result["identity_registration"]["hgnc"] = crosswalk.register(genes)
        adapters = []
        if "lincs" in sources:
            resolutions = None
            mapping, compounds = lincs_compound_mapping(root / "lincs_pert_info.txt.gz")
            if lincs_compoundinfo is not None:
                resolutions, compounds, mapping_audit = compound_resolutions(
                    lincs_compoundinfo, root / "lincs_pert_info.txt.gz"
                )
                result["inputs"]["compoundinfo_beta.txt"] = {
                    "sha256": file_sha256(lincs_compoundinfo),
                    "url": COMPOUNDINFO_URL,
                    "release": "LINCS2020 beta; frozen snapshot, upstream date unavailable",
                }
            result["identity_registration"][
                "lincs_compounds" if resolutions is not None else "lincs_pubchem"
            ] = crosswalk.register(compounds)
            adapters.append(
                LincsConsensusAdapter(
                    root / "lincs_edges.tsv.gz",
                    mapping,
                    release=snapshot,
                    mapping_sha256=file_sha256(root / "lincs_pert_info.txt.gz"),
                    gene_ids=gene_ids,
                    compound_resolutions=resolutions,
                )
            )
        if "gtopdb" in sources:
            result["identity_registration"]["gtopdb_drugs"] = crosswalk.register(
                gtopdb_drug_entities(root / "ligand_id_mapping.csv")
            )
            adapter = GtoPdbSignedAdapter(root / "gtopdb_interactions.csv")
            result["identity_registration"]["gtopdb_proteins"] = crosswalk.register(
                adapter.protein_entities()
            )
            adapters.append(adapter)
        if "hetionet" in sources:
            adapter = HetionetExpressionAdapter(root / "hetionet-v1.0.json.bz2")
            result["identity_registration"]["hetionet_diseases"] = crosswalk.register(
                adapter.disease_entities()
            )
            adapters.append(adapter)
        result["identity_registration_issues"] = crosswalk.registration_issues
        for adapter in adapters:
            report = import_signed_observations(
                session, adapter.iter_edges(), adapter.descriptor, crosswalk, adapter.report
            )
            data = asdict(report)
            # dataclasses.asdict reconstructs Counter from (key, value) pairs.
            data["skipped"] = dict(report.skipped)
            data["identifier_coverage"] = dict(
                Counter(item["status"] for item in report.identifiers.values())
            )
            if isinstance(adapter, LincsConsensusAdapter):
                data["compound_mapping"] = adapter.mapping_diagnostics
                data["compound_mapping_coverage"] = dict(
                    Counter(item["status"] for item in adapter.mapping_diagnostics.values())
                )
                data["unique_source_compounds_scoped"] = len(adapter.compound_counts)
                data["unique_original_genes"] = len(adapter.gene_counts)
                if resolutions is not None:
                    strategies = Counter()
                    strategy_records = Counter()
                    globally_resolved = set()
                    for token, count in adapter.compound_counts.items():
                        resolution = resolutions.get(token)
                        strategy = (
                            resolution.provenance["strategy"] if resolution else "missing_metadata"
                        )
                        strategies[strategy] += 1
                        strategy_records[strategy] += count
                        if resolution and resolution.identifier.namespace == "pubchem":
                            globally_resolved.add(resolution.identifier.value)
                    legacy = mapping_audit["legacy_mapping"]
                    data["mapping_strategy_compounds"] = dict(strategies)
                    data["mapping_strategy_records"] = dict(strategy_records)
                    data["unique_resolved_pubchem_cids"] = len(globally_resolved)
                    data["new_chembl_identities"] = 0
                    data["legacy_unique_cid_compound_keys"] = sum(
                        len(legacy.get(key, [])) == 1 for key in adapter.compound_counts
                    )
                    data["legacy_mapped_records"] = sum(
                        count
                        for key, count in adapter.compound_counts.items()
                        if len(legacy.get(key, [])) == 1
                    )
                    data["metadata_conflicting_compound_keys"] = sum(
                        item.get("metadata_conflict", False)
                        for item in adapter.mapping_diagnostics.values()
                    )
            data["license"] = adapter.descriptor.license
            data["license_url"] = adapter.descriptor.license_url
            result["sources"][adapter.descriptor.key] = data
    engine.dispose()
    result["processing_seconds"] = time.monotonic() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result["peak_process_rss_bytes"] = rss if sys.platform == "darwin" else rss * 1024
    return result


def main() -> None:
    """Parse local import arguments and write a complete audit report.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--lincs-compoundinfo", type=Path, help="Opt in to LINCS2020 native identity preservation"
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=["lincs", "gtopdb", "hetionet"],
        default=["lincs", "gtopdb", "hetionet"],
    )
    parser.add_argument("--gene-ids", help="Comma-separated NCBI IDs; omit for all LINCS genes")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    paths = [args.raw_dir, args.database, args.report]
    if args.lincs_compoundinfo is not None:
        paths.append(args.lincs_compoundinfo)
    for path in paths:
        if path.resolve().is_relative_to(repo):
            parser.error("Raw files, database and reports must be outside the checkout")
    if args.download:
        download_inputs(args.raw_dir)
    result = run_import(
        args.raw_dir,
        args.database,
        set(args.gene_ids.split(",")) if args.gene_ids else None,
        args.sources,
        args.snapshot,
        args.lincs_compoundinfo,
    )
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                key: {
                    k: v for k, v in value.items() if k not in {"identifiers", "compound_mapping"}
                }
                for key, value in result["sources"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
