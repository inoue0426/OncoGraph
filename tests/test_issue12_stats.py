"""Issue #12: Homepage Knowledge Graph Statistics.

Covers scripts/build_static_site.py's stats generation: canonical entity
counts by type, relation/evidence/source counts kept distinct from entity
counts, explicit curated-path counting (never "all possible traversals"),
and the stats.json artifact produced by the same build entrypoint used for
search-index.json/relations.json.
"""

import json
import sys
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from oncograph.models import Entity, Evidence, Relation

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_static_site

# --- compute_entity_counts: canonical counts, no alias/source duplicates -------


def test_entity_counts_group_by_type_and_report_total():
    entities = [
        {"type": "DRUG", "name": "a"},
        {"type": "DRUG", "name": "b"},
        {"type": "GENE", "name": "c"},
    ]
    counts = build_static_site.compute_entity_counts(entities)
    assert counts == {"drug": 2, "gene": 1, "total": 3}


def test_entity_counts_do_not_double_count_aliases_or_source_duplicates():
    """A Gene's aliases live in metadata, never as separate Entity rows --
    so a gene with many aliases still counts as exactly one entity, and two
    source adapters resolving to the same canonical entity (already
    deduplicated by import_entities before export) never appear twice here.
    """
    entities = [
        {
            "type": "GENE",
            "name": "EGFR",
            "canonical_id": "hgnc:HGNC:3236",
            "metadata": {"aliases": ["ERBB1", "HER1", "ERBB", "PIG61"]},
        },
    ]
    counts = build_static_site.compute_entity_counts(entities)
    assert counts == {"gene": 1, "total": 1}


def test_entity_counts_empty_list():
    assert build_static_site.compute_entity_counts([]) == {"total": 0}


# --- compute_relation_stats: relations / evidence_records / sources ------------


def test_relation_stats_counts_relations_and_evidence_separately():
    relations = [
        {"evidence": [{"source": "gtopdb"}, {"source": "europe_pmc"}]},
        {"evidence": [{"source": "gtopdb"}]},
        {"evidence": []},  # a relation can legitimately carry zero evidence rows
    ]
    stats = build_static_site.compute_relation_stats(relations)
    assert stats == {"relations": 3, "evidence_records": 3, "sources": 2}


def test_relation_stats_source_count_is_distinct_not_raw_row_count():
    relations = [
        {"evidence": [{"source": "gtopdb"}, {"source": "gtopdb"}, {"source": "gtopdb"}]},
    ]
    stats = build_static_site.compute_relation_stats(relations)
    assert stats["evidence_records"] == 3
    assert stats["sources"] == 1


def test_relation_stats_ignores_evidence_with_no_source():
    relations = [{"evidence": [{"source": None}]}]
    stats = build_static_site.compute_relation_stats(relations)
    assert stats == {"relations": 1, "evidence_records": 1, "sources": 0}


# --- read_benchmark_gold_paths: explicit curated paths, never traversal count --


def _write_benchmark_file(root: Path, name: str, items: list[dict]) -> None:
    (root / "v1").mkdir(parents=True, exist_ok=True)
    (root / "v1" / name).write_text(json.dumps(items), encoding="utf-8")


def test_benchmark_gold_paths_counts_items_with_a_nonempty_path(tmp_path):
    _write_benchmark_file(
        tmp_path,
        "core.json",
        [
            {"id": "v1-001", "version": "v1", "gold_evidence_path": [{"subject_canonical_id": "a"}]},
            {"id": "v1-002", "version": "v1", "gold_evidence_path": []},
            {"id": "v1-003", "version": "v1"},  # field absent entirely
        ],
    )
    paths = build_static_site.read_benchmark_gold_paths(tmp_path)
    assert paths == {"benchmark_gold": 1, "total": 1}


def test_benchmark_gold_paths_dedup_by_version_and_id(tmp_path):
    item = {"id": "v1-001", "version": "v1", "gold_evidence_path": [{"subject_canonical_id": "a"}]}
    _write_benchmark_file(tmp_path, "core.json", [item])
    _write_benchmark_file(tmp_path, "core_copy.json", [item])  # same curated item, duplicated file
    paths = build_static_site.read_benchmark_gold_paths(tmp_path)
    assert paths == {"benchmark_gold": 1, "total": 1}


def test_benchmark_gold_paths_returns_none_when_no_benchmark_dir(tmp_path):
    assert build_static_site.read_benchmark_gold_paths(tmp_path / "does_not_exist") is None


def test_benchmark_gold_paths_returns_none_when_no_item_has_a_path(tmp_path):
    _write_benchmark_file(tmp_path, "core.json", [{"id": "v1-001", "version": "v1", "gold_evidence_path": []}])
    assert build_static_site.read_benchmark_gold_paths(tmp_path) is None


def test_real_oncology_core_benchmark_file_has_exactly_seven_gold_paths():
    """Guards against silently fabricating/inflating this count: the real,
    checked-in benchmark file (Issue #9) has 9 items, 7 with a non-empty
    gold_evidence_path (2 are illustrative_synthetic with no path)."""
    real_benchmarks_root = Path(__file__).resolve().parent.parent / "data" / "benchmarks"
    paths = build_static_site.read_benchmark_gold_paths(real_benchmarks_root)
    assert paths == {"benchmark_gold": 7, "total": 7}


# --- compute_stats: full payload, omission of unavailable categories -----------


def test_compute_stats_omits_paths_when_no_benchmark_dir(tmp_path):
    entities = [{"type": "DRUG", "name": "a"}]
    relations = [{"evidence": [{"source": "gtopdb"}]}]
    stats = build_static_site.compute_stats(entities, relations, benchmarks_root=tmp_path / "missing")
    assert "paths" not in stats
    assert stats["entities"] == {"drug": 1, "total": 1}
    assert stats["relations"] == 1
    assert stats["evidence_records"] == 1
    assert stats["sources"] == 1
    assert "generated_at" in stats


def test_compute_stats_includes_paths_when_benchmark_dir_has_items(tmp_path):
    _write_benchmark_file(
        tmp_path,
        "core.json",
        [{"id": "v1-001", "version": "v1", "gold_evidence_path": [{"subject_canonical_id": "a"}]}],
    )
    stats = build_static_site.compute_stats([], [], benchmarks_root=tmp_path)
    assert stats["paths"] == {"benchmark_gold": 1, "total": 1}


def test_compute_stats_never_fabricates_a_zero_valued_publication_category():
    """No PAPER entity present -> no "publication" key at all, not "publication": 0."""
    entities = [{"type": "DRUG", "name": "a"}, {"type": "GENE", "name": "b"}]
    stats = build_static_site.compute_stats(entities, [])
    assert "paper" not in stats["entities"]


def test_graph_version_picks_the_latest_release_seen_in_evidence_context():
    relations = [
        {"evidence": [{"source": "gtopdb", "context": {"release": "2026-01-01T00:00:00Z"}}]},
        {"evidence": [{"source": "gene_ontology", "context": {"release": "2026-09-17T20:34:16Z"}}]},
        {"evidence": [{"source": "clinicaltrials_gov", "context": None}]},
    ]
    stats = build_static_site.compute_stats([], relations)
    assert stats["graph_version"] == "2026-09-17T20:34:16Z"


def test_graph_version_absent_when_no_evidence_carries_a_release():
    stats = build_static_site.compute_stats([], [{"evidence": [{"source": "x", "context": None}]}])
    assert "graph_version" not in stats


# --- main(): the actual deployed build entrypoint, end to end ------------------


def _seeded_db_with_relations_and_paths(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        drug = Entity(type="drug", name="gefitinib", canonical_id="gtopdb:4941")
        gene = Entity(type="gene", name="EGFR", canonical_id="hgnc:HGNC:3236")
        disease = Entity(type="disease", name="NSCLC", canonical_id="mondo:0005233")
        session.add_all([drug, gene, disease])
        session.flush()

        targets = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
        indicated = Relation(subject_id=drug.id, predicate="indicated_for", object_id=disease.id)
        session.add_all([targets, indicated])
        session.flush()

        session.add(Evidence(relation_id=targets.id, source="gtopdb"))
        session.add(Evidence(relation_id=indicated.id, source="open_targets_indications"))
        session.add(Evidence(relation_id=indicated.id, source="europe_pmc"))  # 2nd evidence, same relation
        session.commit()


def test_main_writes_a_stats_json_consistent_with_the_exported_entities_and_relations(tmp_path, monkeypatch):
    db_path = tmp_path / "oncograph.db"
    _seeded_db_with_relations_and_paths(db_path)

    benchmarks_root = tmp_path / "benchmarks"
    _write_benchmark_file(
        benchmarks_root,
        "core.json",
        [{"id": "v1-001", "version": "v1", "gold_evidence_path": [{"subject_canonical_id": "gtopdb:4941"}]}],
    )

    entities_out = tmp_path / "search-index.json"
    relations_out = tmp_path / "relations.json"
    stats_out = tmp_path / "stats.json"
    monkeypatch.setattr(build_static_site, "DB_PATH", db_path)
    monkeypatch.setattr(build_static_site, "ENTITIES_OUTPUT_PATH", entities_out)
    monkeypatch.setattr(build_static_site, "RELATIONS_OUTPUT_PATH", relations_out)
    monkeypatch.setattr(build_static_site, "STATS_OUTPUT_PATH", stats_out)
    monkeypatch.setattr(build_static_site, "BENCHMARKS_ROOT", benchmarks_root)

    build_static_site.main()

    stats = json.loads(stats_out.read_text(encoding="utf-8"))
    entities = json.loads(entities_out.read_text(encoding="utf-8"))
    relations = json.loads(relations_out.read_text(encoding="utf-8"))

    assert stats["entities"] == {"drug": 1, "gene": 1, "disease": 1, "total": 3}
    assert stats["entities"]["total"] == len(entities)
    assert stats["relations"] == len(relations) == 2
    assert stats["evidence_records"] == 3  # indicated_for carries two evidence rows
    assert stats["sources"] == 3  # gtopdb, open_targets_indications, europe_pmc
    assert stats["paths"] == {"benchmark_gold": 1, "total": 1}
