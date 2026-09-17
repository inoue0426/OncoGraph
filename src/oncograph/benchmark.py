"""Benchmark schema, metrics, and retrieval-baseline scaffolding (Issue #9).

**No experiment has been run and no score in this module is a real result.**
Everything here is infrastructure: a versioned item schema, real (not
stubbed) metric functions that score a structured prediction against a gold
answer, and a common interface so retrieval strategies can be compared later.
Building/running an actual LLM-only or vector-RAG baseline, or publishing a
benchmark score, is explicitly out of scope -- see docs/BENCHMARKING.md.
"""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .query import (
    GraphRetriever,
    RetrievalResult,
    Retriever,
)


class BenchmarkTaskType(StrEnum):
    SINGLE_HOP_FACTUAL_RETRIEVAL = "single_hop_factual_retrieval"
    MULTI_HOP_REASONING = "multi_hop_reasoning"
    DRUG_TARGET_DISEASE_REASONING = "drug_target_disease_reasoning"
    PATHWAY_REASONING = "pathway_reasoning"
    TRIAL_LOOKUP = "trial_lookup"
    PUBLICATION_EVIDENCE_ATTRIBUTION = "publication_evidence_attribution"
    CONTRADICTION_DETECTION = "contradiction_detection"
    CONTEXT_SPECIFIC_DRUG_RESPONSE = "context_specific_drug_response"
    PROVENANCE_AWARE_REASONING = "provenance_aware_reasoning"


@dataclass(frozen=True)
class GoldEvidenceRef:
    """One expected supporting relation, identified structurally.

    By canonical IDs and predicate -- never a database row UUID, which isn't
    stable across re-imports (this repo's DB is regenerated from scratch on
    every refresh, see docs/HOSTING.md) and so cannot appear in a versioned,
    reproducible benchmark file.
    """

    subject_canonical_id: str
    predicate: str
    object_canonical_id: str
    source: str | None = None

    def key(self) -> tuple[str, str, str]:
        return (self.subject_canonical_id, self.predicate, self.object_canonical_id)


@dataclass(frozen=True)
class BenchmarkItem:
    id: str
    version: str
    task_type: BenchmarkTaskType
    question: str
    gold_answer_canonical_ids: tuple[str, ...] = ()
    gold_evidence_path: tuple[GoldEvidenceRef, ...] = ()
    context: dict = field(default_factory=dict)


def _item_from_dict(row: dict) -> BenchmarkItem:
    return BenchmarkItem(
        id=row["id"],
        version=row["version"],
        task_type=BenchmarkTaskType(row["task_type"]),
        question=row["question"],
        gold_answer_canonical_ids=tuple(row.get("gold_answer_canonical_ids", ())),
        gold_evidence_path=tuple(
            GoldEvidenceRef(**ref) for ref in row.get("gold_evidence_path", ())
        ),
        context=row.get("context", {}),
    )


def load_benchmark_items(path: str | Path) -> list[BenchmarkItem]:
    """Load a versioned, machine-readable benchmark file (a JSON list of items)."""
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_item_from_dict(row) for row in records]


@dataclass(frozen=True)
class Prediction:
    """What a retrieval strategy produced for one BenchmarkItem -- structured,
    not prose, so it can be scored without an LLM-as-judge."""

    answer_canonical_ids: tuple[str, ...] = ()
    evidence_refs: tuple[GoldEvidenceRef, ...] = ()
    claims: tuple[str, ...] = ()
    contradictions_flagged: bool = False


def graph_retrieval_to_prediction(result: RetrievalResult) -> Prediction:
    """Convert a GraphRetriever RetrievalResult into a scoreable Prediction."""
    if result.root is None:
        return Prediction()
    canonical_by_id = {e["id"]: e["canonical_id"] for e in result.entities if e.get("canonical_id")}
    root_canonical = result.root.get("canonical_id")
    answer_ids = tuple(
        sorted({cid for eid, cid in canonical_by_id.items() if cid and cid != root_canonical})
    )
    evidence_refs: list[GoldEvidenceRef] = []
    contradictions_flagged = False
    for relation in result.relations:
        subject_cid = canonical_by_id.get(relation["subject_id"])
        object_cid = canonical_by_id.get(relation["object_id"])
        if not subject_cid or not object_cid:
            continue
        if relation.get("has_contradictory_evidence"):
            contradictions_flagged = True
        for evidence in relation["evidence"]:
            evidence_refs.append(
                GoldEvidenceRef(subject_cid, relation["predicate"], object_cid, evidence.get("source"))
            )
    return Prediction(
        answer_canonical_ids=answer_ids,
        evidence_refs=tuple(evidence_refs),
        contradictions_flagged=contradictions_flagged,
    )


# --- Metrics -------------------------------------------------------------------
#
# Every function here is a real, deterministic computation over structured
# data -- not a placeholder returning a fixed number. Several are
# deliberately coarse proxies (documented inline) appropriate for structured
# predictions; scoring free-text LLM output would need a different,
# judge-based approach not implemented here.


def answer_correctness(prediction: Prediction, item: BenchmarkItem) -> float:
    """Fraction of gold answer IDs present in the prediction (recall)."""
    gold = set(item.gold_answer_canonical_ids)
    predicted = set(prediction.answer_canonical_ids)
    if not gold:
        return 1.0 if not predicted else 0.0
    return len(gold & predicted) / len(gold)


def citation_correctness(prediction: Prediction, item: BenchmarkItem) -> float:
    """Fraction of the prediction's cited evidence that matches a gold reference (precision)."""
    gold_keys = {ref.key() for ref in item.gold_evidence_path}
    predicted_keys = {ref.key() for ref in prediction.evidence_refs}
    if not predicted_keys:
        return 0.0
    return len(gold_keys & predicted_keys) / len(predicted_keys)


def evidence_completeness(prediction: Prediction, item: BenchmarkItem) -> float:
    """Fraction of the gold evidence path actually covered by the prediction (recall)."""
    gold_keys = {ref.key() for ref in item.gold_evidence_path}
    if not gold_keys:
        return 1.0
    predicted_keys = {ref.key() for ref in prediction.evidence_refs}
    return len(gold_keys & predicted_keys) / len(gold_keys)


def path_correctness(prediction: Prediction, item: BenchmarkItem) -> float:
    """1.0 if the prediction's evidence set is exactly the gold evidence set, else 0.0.

    Set-based, not sequence-based: multi-hop traversal can legitimately visit
    the gold hops in a different discovery order.
    """
    gold_keys = {ref.key() for ref in item.gold_evidence_path}
    if not gold_keys:
        return 1.0
    predicted_keys = {ref.key() for ref in prediction.evidence_refs}
    return 1.0 if predicted_keys == gold_keys else 0.0


def unsupported_claim_rate(prediction: Prediction) -> float:
    """Coarse proxy: fraction of free-text claims made with zero cited evidence.

    Real claim-level attribution (which evidence backs *which* claim) needs a
    claim/evidence link this schema doesn't have yet; this only detects the
    all-or-nothing case (some claims stated, no evidence at all).
    """
    if not prediction.claims:
        return 0.0
    return 1.0 if not prediction.evidence_refs else 0.0


def contradiction_awareness(item: BenchmarkItem, prediction: Prediction) -> float:
    """1.0 if the item expects known contradicting evidence and the prediction flags it."""
    expected = bool(item.context.get("has_known_contradiction"))
    if not expected:
        return 1.0
    return 1.0 if prediction.contradictions_flagged else 0.0


def provenance_coverage(prediction: Prediction) -> float:
    """1.0 if an answer was given and at least one piece of evidence was cited for it."""
    if not prediction.answer_canonical_ids:
        return 0.0
    return 1.0 if prediction.evidence_refs else 0.0


@dataclass(frozen=True)
class BenchmarkScore:
    item_id: str
    answer_correctness: float
    citation_correctness: float
    evidence_completeness: float
    path_correctness: float
    unsupported_claim_rate: float
    contradiction_awareness: float
    provenance_coverage: float


def score_prediction(item: BenchmarkItem, prediction: Prediction) -> BenchmarkScore:
    """Score one prediction against one item's gold answer -- the whole scoring API."""
    return BenchmarkScore(
        item_id=item.id,
        answer_correctness=answer_correctness(prediction, item),
        citation_correctness=citation_correctness(prediction, item),
        evidence_completeness=evidence_completeness(prediction, item),
        path_correctness=path_correctness(prediction, item),
        unsupported_claim_rate=unsupported_claim_rate(prediction),
        contradiction_awareness=contradiction_awareness(item, prediction),
        provenance_coverage=provenance_coverage(prediction),
    )


# --- Retrieval-baseline scaffolding ---------------------------------------------
#
# GraphRetriever (oncograph.query) is the only implemented Retriever. The
# following share its Protocol so a benchmark harness can swap them in later
# without redesigning anything here -- but building them (an LLM call, a
# vector index, an evidence-blind graph walk) is explicitly out of scope for
# this issue.


class LLMOnlyRetriever(Retriever):
    """Scaffold only. Would answer from model knowledge alone, no graph/document
    context -- and so structurally has nothing to put in Prediction.evidence_refs."""

    def retrieve(self, query):
        raise NotImplementedError(
            "LLMOnlyRetriever is a scaffold for future baseline comparison; "
            "this repository does not call an LLM."
        )


class VectorRAGRetriever(Retriever):
    """Scaffold only. Would embed a text corpus (e.g. publication titles/abstracts)
    and retrieve top-k by similarity, independent of the graph structure."""

    def retrieve(self, query):
        raise NotImplementedError("VectorRAGRetriever is a scaffold; not implemented.")


class VanillaGraphRetriever(Retriever):
    """Scaffold only. Would traverse the graph like GraphRetriever but without
    evidence-aware filtering, to isolate what evidence-awareness contributes."""

    def retrieve(self, query):
        raise NotImplementedError("VanillaGraphRetriever is a scaffold; not implemented.")


__all__ = [
    "BenchmarkItem",
    "BenchmarkScore",
    "BenchmarkTaskType",
    "GoldEvidenceRef",
    "GraphRetriever",
    "LLMOnlyRetriever",
    "Prediction",
    "Retriever",
    "VanillaGraphRetriever",
    "VectorRAGRetriever",
    "answer_correctness",
    "citation_correctness",
    "contradiction_awareness",
    "evidence_completeness",
    "graph_retrieval_to_prediction",
    "load_benchmark_items",
    "path_correctness",
    "provenance_coverage",
    "score_prediction",
    "unsupported_claim_rate",
]
