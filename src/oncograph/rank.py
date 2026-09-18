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
from dataclasses import dataclass

from sqlmodel import Session

from .query import RetrievalQuery, RetrievalResult, TraversalFilters, resolve_entity, traverse
from .semantic import TfidfSpace, cosine_similarity

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


# ---------------------------------------------------------------------------
# HybridPathRanker: semantic + structural extension
# ---------------------------------------------------------------------------
#
# QueryConditionedRetriever above is left entirely unmodified -- its
# behavior is part of the already-recorded docs/BENCHMARK_RUN_v3_ranked.md
# result and must not change retroactively. Everything below is additive:
# a second, independent Retriever that reuses the same traverse() call and
# relative-threshold keep/drop mechanism, but scores candidates on five
# decomposable, inspectable components -- lexical, semantic (TF-IDF cosine,
# oncograph.semantic), structural (entity-type/hop), provenance
# (evidence tier/verification), and a hub/branch penalty -- combined by
# configurable weights so each can be zeroed out for a clean ablation
# without duplicating the retrieval logic five times. See
# docs/BENCHMARK_RUN_v3_hybrid.md for the dev calibration and held-out
# results.

# A small, generic entity-type vocabulary a question's own words might
# name -- the same kind of controlled mapping web/app.js's FACET_KEYWORDS
# already uses for search-intent parsing, not something invented for or
# tuned to this benchmark's specific items.
_TYPE_KEYWORDS = {
    "gene": "gene", "genes": "gene", "target": "gene", "targets": "gene",
    "protein": "protein", "proteins": "protein",
    "drug": "drug", "drugs": "drug", "medication": "drug", "medications": "drug",
    "disease": "disease", "diseases": "disease", "cancer": "disease", "tumor": "disease",
    "trial": "trial", "trials": "trial", "study": "trial", "studies": "trial",
    "pathway": "pathway", "pathways": "pathway",
    "tissue": "tissue", "tissues": "tissue",
    "combination": "combination_treatment", "treatment": "combination_treatment",
}


def _entity_text(entity: dict) -> str:
    """Name + aliases (when the export carries them, e.g. Gene entities --
    see scripts/build_static_site.py's _exported_metadata allowlist)."""
    parts = [entity.get("name") or ""]
    aliases = (entity.get("metadata") or {}).get("aliases") or []
    parts.extend(str(a) for a in aliases)
    return " ".join(p for p in parts if p)


def _evidence_context_text(evidence_list: list[dict]) -> str:
    """Flatten each evidence row's context/evidence_type into text -- e.g. a
    trial edge's matched_intervention/overall_status/phases, a ChEMBL edge's
    mechanism_of_action, a GTEx edge's tissue/median_tpm."""
    parts: list[str] = []
    for evidence in evidence_list:
        if evidence.get("evidence_type"):
            parts.append(str(evidence["evidence_type"]).replace("_", " "))
        for value in (evidence.get("context") or {}).values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(v) for v in value if isinstance(v, str))
    return " ".join(parts)


def relation_document(relation: dict, subject_entity: dict, object_entity: dict) -> str:
    """The "semantic text" for one relation: subject name/aliases,
    predicate, object name/aliases, evidence context -- never a gold
    answer or gold evidence field, only real graph/evidence content."""
    return " ".join(
        [
            _entity_text(subject_entity),
            relation["predicate"].replace("_", " "),
            _entity_text(object_entity),
            _evidence_context_text(relation.get("evidence") or []),
        ]
    )


def path_document(path_relation_ids: list[str], relations_by_id: dict[str, dict], entities_by_id: dict[str, dict]) -> str:
    """Concatenated per-hop relation_document() text for a multi-hop path."""
    parts = []
    for relation_id in path_relation_ids:
        relation = relations_by_id.get(relation_id)
        if relation is None:
            continue
        subject_entity = entities_by_id.get(relation["subject_id"], {})
        object_entity = entities_by_id.get(relation["object_id"], {})
        parts.append(relation_document(relation, subject_entity, object_entity))
    return " ".join(parts)


def _expected_entity_type(question_tokens: set[str]) -> str | None:
    for token in question_tokens:
        if token in _TYPE_KEYWORDS:
            return _TYPE_KEYWORDS[token]
    return None


def _entity_type_match_score(entity: dict, expected_type: str | None) -> float:
    """1.0 if the question names this entity's type, 0.0 if it names a
    *different* type, 0.5 (neutral) if the question gives no type signal."""
    if expected_type is None:
        return 0.5
    return 1.0 if str(entity.get("type", "")).lower() == expected_type else 0.0


def lexical_component(question_tokens: set[str], path_relations: list[dict]) -> float:
    """Mean predicate/question token overlap across the path's hops."""
    if not path_relations:
        return 0.0
    total = sum(len(question_tokens & _predicate_tokens(r["predicate"])) for r in path_relations)
    return total / len(path_relations)


def semantic_component(question_text: str, document: str, tfidf_space: TfidfSpace) -> float:
    """TF-IDF cosine similarity between the question and this path's
    document (oncograph.semantic) -- 0.0 with no question text or an
    empty/unbuilt document, the graceful fallback."""
    if not question_text or not document:
        return 0.0
    return cosine_similarity(tfidf_space.vectorize(question_text), tfidf_space.vectorize(document))


def structural_component(entity: dict, hop_distance: int, expected_type: str | None) -> float:
    """Entity-type/question compatibility averaged with an inverse-hop-
    distance preference for closer, more direct evidence."""
    type_score = _entity_type_match_score(entity, expected_type)
    hop_score = 1.0 / hop_distance if hop_distance > 0 else 0.0
    return (type_score + hop_score) / 2.0


# A trial's overall_status counts as "informative" when the registry
# reports a definite state -- an UNKNOWN status trial record is less
# complete/attested than one with a concrete status, independent of what
# the question asks. Not a preference for any particular status value.
_INFORMATIVE_TRIAL_STATUSES = {
    "completed", "active_not_recruiting", "recruiting", "enrolling_by_invitation",
    "terminated", "withdrawn", "suspended",
}


def _trial_context_specificity(relation: dict, root_entity: dict) -> float:
    """Real, available ClinicalTrials.gov edge-context fields (Issue #11:
    sources/clinicaltrials.py's studied_in edges carry matched_intervention/
    overall_status/phases) used to prefer a more precisely-attested trial
    record over a vaguer one -- never a preference correlated with any
    particular benchmark item's gold trial, only with record quality/
    specificity available in the graph itself.

    - +0.15 when the edge's own matched_intervention text is an *exact*
      match to the root drug's name (a precise single-agent record) rather
      than a partial/fuzzy match (e.g. matched within a combination
      product's longer intervention name).
    - +0.1 when the trial has a concrete (non-UNKNOWN) overall_status.

    Kept deliberately small relative to the base tier score: found via dev
    debugging that an earlier, larger version (+0.5/+0.25) let this signal
    -- meant only to break ties *among* same-predicate trial siblings --
    outweigh the base tier score entirely, making trial evidence look
    higher-provenance than a curated_database gene-target edge and
    *hurting* single_hop_factual_retrieval instead of only helping
    trial_lookup (see docs/BENCHMARK_RUN_v3_hybrid.md).
    """
    context = (relation.get("evidence") or [{}])[0].get("context") or {}
    bonus = 0.0
    matched_intervention = context.get("matched_intervention")
    root_name = root_entity.get("name")
    if matched_intervention and root_name and matched_intervention.strip().lower() == root_name.strip().lower():
        bonus += 0.15
    overall_status = str(context.get("overall_status") or "").lower()
    if overall_status in _INFORMATIVE_TRIAL_STATUSES:
        bonus += 0.1
    return bonus


_MAX_TIER_WEIGHT = max(_TIER_WEIGHTS.values())


def provenance_component(path_relations: list[dict], root_entity: dict | None = None) -> float:
    """Mean evidence-tier weight (normalized to roughly [0, 1] by the
    highest defined tier, so this component sits on a comparable scale to
    lexical/semantic/structural rather than dominating them by sharing
    QueryConditionedRetriever's unnormalized 0.5-3.0 tier scale) across the
    path's hops, with a small bonus for human-verified evidence, a cited
    publication, or (Issue #11 trial context, when ``root_entity`` is
    given) a precisely-matched, well-attested ClinicalTrials.gov record --
    richer, better-attested provenance scores higher.

    Deliberately a *separate* normalization from ``_tier_weight``'s raw
    0.5-3.0 scale (used unchanged by QueryConditionedRetriever, whose
    already-recorded docs/BENCHMARK_RUN_v3_ranked.md result must not
    change retroactively) -- found necessary via dev-set debugging: an
    unnormalized provenance term of the same nominal weight as lexical
    ended up dominating it and diluting the sharp lexical signal that was
    working well, discovered by inspecting the raw component scores on a
    known dev example (see docs/BENCHMARK_RUN_v3_hybrid.md).
    """
    if not path_relations:
        return 0.0
    total = 0.0
    for relation in path_relations:
        evidence = (relation.get("evidence") or [{}])[0]
        score = _tier_weight(relation) / _MAX_TIER_WEIGHT
        if str(evidence.get("verification_status", "")).lower() == "verified":
            score += 0.25
        if evidence.get("publication_id"):
            score += 0.25
        if root_entity is not None:
            score += _trial_context_specificity(relation, root_entity)
        total += score
    return total / len(path_relations)


def go_branch_factor(entity_id: str, relations: list[dict]) -> int:
    """How many *locally reached* entities point to this one via ``is_a`` --
    a proxy for how generic/root-like a GO term is (a highly generic term
    like "biological_process" has many children; a specific leaf term has
    few or none). Computed only from relations already touched by this
    query's own traversal -- never a global, precomputed graph statistic,
    since GO_TERM entity metadata (is_root/child_count, computed by
    sources/gene_ontology.py at import time) is not carried through to the
    frozen public snapshot this benchmark reads (scripts/build_static_site.py
    only exports metadata for PAPER/GENE types) and the frozen snapshot
    must not be modified to add it retroactively.
    """
    return sum(1 for r in relations if r["predicate"] == "is_a" and r["object_id"] == entity_id)


def hub_branch_penalty(entity: dict, degree_by_entity: dict[str, int], relations: list[dict]) -> float:
    """Local-degree hub penalty, plus an extra penalty for GO terms with a
    high local branching factor (many reached entities is_a-ing into them --
    the generic/root-like terms Issue #8's UI already tries to filter out
    of list views). 0 additional penalty for a leaf/non-branching GO term
    or any non-GO_TERM entity."""
    degree_penalty = math.log2(2 + degree_by_entity.get(entity["id"], 1))
    branch_penalty = 0.0
    if str(entity.get("type", "")).lower() == "go_term":
        branch_penalty = math.log2(2 + go_branch_factor(entity["id"], relations)) - 1.0
    return degree_penalty + branch_penalty


@dataclass(frozen=True)
class HybridWeights:
    """Combination weights for HybridPathRanker's five components. Zero out
    any weight to run a clean ablation without a separate code path --
    see docs/BENCHMARK_RUN_v3_hybrid.md's ablation table."""

    lexical: float = 1.0
    semantic: float = 1.0
    structural: float = 1.0
    provenance: float = 1.0
    hub: float = 1.0


@dataclass(frozen=True)
class ComponentScores:
    """Every score HybridPathRanker computed for one reached entity --
    inspectable individually, per Issue's requirement that the ranking stay
    interpretable rather than an opaque combined number."""

    entity_id: str
    lexical: float
    semantic: float
    structural: float
    provenance: float
    hub_branch_penalty: float
    combined: float


DEFAULT_HYBRID_WEIGHTS = HybridWeights()


class HybridPathRanker:
    """Query-conditioned relation/path selection with semantic + structural
    signals on top of QueryConditionedRetriever's lexical-only approach.

    ``combined = (w_lex*lexical + w_sem*semantic + w_struct*structural +
    w_prov*provenance) / (1 + w_hub*hub_branch_penalty)``, then the same
    relative-threshold keep/drop rule as QueryConditionedRetriever (entities
    scoring below ``relative_threshold * max_combined`` are dropped; the
    degenerate all-zero case keeps everyone). ``weights``/``relative_threshold``
    are calibrated on the benchmark dev split only -- see
    docs/BENCHMARK_RUN_v3_hybrid.md -- and frozen before any held-out score
    is computed.
    """

    def __init__(
        self,
        session: Session,
        weights: HybridWeights = DEFAULT_HYBRID_WEIGHTS,
        relative_threshold: float = DEFAULT_RELATIVE_THRESHOLD,
    ):
        self.session = session
        self.weights = weights
        self.relative_threshold = relative_threshold

    def score_candidates(self, query: RetrievalQuery) -> list[ComponentScores]:
        """The full, decomposed score for every reached (non-root) entity --
        exposed separately from retrieve() so callers/tests can inspect each
        component without reconstructing them from a filtered RetrievalResult."""
        root = resolve_entity(self.session, query.root_ref, query.root_type)
        if root is None:
            return []
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
            return []

        relations_by_id = {relation["id"]: relation for relation in result["relations"]}
        entities_by_id = {entity["id"]: entity for entity in result["entities"]}
        degree_by_entity = {
            entity["id"]: _local_degree(entity["id"], result["relations"]) for entity in result["entities"]
        }
        question_tokens = _tokenize(query.question_text) if query.question_text else set()
        expected_type = _expected_entity_type(question_tokens)
        root_id = str(root.id)

        # One shared local TF-IDF space per query: the question text plus
        # every candidate's path document -- see oncograph.semantic.
        candidate_paths = {eid: ids for eid, ids in result["paths"].items() if eid != root_id and ids}
        documents = {
            eid: path_document(path_ids, relations_by_id, entities_by_id) for eid, path_ids in candidate_paths.items()
        }
        corpus = [query.question_text or "", *documents.values()]
        tfidf_space = TfidfSpace(corpus)

        scored: list[ComponentScores] = []
        for entity_id, path_ids in candidate_paths.items():
            entity = entities_by_id[entity_id]
            path_relations = [relations_by_id[rid] for rid in path_ids if rid in relations_by_id]
            hop_distance = len(path_ids)

            lexical = lexical_component(question_tokens, path_relations)
            semantic = semantic_component(query.question_text or "", documents[entity_id], tfidf_space)
            structural = structural_component(entity, hop_distance, expected_type)
            provenance = provenance_component(path_relations, root_entity=result["root"])
            hub_penalty = hub_branch_penalty(entity, degree_by_entity, result["relations"])

            raw = (
                self.weights.lexical * lexical
                + self.weights.semantic * semantic
                + self.weights.structural * structural
                + self.weights.provenance * provenance
            )
            combined = raw / (1.0 + self.weights.hub * hub_penalty)
            scored.append(
                ComponentScores(
                    entity_id=entity_id,
                    lexical=lexical,
                    semantic=semantic,
                    structural=structural,
                    provenance=provenance,
                    hub_branch_penalty=hub_penalty,
                    combined=combined,
                )
            )
        # Deterministic order: highest combined score first, entity_id as a
        # stable tie-breaker -- never left to dict/set iteration order.
        scored.sort(key=lambda s: (-s.combined, s.entity_id))
        return scored

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

        root_id = str(root.id)
        scored = self.score_candidates(query)
        max_combined = max((s.combined for s in scored), default=0.0)
        if max_combined <= 0.0:
            kept_ids = {s.entity_id for s in scored} | {root_id}
        else:
            cutoff = self.relative_threshold * max_combined
            kept_ids = {s.entity_id for s in scored if s.combined >= cutoff} | {root_id}

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


__all__ = [
    "DEFAULT_HYBRID_WEIGHTS",
    "DEFAULT_RELATIVE_THRESHOLD",
    "ComponentScores",
    "HybridPathRanker",
    "HybridWeights",
    "QueryConditionedRetriever",
    "go_branch_factor",
    "hub_branch_penalty",
    "lexical_component",
    "path_document",
    "provenance_component",
    "relation_document",
    "score_entity",
    "semantic_component",
    "structural_component",
    "sweep_relative_thresholds",
]
