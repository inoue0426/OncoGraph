"""Query-conditioned relation/path ranking for retrieval-quality improvement.

Addresses the residual failure mode measured in docs/BENCHMARK_RUN_v3.md:
principled path selection (Issue #9's ``graph_retrieval_to_prediction``) cites
every relation on *some* shortest path from the root, which is correct
recall-wise but still over-cites for a high-degree root, because many of its
real, distinct relations are each legitimately "the shortest path" to some
entity -- just not one relevant to the specific question being asked.

``QueryConditionedRetriever`` narrows this further: given the caller's
question text (``RetrievalQuery.question_text``), it scores each reached
entity's justifying path by simple, deterministic, explainable signals --
predicate/question lexical token overlap, evidence tier, hop distance, and
local node degree (a hub-bias penalty) -- and keeps only entities whose
score is competitive with the best-scoring entity for that same query. No
LLM, no embedding model, no synonym dictionary: this is literal token
overlap plus arithmetic, in the same "rule-based, not NLP" spirit as
``web/app.js``'s search-intent parsing. It never looks at a benchmark
item's gold answer or gold evidence path -- only the question text and the
graph itself -- so there is no label leakage into the ranking.

This is a real, honestly-scoped improvement, not a universal fix: when a
root's candidate relations share the same predicate (e.g. several
``studied_in`` trial edges with no other lexical signal to tell them
apart), token overlap cannot discriminate between them, and the ranker
degrades gracefully to keeping all of them -- the same as before. See
docs/BENCHMARK_RUN_v3_ranked.md for where this does and does not help,
measured honestly on the same v3 benchmark and frozen snapshot.
"""

from __future__ import annotations

import math
import re

from sqlmodel import Session

from .query import RetrievalQuery, RetrievalResult, TraversalFilters, resolve_entity, traverse

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# A small, standard set of generic English function words -- not tuned to
# any specific question or predicate. Without this, a predicate like
# "tested_in" spuriously outscores a more relevant one like "has_component"
# on questions containing an unrelated "...tested in..." simply because both
# "tested" and the near-universal preposition "in" happen to co-occur --
# discovered via dev-set debugging (docs/BENCHMARK_RUN_v3_ranked.md), fixed
# with standard stopword filtering rather than a rule about this one case.
# "a" and "is" are deliberately NOT included: this repository's own GO
# predicate "is_a" (docs/QUERY_API.md) tokenizes to exactly {"is", "a"}, and
# stopping both would make that real, meaningful predicate name unmatchable.
_STOPWORDS = {
    "an", "the", "are", "was", "were", "be", "been", "being",
    "in", "on", "of", "for", "to", "and", "or", "with", "by", "at", "as",
    "that", "this", "these", "those", "which", "what", "who", "whom",
    "does", "do", "did", "can", "could", "will", "would", "should",
    "its", "it", "into", "via", "from", "about",
}

# Coarser -> higher signal that a source represents a deliberate, curated
# claim rather than a computed/unclassified one. Mirrors web/app.js's
# TIER_ORDER intent, simplified to a numeric weight for ranking arithmetic.
_TIER_WEIGHTS = {
    "approved": 3.0,
    "curated_database": 2.0,
    "publication": 1.5,
    "registry": 1.0,
    "computed": 0.5,
    "unknown": 0.5,
}

DEFAULT_RELATIVE_THRESHOLD = 0.5


def _tokenize(text: str) -> set[str]:
    """Lowercase, alphanumeric tokens with minimal, generic stemming
    (trailing "es"/"s" stripped) and standard stopword removal -- not a
    synonym dictionary, not NLP."""
    tokens = set()
    for raw in _TOKEN_RE.findall(text.lower()):
        if raw in _STOPWORDS:
            continue
        stemmed = raw
        if stemmed.endswith("es") and len(stemmed) > 4:
            stemmed = stemmed[:-2]
        elif stemmed.endswith("s") and len(stemmed) > 3:
            stemmed = stemmed[:-1]
        if stemmed not in _STOPWORDS:
            tokens.add(stemmed)
        tokens.add(raw)  # keep the unstemmed form too, cheap and avoids false negatives
    return tokens


def _predicate_tokens(predicate: str) -> set[str]:
    return _tokenize(predicate.replace("_", " "))


def _tier_weight(relation: dict) -> float:
    evidence = relation.get("evidence") or [{}]
    source_type = (evidence[0].get("source_type") or "unknown").lower()
    return _TIER_WEIGHTS.get(source_type, 0.5)


def _local_degree(entity_id: str, relations: list[dict]) -> int:
    return sum(1 for r in relations if r["subject_id"] == entity_id or r["object_id"] == entity_id)


def score_entity(
    question_tokens: set[str],
    path_relation_ids: list[str],
    relations_by_id: dict[str, dict],
    degree_by_entity: dict[str, int],
) -> float:
    """Score one reached entity by its shortest-path relation chain.

    Higher is more relevant to the question. Zero when the question gives
    no lexical signal at all (the degenerate, honest fallback case) --
    callers should keep everything when every candidate scores 0.
    """
    if not path_relation_ids:
        return 0.0
    total = 0.0
    degree_penalties = []
    for relation_id in path_relation_ids:
        relation = relations_by_id.get(relation_id)
        if relation is None:
            continue
        overlap = len(question_tokens & _predicate_tokens(relation["predicate"]))
        total += overlap * 2.0 + _tier_weight(relation)
        other_degree = max(
            degree_by_entity.get(relation["subject_id"], 1),
            degree_by_entity.get(relation["object_id"], 1),
        )
        degree_penalties.append(math.log2(2 + other_degree))
    hop_distance = len(path_relation_ids)
    avg_degree_penalty = sum(degree_penalties) / len(degree_penalties) if degree_penalties else 1.0
    return total / hop_distance / avg_degree_penalty


class QueryConditionedRetriever:
    """Ranks each reached entity's justifying path by relevance to
    ``RetrievalQuery.question_text`` and keeps only the competitive ones,
    relative to the best-scoring entity for that query.

    ``relative_threshold`` (in [0, 1]) is a keep/drop cutoff as a fraction
    of the top score: entities scoring below ``relative_threshold *
    max_score`` are dropped from the returned RetrievalResult (and so never
    reach ``graph_retrieval_to_prediction``'s answer/evidence extraction).
    Chosen via dev-set-only calibration -- see
    docs/BENCHMARK_RUN_v3_ranked.md -- never adjusted after seeing held-out
    scores.
    """

    def __init__(self, session: Session, relative_threshold: float = DEFAULT_RELATIVE_THRESHOLD):
        self.session = session
        self.relative_threshold = relative_threshold

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        root = resolve_entity(self.session, query.root_ref, query.root_type)
        if root is None:
            return RetrievalResult(query=query, root=None)
        result = traverse(
            self.session,
            root.id,
            TraversalFilters(
                max_hops=query.max_hops,
                predicates=query.predicates,
                sources=query.sources,
                min_confidence=query.min_confidence,
                require_publication=query.require_publication,
            ),
        )
        if result is None:
            return RetrievalResult(query=query, root=None)

        relations_by_id = {relation["id"]: relation for relation in result["relations"]}
        degree_by_entity = {
            entity["id"]: _local_degree(entity["id"], result["relations"]) for entity in result["entities"]
        }
        question_tokens = _tokenize(query.question_text) if query.question_text else set()

        root_id = str(root.id)
        scores = {
            entity_id: score_entity(question_tokens, path_ids, relations_by_id, degree_by_entity)
            for entity_id, path_ids in result["paths"].items()
            if entity_id != root_id
        }
        max_score = max(scores.values(), default=0.0)
        # Degenerate case (no lexical signal distinguishes anything, or every
        # candidate is equally relevant): keep everyone rather than pick an
        # arbitrary subset -- the same, honest fallback as citing the whole
        # neighborhood when ranking has nothing to go on.
        if max_score <= 0.0:
            kept_ids = set(scores) | {root_id}
        else:
            cutoff = self.relative_threshold * max_score
            kept_ids = {entity_id for entity_id, score in scores.items() if score >= cutoff} | {root_id}

        kept_entities = [e for e in result["entities"] if e["id"] in kept_ids]
        kept_paths = {eid: rel_ids for eid, rel_ids in result["paths"].items() if eid in kept_ids}
        kept_relation_ids = {rid for rel_ids in kept_paths.values() for rid in rel_ids}
        kept_relations = [r for r in result["relations"] if r["id"] in kept_relation_ids]

        return RetrievalResult(
            query=query,
            root=result["root"],
            entities=kept_entities,
            relations=kept_relations,
            paths={eid: [str(rid) for rid in rel_ids] for eid, rel_ids in kept_paths.items()},
        )


def sweep_relative_thresholds(candidates: list[float]) -> list[float]:
    """Deduplicated, sorted candidate thresholds for dev-set calibration."""
    return sorted(set(candidates))


__all__ = [
    "DEFAULT_RELATIVE_THRESHOLD",
    "QueryConditionedRetriever",
    "score_entity",
    "sweep_relative_thresholds",
]
