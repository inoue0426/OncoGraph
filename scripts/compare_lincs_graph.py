"""Compare a local LINCS import to a frozen public graph without publishing it."""

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from oncograph.sources.sigma_sources import file_sha256, gtopdb_drug_entities


def compare_graph(
    database: Path, entities_path: Path, relations_path: Path, ligand_mapping: Path
) -> dict:
    """Compare exact IDs and authoritative cross-references, never display names.

    Args:
        database: Local LINCS database, opened read-only.
        entities_path: Frozen public search-index.json.
        relations_path: Frozen public relations.json.
        ligand_mapping: Official GtoPdb cross-references used only for comparison.

    Returns:
        Coverage and target overlaps; unresolved snapshot IDs remain explicit.
    """
    entities = {row["id"]: row for row in json.loads(entities_path.read_text())}
    relations = json.loads(relations_path.read_text())
    crossrefs = defaultdict(set)
    for record in gtopdb_drug_entities(ligand_mapping):
        if record.metadata.get("identifier_mapping_conflicts"):
            continue
        cids = {i.value for i in record.identifiers if i.namespace == "pubchem"}
        for identifier in record.identifiers:
            crossrefs[f"{identifier.namespace}:{identifier.value}"].update(cids)
    result = {
        "comparison_scope": "Frozen published snapshot; not all current upstream data",
        "inputs_sha256": {
            path.name: file_sha256(path) for path in (entities_path, relations_path, ligand_mapping)
        },
        "public_entities": len(entities),
        "public_relations": len(relations),
        "public_signed_drug_gene_relations": sum(
            r["predicate"] in {"upregulates", "downregulates"} for r in relations
        ),
        "public_pathway_entities": sum(e["type"] == "PATHWAY" for e in entities.values()),
    }
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
        local = defaultdict(set)
        entity_types = {}
        for identity, canonical, entity_type in connection.execute(
            "SELECT id,canonical_id,type FROM entity"
        ):
            local[canonical].add(identity)
            entity_types[identity] = entity_type
        for identity, namespace, value in connection.execute(
            "SELECT entity_id,namespace,value FROM entityidentifier"
        ):
            local[f"{namespace}:{value}"].add(identity)
        matched, statuses = {}, Counter()
        for key, entity in entities.items():
            canonical = entity["canonical_id"]
            candidates = set(local.get(canonical, set()))
            if entity["type"] == "DRUG" and not candidates:
                cids = crossrefs.get(canonical, set())
                if len(cids) > 1:
                    statuses["ambiguous_drug_cross_reference"] += 1
                    continue
                for cid in cids:
                    candidates.update(local.get(f"pubchem:{cid}", set()))
            if any(entity_types[item] != entity["type"] for item in candidates):
                statuses[f"conflicting_{entity['type'].lower()}"] += 1
                continue
            if len(candidates) == 1:
                matched[key] = next(iter(candidates))
                statuses[f"matched_{entity['type'].lower()}"] += 1
            elif len(candidates) > 1:
                statuses[f"ambiguous_{entity['type'].lower()}"] += 1
            else:
                statuses[f"unmatched_{entity['type'].lower()}"] += 1
        result["entity_matching"] = dict(statuses)
        affected = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT object_id FROM relation WHERE predicate IN ('upregulates','downregulates')"
            )
        }
        result["affected_genes_present_in_public_snapshot"] = len(
            {matched[key] for key, e in entities.items() if e["type"] == "GENE" and key in matched}
            & affected
        )
        counters = Counter()
        overlap_pairs = set()
        for relation in relations:
            if relation["predicate"] != "targets" or not relation.get("evidence"):
                continue
            subject, target = relation["subject_id"], relation["object_id"]
            if entities[subject]["type"] != "DRUG" or entities[target]["type"] != "GENE":
                continue
            counters["public_drug_gene_target_relations"] += 1
            if subject not in matched or target not in matched:
                counters["target_relations_with_unresolved_endpoint"] += 1
                continue
            counters["target_relations_with_resolved_endpoints"] += 1
            pair = (matched[subject], matched[target])
            signs = [
                row[0]
                for row in connection.execute(
                    "SELECT predicate FROM relation WHERE subject_id=? AND object_id=? "
                    "AND predicate IN ('upregulates','downregulates')",
                    pair,
                )
            ]
            if signs:
                counters["public_target_relations_with_transcriptional_observations"] += 1
                overlap_pairs.add(pair)
                counters.update(f"overlap_{sign}" for sign in signs)
        result["target_overlap"] = {
            **dict(counters),
            "unique_local_drug_gene_pairs": len(overlap_pairs),
        }
        result["protein_targets"] = (
            "Not equated to genes; require a separate encoding relation or reviewed HGNC product crosswalk"
        )
    return result


def main() -> None:
    """Write a local comparison report from explicitly frozen inputs.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--entities", type=Path, required=True)
    parser.add_argument("--relations", type=Path, required=True)
    parser.add_argument("--ligand-mapping", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("Write local reports outside the checkout")
    result = compare_graph(args.database, args.entities, args.relations, args.ligand_mapping)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
