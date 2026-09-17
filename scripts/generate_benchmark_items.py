"""Generate real, deterministic benchmark items from a frozen graph snapshot.

Unlike `data/benchmarks/v1/oncology_core.json` (9 hand-written items, mostly
`verified_live_data` but written by inspecting the live index by hand), this
script *programmatically* samples real relations directly out of a deployed
`search-index.json`/`relations.json` pair with a fixed random seed, so the
result is reproducible and not hand-picked to flatter any retriever.

Every item is grounded in a real subject/predicate/object triple that
exists in the snapshot -- nothing here is synthetic. Task types with no
real backing data in the current snapshot (no Publication entities, no
recorded contradictions, no drug-response observations) are simply not
generated; see the module docstring in oncograph.benchmark and
docs/BENCHMARKING.md for how those are covered by illustrative_synthetic
items in v1 instead.

Usage:
    python scripts/generate_benchmark_items.py \
        --snapshot-dir path/to/dir/with/search-index.json+relations.json \
        --graph-version 2026-09-17T20:34:16Z \
        --seed 20260917 \
        --out-dev data/benchmarks/v2/generated_dev.json \
        --out-heldout data/benchmarks/v2/generated_heldout.json

The dev/held-out split is fixed by the seed: dev is meant only for building
and sanity-checking a retriever/generator, and should not be re-scored to
pick a headline number -- final metrics are computed once on held-out.
"""

import argparse
import json
import random
from pathlib import Path

DEV_ITEMS_PER_TASK = 3


def _load_snapshot(snapshot_dir: Path) -> tuple[dict, list[dict]]:
    entities = json.loads((snapshot_dir / "search-index.json").read_text(encoding="utf-8"))
    relations = json.loads((snapshot_dir / "relations.json").read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in entities}
    return by_id, relations


def _primary_source(evidence: list[dict]) -> str | None:
    return evidence[0]["source"] if evidence else None


def _relations_by_predicate(relations: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for relation in relations:
        grouped.setdefault(relation["predicate"], []).append(relation)
    return grouped


def generate_single_hop_items(
    rng: random.Random,
    by_id: dict,
    by_predicate: dict[str, list[dict]],
    predicate: str,
    count: int,
    question_fmt: str,
    task_type: str = "single_hop_factual_retrieval",
) -> list[dict]:
    candidates = [
        r
        for r in by_predicate.get(predicate, [])
        if by_id.get(r["subject_id"], {}).get("canonical_id") and by_id.get(r["object_id"], {}).get("canonical_id")
    ]
    sample = rng.sample(candidates, k=min(count, len(candidates)))
    items = []
    for relation in sample:
        subject = by_id[relation["subject_id"]]
        obj = by_id[relation["object_id"]]
        items.append(
            {
                "task_type": task_type,
                "question": question_fmt.format(subject=subject["name"], object=obj["name"]),
                "gold_answer_canonical_ids": [obj["canonical_id"]],
                "gold_evidence_path": [
                    {
                        "subject_canonical_id": subject["canonical_id"],
                        "predicate": predicate,
                        "object_canonical_id": obj["canonical_id"],
                        "source": _primary_source(relation["evidence"]),
                    }
                ],
                "context": {"grounding": "verified_live_data", "generated_by": "generate_benchmark_items.py"},
            }
        )
    return items


def generate_drug_disease_reasoning_items(
    rng: random.Random, by_id: dict, by_predicate: dict[str, list[dict]], count: int
) -> list[dict]:
    """Two real, independently-sourced facts about the same drug -- its
    target and its approved indication -- combined into one reasoning item,
    matching data/benchmarks/v1/oncology_core.json's v1-002/v1-004 style."""
    targets_by_drug: dict[str, dict] = {}
    for relation in by_predicate.get("targets", []):
        subject = by_id.get(relation["subject_id"])
        obj = by_id.get(relation["object_id"])
        if subject and obj and subject.get("canonical_id") and obj.get("canonical_id"):
            targets_by_drug[relation["subject_id"]] = relation

    candidates = [
        relation
        for relation in by_predicate.get("indicated_for", [])
        if relation["subject_id"] in targets_by_drug
        and by_id.get(relation["object_id"], {}).get("canonical_id")
    ]
    sample = rng.sample(candidates, k=min(count, len(candidates)))
    items = []
    for indicated_relation in sample:
        drug = by_id[indicated_relation["subject_id"]]
        disease = by_id[indicated_relation["object_id"]]
        target_relation = targets_by_drug[indicated_relation["subject_id"]]
        gene = by_id[target_relation["object_id"]]
        items.append(
            {
                "task_type": "drug_target_disease_reasoning",
                "question": f"What disease is {drug['name']} approved for, and via which target?",
                "gold_answer_canonical_ids": [gene["canonical_id"], disease["canonical_id"]],
                "gold_evidence_path": [
                    {
                        "subject_canonical_id": drug["canonical_id"],
                        "predicate": "targets",
                        "object_canonical_id": gene["canonical_id"],
                        "source": _primary_source(target_relation["evidence"]),
                    },
                    {
                        "subject_canonical_id": drug["canonical_id"],
                        "predicate": "indicated_for",
                        "object_canonical_id": disease["canonical_id"],
                        "source": _primary_source(indicated_relation["evidence"]),
                    },
                ],
                "context": {"grounding": "verified_live_data", "generated_by": "generate_benchmark_items.py"},
            }
        )
    return items


def generate_go_chain_items(rng: random.Random, by_id: dict, by_predicate: dict[str, list[dict]], count: int) -> list[dict]:
    """A real 2-hop is_a chain between GO terms (child -> parent -> grandparent) --
    the only genuinely chainable multi-hop structure in the deployed snapshot."""
    is_a = by_predicate.get("is_a", [])
    parent_of: dict[str, list[dict]] = {}
    for relation in is_a:
        if by_id.get(relation["subject_id"], {}).get("canonical_id") and by_id.get(relation["object_id"], {}).get(
            "canonical_id"
        ):
            parent_of.setdefault(relation["subject_id"], []).append(relation)

    candidates = []
    for child_rels in parent_of.values():
        for child_to_parent in child_rels:
            parent_id = child_to_parent["object_id"]
            for parent_to_grandparent in parent_of.get(parent_id, []):
                candidates.append((child_to_parent, parent_to_grandparent))

    sample = rng.sample(candidates, k=min(count, len(candidates)))
    items = []
    for child_to_parent, parent_to_grandparent in sample:
        child = by_id[child_to_parent["subject_id"]]
        parent = by_id[child_to_parent["object_id"]]
        grandparent = by_id[parent_to_grandparent["object_id"]]
        items.append(
            {
                "task_type": "multi_hop_reasoning",
                "question": f"Through which successive parent GO terms does '{child['name']}' chain (is_a x2)?",
                "gold_answer_canonical_ids": [parent["canonical_id"], grandparent["canonical_id"]],
                "gold_evidence_path": [
                    {
                        "subject_canonical_id": child["canonical_id"],
                        "predicate": "is_a",
                        "object_canonical_id": parent["canonical_id"],
                        "source": _primary_source(child_to_parent["evidence"]),
                    },
                    {
                        "subject_canonical_id": parent["canonical_id"],
                        "predicate": "is_a",
                        "object_canonical_id": grandparent["canonical_id"],
                        "source": _primary_source(parent_to_grandparent["evidence"]),
                    },
                ],
                "context": {"grounding": "verified_live_data", "generated_by": "generate_benchmark_items.py"},
            }
        )
    return items


def generate_all(by_id: dict, relations: list[dict], seed: int, per_task: int) -> list[dict]:
    rng = random.Random(seed)
    by_predicate = _relations_by_predicate(relations)

    generated: list[dict] = []
    generated += generate_single_hop_items(
        rng, by_id, by_predicate, "targets", per_task, "What gene does {subject} target?"
    )
    generated += generate_single_hop_items(
        rng,
        by_id,
        by_predicate,
        "studied_in",
        per_task,
        "Which registered trial evaluates {subject}?",
        task_type="trial_lookup",
    )
    generated += generate_single_hop_items(
        rng,
        by_id,
        by_predicate,
        "part_of",
        per_task,
        "What GO term is '{subject}' part of?",
        task_type="pathway_reasoning",
    )
    generated += generate_drug_disease_reasoning_items(rng, by_id, by_predicate, per_task)
    generated += generate_go_chain_items(rng, by_id, by_predicate, per_task)

    # provenance_aware_reasoning reuses the "targets" fact structure but is
    # graded on provenance_coverage, not just answer_correctness -- sample a
    # disjoint set from the single-hop "targets" pool.
    already_used_subjects = {
        item["gold_evidence_path"][0]["subject_canonical_id"]
        for item in generated
        if item["task_type"] == "single_hop_factual_retrieval"
    }
    provenance_candidates = [
        r
        for r in by_predicate.get("targets", [])
        if by_id.get(r["subject_id"], {}).get("canonical_id") not in already_used_subjects
        and by_id.get(r["subject_id"], {}).get("canonical_id")
        and by_id.get(r["object_id"], {}).get("canonical_id")
    ]
    sample = rng.sample(provenance_candidates, k=min(per_task, len(provenance_candidates)))
    for relation in sample:
        subject = by_id[relation["subject_id"]]
        obj = by_id[relation["object_id"]]
        generated.append(
            {
                "task_type": "provenance_aware_reasoning",
                "question": f"What gene does {subject['name']} target, and what is the source of that claim?",
                "gold_answer_canonical_ids": [obj["canonical_id"]],
                "gold_evidence_path": [
                    {
                        "subject_canonical_id": subject["canonical_id"],
                        "predicate": "targets",
                        "object_canonical_id": obj["canonical_id"],
                        "source": _primary_source(relation["evidence"]),
                    }
                ],
                "context": {"grounding": "verified_live_data", "generated_by": "generate_benchmark_items.py"},
            }
        )

    return generated


def assign_ids_and_version(items: list[dict], version: str) -> list[dict]:
    for index, item in enumerate(items):
        item["id"] = f"{version}-{index:04d}"
        item["version"] = version
    return items


def split_dev_heldout(rng: random.Random, items: list[dict], dev_per_task: int) -> tuple[list[dict], list[dict]]:
    by_task: dict[str, list[dict]] = {}
    for item in items:
        by_task.setdefault(item["task_type"], []).append(item)

    dev: list[dict] = []
    heldout: list[dict] = []
    for task_items in by_task.values():
        shuffled = task_items[:]
        rng.shuffle(shuffled)
        dev += shuffled[:dev_per_task]
        heldout += shuffled[dev_per_task:]
    return dev, heldout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--graph-version", type=str, required=True)
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument("--per-task", type=int, default=15)
    parser.add_argument("--dev-per-task", type=int, default=DEV_ITEMS_PER_TASK)
    parser.add_argument("--version", type=str, default="v2")
    parser.add_argument("--out-dev", type=Path, required=True)
    parser.add_argument("--out-heldout", type=Path, required=True)
    args = parser.parse_args()

    by_id, relations = _load_snapshot(args.snapshot_dir)
    generated = generate_all(by_id, relations, args.seed, args.per_task)
    for item in generated:
        item["context"]["source_snapshot_graph_version"] = args.graph_version
        item["context"]["generator_seed"] = args.seed

    split_rng = random.Random(args.seed)
    dev, heldout = split_dev_heldout(split_rng, generated, args.dev_per_task)
    assign_ids_and_version(dev, args.version + "-dev")
    assign_ids_and_version(heldout, args.version + "-heldout")

    args.out_dev.parent.mkdir(parents=True, exist_ok=True)
    args.out_dev.write_text(json.dumps(dev, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_heldout.parent.mkdir(parents=True, exist_ok=True)
    args.out_heldout.write_text(json.dumps(heldout, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    by_task_counts = {}
    for item in generated:
        by_task_counts[item["task_type"]] = by_task_counts.get(item["task_type"], 0) + 1
    print(f"Generated {len(generated)} items: {by_task_counts}")
    print(f"dev={len(dev)} heldout={len(heldout)}")


if __name__ == "__main__":
    main()
