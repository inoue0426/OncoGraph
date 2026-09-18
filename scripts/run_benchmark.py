"""Run GraphRetriever / VanillaGraphRetriever against a benchmark file.

Rebuilds a throwaway SQLite database from a frozen `search-index.json` +
`relations.json` pair (the same public export the deployed site serves --
the original CI-only SQLite database is never persisted, by design, see
docs/HOSTING.md), then runs every requested Retriever over every item in
the given benchmark file(s), scoring each with `oncograph.benchmark`.

Writes one JSON results log per invocation with full experiment metadata
(snapshot identity, seed, retriever, per-item scores, aggregates) so a run
can be inspected or diffed later -- never just a printed headline number.

Usage:
    python scripts/run_benchmark.py \
        --snapshot-dir path/to/dir/with/search-index.json+relations.json \
        --benchmark data/benchmarks/v2/generated_heldout.json \
        --retriever graph_retriever --retriever vanilla_graph_retriever \
        --out data/benchmarks/v2/results_heldout.json
"""

import argparse
import json
import statistics
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlmodel import Session, SQLModel, create_engine

from oncograph.benchmark import (
    VanillaGraphRetriever,
    graph_retrieval_to_prediction,
    load_benchmark_items,
    score_prediction,
)
from oncograph.models import ClaimState, Entity, Evidence, Relation, VerificationStatus
from oncograph.query import GraphRetriever, RetrievalQuery
from oncograph.rank import DEFAULT_RELATIVE_THRESHOLD, QueryConditionedRetriever

RETRIEVERS = {
    "graph_retriever": GraphRetriever,
    "vanilla_graph_retriever": VanillaGraphRetriever,
    "query_conditioned": QueryConditionedRetriever,
}


def _load_snapshot_into_db(snapshot_dir: Path, db_path: Path) -> None:
    entities = json.loads((snapshot_dir / "search-index.json").read_text(encoding="utf-8"))
    relations = json.loads((snapshot_dir / "relations.json").read_text(encoding="utf-8"))

    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for row in entities:
            session.add(
                Entity(
                    id=UUID(row["id"]),
                    type=row["type"].lower(),
                    name=row["name"],
                    canonical_id=row.get("canonical_id"),
                    description=row.get("description"),
                    entity_metadata=json.dumps(row["metadata"]) if row.get("metadata") else None,
                )
            )
        session.commit()

        for relation in relations:
            rel = Relation(
                subject_id=UUID(relation["subject_id"]),
                predicate=relation["predicate"],
                object_id=UUID(relation["object_id"]),
            )
            session.add(rel)
            session.flush()
            for evidence in relation["evidence"]:
                session.add(
                    Evidence(
                        relation_id=rel.id,
                        source=evidence["source"],
                        source_id=evidence.get("source_id"),
                        source_url=evidence.get("source_url"),
                        source_type=evidence.get("source_type"),
                        evidence_type=evidence.get("evidence_type"),
                        confidence=evidence.get("confidence"),
                        license=evidence.get("license"),
                        publication_id=UUID(evidence["publication_id"]) if evidence.get("publication_id") else None,
                        context=json.dumps(evidence["context"]) if evidence.get("context") else None,
                        claim_state=ClaimState(evidence["claim_state"].lower())
                        if evidence.get("claim_state")
                        else ClaimState.SUPPORTS,
                        verification_status=VerificationStatus(evidence["verification_status"].lower())
                        if evidence.get("verification_status")
                        else VerificationStatus.UNVERIFIED,
                    )
                )
        session.commit()


def _required_hops(item) -> int:
    """The minimum BFS depth that could possibly reach every gold hop from the
    item's root, following subject->object edges breadth-first.

    Several task types (e.g. drug_target_disease_reasoning) list two
    independent 1-hop facts about the same root as a "star", not a 2-hop
    chain -- using len(gold_evidence_path) as max_hops there would explore
    needlessly far and hurt citation_correctness for reasons that have
    nothing to do with retrieval quality. Only a genuine chain (each hop's
    object feeding the next hop's subject, e.g. the GO is_a chain items)
    needs hops > 1.
    """
    if not item.gold_evidence_path:
        return 1
    root = item.gold_evidence_path[0].subject_canonical_id
    reachable = {root}
    remaining = list(item.gold_evidence_path)
    depth = 0
    while remaining:
        newly_reachable = {ref.object_canonical_id for ref in remaining if ref.subject_canonical_id in reachable}
        remaining = [ref for ref in remaining if ref.subject_canonical_id not in reachable]
        if not newly_reachable:
            break  # a hop we can never satisfy from root; don't loop forever
        reachable |= newly_reachable
        depth += 1
    return max(depth, 1)


def _make_retriever(session: Session, retriever_name: str, relevance_threshold: float):
    retriever_cls = RETRIEVERS[retriever_name]
    if retriever_cls is QueryConditionedRetriever:
        return retriever_cls(session, relative_threshold=relevance_threshold)
    return retriever_cls(session)


def _run_one(session: Session, retriever_name: str, item, max_hops: int | None, relevance_threshold: float) -> dict:
    retriever = _make_retriever(session, retriever_name, relevance_threshold)
    root_ref = item.gold_evidence_path[0].subject_canonical_id if item.gold_evidence_path else None
    hops = max_hops if max_hops is not None else _required_hops(item)
    if root_ref is None:
        prediction_dict = {}
        score = None
    else:
        result = retriever.retrieve(RetrievalQuery(root_ref=root_ref, max_hops=hops, question_text=item.question))
        prediction = graph_retrieval_to_prediction(result)
        score = score_prediction(item, prediction)
        prediction_dict = asdict(prediction)
    return {
        "item_id": item.id,
        "root_ref": root_ref,
        "max_hops_used": hops,
        "prediction": prediction_dict,
        "score": asdict(score) if score else None,
    }


def _aggregate(per_item: list[dict]) -> dict:
    scored = [row["score"] for row in per_item if row["score"] is not None]
    if not scored:
        return {}
    metric_names = [k for k in scored[0] if k != "item_id"]
    return {metric: round(statistics.mean(s[metric] for s in scored), 4) for metric in metric_names}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, action="append", required=True)
    parser.add_argument("--retriever", action="append", required=True, choices=list(RETRIEVERS))
    parser.add_argument(
        "--max-hops",
        type=int,
        default=None,
        help="Fixed hop depth for every item. Default: auto-compute the minimum depth each "
        "item's own gold_evidence_path actually needs (see _required_hops).",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--db-path", type=Path, default=None, help="Reuse an already-built DB instead of rebuilding it")
    parser.add_argument(
        "--relevance-threshold",
        type=float,
        default=DEFAULT_RELATIVE_THRESHOLD,
        help="query_conditioned only: keep/drop cutoff as a fraction of the top-scoring entity "
        "for that query (oncograph.rank.QueryConditionedRetriever). Calibrate on dev only.",
    )
    args = parser.parse_args()

    db_path = args.db_path or (args.out.parent / "_run_benchmark_scratch.db")
    if not args.db_path:
        db_path.unlink(missing_ok=True)
        _load_snapshot_into_db(args.snapshot_dir, db_path)

    engine = create_engine(f"sqlite:///{db_path}")
    all_items = []
    for benchmark_path in args.benchmark:
        all_items += load_benchmark_items(benchmark_path)

    results = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "snapshot_dir": str(args.snapshot_dir),
        "benchmark_files": [str(p) for p in args.benchmark],
        "item_count": len(all_items),
        "max_hops": args.max_hops if args.max_hops is not None else "auto-per-item",
        "relevance_threshold": args.relevance_threshold,
        "by_retriever": {},
    }

    with Session(engine) as session:
        for retriever_name in args.retriever:
            per_item = [
                _run_one(session, retriever_name, item, args.max_hops, args.relevance_threshold) for item in all_items
            ]
            by_task_type: dict[str, list[dict]] = {}
            for item, row in zip(all_items, per_item, strict=True):
                by_task_type.setdefault(item.task_type.value, []).append(row)
            results["by_retriever"][retriever_name] = {
                "aggregate": _aggregate(per_item),
                "aggregate_by_task_type": {task: _aggregate(rows) for task, rows in by_task_type.items()},
                "per_item": per_item,
            }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    for retriever_name, payload in results["by_retriever"].items():
        print(f"{retriever_name}: {payload['aggregate']}")

    if not args.db_path:
        db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
