"""Tests for the benchmark-execution tooling (generate_benchmark_items.py,
run_benchmark.py) used to run OncoGraph's first real, non-fabricated
benchmark pass against a frozen graph snapshot.

These are unit tests over small synthetic snapshots -- the actual run
against the real deployed snapshot is a one-off script invocation,
recorded in data/benchmarks/v2/ and written up separately, not something
a fast test suite re-executes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_benchmark_items as gen
import run_benchmark

from oncograph.benchmark import BenchmarkItem, BenchmarkTaskType, GoldEvidenceRef

# --- generate_benchmark_items.py ------------------------------------------------


def _entity(entity_id: str, entity_type: str, name: str, canonical_id: str | None) -> dict:
    return {"id": entity_id, "type": entity_type, "name": name, "canonical_id": canonical_id}


def _relation(subject_id: str, predicate: str, object_id: str, source: str = "test_source") -> dict:
    return {"subject_id": subject_id, "predicate": predicate, "object_id": object_id, "evidence": [{"source": source}]}


def test_generate_single_hop_items_are_grounded_in_real_relations():
    by_id = {
        "d1": _entity("d1", "DRUG", "drugA", "gtopdb:1"),
        "g1": _entity("g1", "GENE", "geneA", "hgnc:HGNC:1"),
    }
    by_predicate = {"targets": [_relation("d1", "targets", "g1")]}
    rng = gen.random.Random(1)

    items = gen.generate_single_hop_items(rng, by_id, by_predicate, "targets", count=5, question_fmt="{subject}->{object}")

    assert len(items) == 1
    assert items[0]["gold_answer_canonical_ids"] == ["hgnc:HGNC:1"]
    assert items[0]["gold_evidence_path"] == [
        {"subject_canonical_id": "gtopdb:1", "predicate": "targets", "object_canonical_id": "hgnc:HGNC:1", "source": "test_source"}
    ]


def test_generate_single_hop_items_skips_entities_without_canonical_id():
    by_id = {
        "d1": _entity("d1", "DRUG", "drugA", None),  # unresolvable, no canonical_id
        "g1": _entity("g1", "GENE", "geneA", "hgnc:HGNC:1"),
    }
    by_predicate = {"targets": [_relation("d1", "targets", "g1")]}
    items = gen.generate_single_hop_items(gen.random.Random(1), by_id, by_predicate, "targets", 5, "{subject}")
    assert items == []


def test_generate_single_hop_items_respects_requested_count():
    by_id = {f"g{i}": _entity(f"g{i}", "GENE", f"gene{i}", f"hgnc:HGNC:{i}") for i in range(5)}
    by_id["d1"] = _entity("d1", "DRUG", "drugA", "gtopdb:1")
    by_predicate = {"targets": [_relation("d1", "targets", f"g{i}") for i in range(5)]}
    items = gen.generate_single_hop_items(gen.random.Random(1), by_id, by_predicate, "targets", 2, "{subject}")
    assert len(items) == 2


def test_generate_drug_disease_reasoning_combines_two_independent_real_facts():
    by_id = {
        "d1": _entity("d1", "DRUG", "drugA", "gtopdb:1"),
        "g1": _entity("g1", "GENE", "geneA", "hgnc:HGNC:1"),
        "dis1": _entity("dis1", "DISEASE", "diseaseA", "mondo:1"),
    }
    by_predicate = {
        "targets": [_relation("d1", "targets", "g1", source="gtopdb")],
        "indicated_for": [_relation("d1", "indicated_for", "dis1", source="open_targets_indications")],
    }
    items = gen.generate_drug_disease_reasoning_items(gen.random.Random(1), by_id, by_predicate, count=5)

    assert len(items) == 1
    item = items[0]
    assert item["task_type"] == "drug_target_disease_reasoning"
    assert set(item["gold_answer_canonical_ids"]) == {"hgnc:HGNC:1", "mondo:1"}
    sources = {ref["source"] for ref in item["gold_evidence_path"]}
    assert sources == {"gtopdb", "open_targets_indications"}


def test_generate_drug_disease_reasoning_requires_both_edges_on_the_same_drug():
    by_id = {
        "d1": _entity("d1", "DRUG", "drugA", "gtopdb:1"),
        "d2": _entity("d2", "DRUG", "drugB", "gtopdb:2"),
        "g1": _entity("g1", "GENE", "geneA", "hgnc:HGNC:1"),
        "dis1": _entity("dis1", "DISEASE", "diseaseA", "mondo:1"),
    }
    # drugA has a target but no indication; drugB has an indication but no target.
    by_predicate = {
        "targets": [_relation("d1", "targets", "g1")],
        "indicated_for": [_relation("d2", "indicated_for", "dis1")],
    }
    items = gen.generate_drug_disease_reasoning_items(gen.random.Random(1), by_id, by_predicate, count=5)
    assert items == []


def test_generate_go_chain_items_finds_a_real_two_hop_is_a_chain():
    by_id = {
        "child": _entity("child", "GO_TERM", "child term", "go:1"),
        "parent": _entity("parent", "GO_TERM", "parent term", "go:2"),
        "grandparent": _entity("grandparent", "GO_TERM", "grandparent term", "go:3"),
    }
    by_predicate = {
        "is_a": [
            _relation("child", "is_a", "parent"),
            _relation("parent", "is_a", "grandparent"),
        ]
    }
    items = gen.generate_go_chain_items(gen.random.Random(1), by_id, by_predicate, count=5)

    assert len(items) == 1
    item = items[0]
    assert item["task_type"] == "multi_hop_reasoning"
    assert item["gold_answer_canonical_ids"] == ["go:2", "go:3"]
    assert [ref["object_canonical_id"] for ref in item["gold_evidence_path"]] == ["go:2", "go:3"]


def test_generate_go_chain_items_requires_a_genuine_chain_not_two_unrelated_edges():
    by_id = {
        "a": _entity("a", "GO_TERM", "a", "go:1"),
        "b": _entity("b", "GO_TERM", "b", "go:2"),
        "c": _entity("c", "GO_TERM", "c", "go:3"),
        "d": _entity("d", "GO_TERM", "d", "go:4"),
    }
    # a->b and c->d: no shared node, not a chain.
    by_predicate = {"is_a": [_relation("a", "is_a", "b"), _relation("c", "is_a", "d")]}
    items = gen.generate_go_chain_items(gen.random.Random(1), by_id, by_predicate, count=5)
    assert items == []


def test_generate_combination_treatment_items_uses_real_component_and_trial_edges():
    by_id = {
        "combo1": _entity("combo1", "COMBINATION_TREATMENT", "durvalumab + olaparib", "ctgov_combo:1"),
        "d1": _entity("d1", "DRUG", "durvalumab", "gtopdb:9223"),
        "d2": _entity("d2", "DRUG", "olaparib", "gtopdb:7519"),
        "t1": _entity("t1", "TRIAL", "Ovarian cancer combo trial", "clinicaltrials.gov:NCT03737643"),
    }
    by_predicate = {
        "has_component": [
            _relation("combo1", "has_component", "d1", source="clinicaltrials_gov"),
            _relation("combo1", "has_component", "d2", source="clinicaltrials_gov"),
        ],
        "tested_in": [_relation("combo1", "tested_in", "t1", source="clinicaltrials_gov")],
    }
    items = gen.generate_combination_treatment_items(gen.random.Random(1), by_id, by_predicate, count=5)

    assert len(items) == 1
    item = items[0]
    assert item["task_type"] == "combination_treatment_reasoning"
    assert item["gold_answer_canonical_ids"] == ["gtopdb:7519", "gtopdb:9223"]
    predicates = {ref["predicate"] for ref in item["gold_evidence_path"]}
    assert predicates == {"has_component", "tested_in"}
    assert len(item["gold_evidence_path"]) == 3  # 2 components + 1 trial edge


def test_generate_combination_treatment_items_requires_2plus_components_and_a_trial():
    by_id = {
        "combo1": _entity("combo1", "COMBINATION_TREATMENT", "solo drug", "ctgov_combo:1"),
        "d1": _entity("d1", "DRUG", "drugA", "gtopdb:1"),
    }
    # Only one component -- not a real combination, must not be emitted.
    by_predicate = {"has_component": [_relation("combo1", "has_component", "d1")], "tested_in": []}
    items = gen.generate_combination_treatment_items(gen.random.Random(1), by_id, by_predicate, count=5)
    assert items == []


def test_split_dev_heldout_partitions_without_overlap():
    items = [{"task_type": "single_hop_factual_retrieval", "id": f"i{i}"} for i in range(10)]
    dev, heldout = gen.split_dev_heldout(gen.random.Random(1), items, dev_per_task=3)
    assert len(dev) == 3
    assert len(heldout) == 7
    assert {i["id"] for i in dev} & {i["id"] for i in heldout} == set()


def test_split_dev_heldout_splits_independently_per_task_type():
    items = [{"task_type": "a", "id": f"a{i}"} for i in range(5)] + [{"task_type": "b", "id": f"b{i}"} for i in range(5)]
    dev, _heldout = gen.split_dev_heldout(gen.random.Random(1), items, dev_per_task=2)
    dev_tasks = {i["task_type"] for i in dev}
    assert dev_tasks == {"a", "b"}
    assert sum(1 for i in dev if i["task_type"] == "a") == 2
    assert sum(1 for i in dev if i["task_type"] == "b") == 2


def test_assign_ids_and_version_is_stable_and_unique():
    items = [{"task_type": "x"} for _ in range(3)]
    gen.assign_ids_and_version(items, "v2-test")
    assert [i["id"] for i in items] == ["v2-test-0000", "v2-test-0001", "v2-test-0002"]
    assert all(i["version"] == "v2-test" for i in items)


# --- run_benchmark.py: per-item hop-depth auto-computation ---------------------


def _item(gold_evidence_path):
    return BenchmarkItem(
        id="t",
        version="v2",
        task_type=BenchmarkTaskType.SINGLE_HOP_FACTUAL_RETRIEVAL,
        question="q",
        gold_evidence_path=tuple(gold_evidence_path),
    )


def test_required_hops_is_one_for_a_star_shaped_gold_path():
    """Two independent 1-hop facts about the same root (drug_target_disease_reasoning's
    shape) should never be treated as requiring 2 traversal hops."""
    item = _item(
        [
            GoldEvidenceRef("gtopdb:1", "targets", "hgnc:HGNC:1", "gtopdb"),
            GoldEvidenceRef("gtopdb:1", "indicated_for", "mondo:1", "open_targets_indications"),
        ]
    )
    assert run_benchmark._required_hops(item) == 1


def test_required_hops_is_two_for_a_genuine_chain():
    item = _item(
        [
            GoldEvidenceRef("go:1", "is_a", "go:2", "gene_ontology"),
            GoldEvidenceRef("go:2", "is_a", "go:3", "gene_ontology"),
        ]
    )
    assert run_benchmark._required_hops(item) == 2


def test_required_hops_is_one_when_no_gold_path():
    assert run_benchmark._required_hops(_item([])) == 1


def test_required_hops_does_not_hang_on_an_unreachable_hop():
    # The second hop's subject is never reachable from the root -- must not loop forever.
    item = _item(
        [
            GoldEvidenceRef("go:1", "is_a", "go:2", "gene_ontology"),
            GoldEvidenceRef("go:99", "is_a", "go:100", "gene_ontology"),
        ]
    )
    assert run_benchmark._required_hops(item) == 1


def test_aggregate_computes_mean_per_metric_and_skips_missing_scores():
    per_item = [
        {"score": {"answer_correctness": 1.0, "citation_correctness": 0.5}},
        {"score": {"answer_correctness": 0.0, "citation_correctness": 0.5}},
        {"score": None},  # unscoreable item (no root_ref) -- excluded, not averaged as 0
    ]
    aggregate = run_benchmark._aggregate(per_item)
    assert aggregate == {"answer_correctness": 0.5, "citation_correctness": 0.5}


def test_aggregate_returns_empty_dict_when_nothing_was_scored():
    assert run_benchmark._aggregate([{"score": None}]) == {}
