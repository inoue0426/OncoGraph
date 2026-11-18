"""Audit a local LINCS graph with disk-backed SQL aggregation and frozen inputs."""

import argparse
import json
import math
import sqlite3
import time
from collections import Counter
from pathlib import Path

from oncograph.sources.sigma_sources import LINCS_DESCRIPTOR, file_sha256, table_rows


def audit_database(database: Path, geneinfo: Path | None = None) -> dict:
    """Count source-backed relations without loading the full graph into memory.

    Args:
        database: Local import database, opened read-only.
        geneinfo: Optional official LINCS2020 gene feature-space metadata.

    Returns:
        Counts, biological checks and explicitly scoped platform annotations.
    """
    started = time.monotonic()
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("PRAGMA cache_size=-32768")
        connection.execute(
            "CREATE TEMP TABLE scoped_relations AS "
            "SELECT r.* FROM relation r WHERE r.id IN "
            "(SELECT e.relation_id FROM evidence e WHERE e.source=?)",
            (LINCS_DESCRIPTOR.key,),
        )
        result = dict(
            zip(
                ("signed_relations", "unique_compound_entities", "unique_gene_entities"),
                connection.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT subject_id), "
                    "COUNT(DISTINCT object_id) FROM scoped_relations"
                ).fetchone(),
            )
        )
        result["relations_by_sign"] = dict(
            connection.execute(
                "SELECT predicate, COUNT(*) FROM scoped_relations GROUP BY predicate"
            )
        )
        result["evidence_records"] = connection.execute(
            "SELECT COUNT(*) FROM evidence WHERE source=?", (LINCS_DESCRIPTOR.key,)
        ).fetchone()[0]
        result["opposite_sign_pairs"] = connection.execute(
            "SELECT COUNT(*) FROM (SELECT subject_id,object_id FROM scoped_relations "
            "GROUP BY subject_id,object_id HAVING COUNT(DISTINCT predicate)=2)"
        ).fetchone()[0]
        result["endpoint_type_violations"] = connection.execute(
            "SELECT COUNT(*) FROM scoped_relations r JOIN entity s ON s.id=r.subject_id "
            "JOIN entity o ON o.id=r.object_id WHERE s.type!='DRUG' OR o.type!='GENE' "
            "OR r.predicate NOT IN ('upregulates','downregulates')"
        ).fetchone()[0]
        result["compound_entities_by_namespace"] = dict(
            connection.execute(
                "SELECT substr(e.canonical_id,1,instr(e.canonical_id,':')-1), COUNT(*) "
                "FROM entity e WHERE e.id IN (SELECT subject_id FROM scoped_relations) GROUP BY 1"
            )
        )
        gene_rows = connection.execute(
            "SELECT e.canonical_id,e.entity_metadata FROM entity e "
            "WHERE e.id IN (SELECT object_id FROM scoped_relations)"
        ).fetchall()
        result["gene_taxon_violations"] = sum(
            json.loads(metadata or "{}").get("taxon_id") != 9606 for _, metadata in gene_rows
        )
        if geneinfo:
            feature_spaces = {}
            for row in table_rows(geneinfo):
                key, space = row["gene_id"], row["feature_space"]
                if key in feature_spaces and feature_spaces[key] != space:
                    raise ValueError(f"Conflicting gene feature-space annotation: {key}")
                feature_spaces[key] = space
            gene_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT value FROM entityidentifier WHERE namespace='ncbigene' "
                    "AND entity_id IN (SELECT object_id FROM scoped_relations)"
                )
            ]
            result["gene_feature_space"] = {
                "counts_by_ncbi_id": dict(
                    Counter(feature_spaces.get(key, "unknown") for key in gene_ids)
                ),
                "metadata_sha256": file_sha256(geneinfo),
                "scope": "LINCS2020 platform annotation; not per-observation measurement validation",
            }
        # A malformed import must not be hidden behind aggregate coverage counts.
        result["foreign_key_violations"] = len(
            connection.execute("PRAGMA foreign_key_check").fetchall()
        )
    result["audit_seconds"] = time.monotonic() - started
    return result


def audit_source(path: Path) -> dict:
    """Audit original rows, including duplicates excluded from neither scope.

    Args:
        path: Frozen original Harmonizome edge export, plain or gzip.

    Returns:
        Original-row and observation-identity counts using disk-backed grouping.
    """
    counters = Counter()
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("PRAGMA cache_size=-32768")
        connection.execute(
            "CREATE TEMP TABLE observations (record_id TEXT, compound TEXT, "
            "gene TEXT, sign INTEGER, score REAL)"
        )
        batch = []
        for row in table_rows(path):
            counters["original_records"] += 1
            try:
                score, sign = float(row["Z-score"]), int(row["Threshold Value"])
                gene, compound, record_id = (
                    row["Gene ID"].strip(),
                    row["Chemical Perturbation"].strip(),
                    row[""],
                )
                if (
                    not math.isfinite(score)
                    or sign not in {-1, 1}
                    or score * sign <= 0
                    or not gene.isdigit()
                    or int(gene) <= 0
                    or not compound
                    or not record_id
                ):
                    raise ValueError("Invalid observation")
            except (ValueError, TypeError):
                counters["invalid_records"] += 1
                continue
            batch.append((record_id, compound, gene, sign, score))
            counters["valid_records"] += 1
            if len(batch) == 1000:
                connection.executemany("INSERT INTO observations VALUES (?,?,?,?,?)", batch)
                batch.clear()
        connection.executemany("INSERT INTO observations VALUES (?,?,?,?,?)", batch)
        result = {
            key: counters[key] for key in ("original_records", "valid_records", "invalid_records")
        }
        result.update(
            zip(
                ("unique_source_compounds", "unique_source_genes", "unique_record_ids"),
                connection.execute(
                    "SELECT COUNT(DISTINCT compound),COUNT(DISTINCT gene),"
                    "COUNT(DISTINCT record_id) FROM observations"
                ).fetchone(),
            )
        )
        result["repeated_record_ids"] = counters["valid_records"] - result["unique_record_ids"]
        unique_observations = connection.execute(
            "SELECT COUNT(*) FROM (SELECT compound,gene,sign,score FROM observations "
            "GROUP BY compound,gene,sign,score)"
        ).fetchone()[0]
        result["duplicate_observations_ignoring_row_id"] = (
            counters["valid_records"] - unique_observations
        )
        result["opposite_sign_native_compound_gene_pairs"] = connection.execute(
            "SELECT COUNT(*) FROM (SELECT compound,gene FROM observations GROUP BY compound,gene "
            "HAVING COUNT(DISTINCT sign)=2)"
        ).fetchone()[0]
        result["source_records_by_sign"] = dict(
            connection.execute("SELECT sign,COUNT(*) FROM observations GROUP BY sign")
        )
    result["file_sha256"] = file_sha256(path)
    return result


def main() -> None:
    """Write an aggregate audit outside the checkout without publishing data.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--geneinfo", type=Path)
    parser.add_argument("--edges", type=Path, help="Also audit all original rows and duplicates")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.report.resolve().is_relative_to(repo):
        parser.error("Write local audit reports outside the checkout")
    result = audit_database(args.database, args.geneinfo)
    if args.edges:
        result["original_source_audit"] = audit_source(args.edges)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
