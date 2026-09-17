"""Evidence-aware graph traversal and representative oncology query helpers.

Everything here returns machine-readable, JSON-serializable dicts/dataclasses
-- never prose -- so a caller (API endpoint, notebook, or a future GraphRAG
layer) gets entities, relations, their supporting evidence (source,
provenance, confidence, context, claim_state, publication reference), and
the path taken, without having to re-derive any of it.

``Retriever``/``RetrievalQuery``/``RetrievalResult`` exist so LLM-only,
flat/vector-RAG, and vanilla graph-retrieval baselines (Issue #9's job, not
this one) can be compared against ``GraphRetriever`` through one interface,
without redesigning this module. Only ``GraphRetriever`` is implemented here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from sqlmodel import Session, or_, select

from .models import Entity, Evidence, Relation


def _entity_dict(entity: Entity) -> dict:
    return {
        "id": str(entity.id),
        "type": entity.type,
        "name": entity.name,
        "canonical_id": entity.canonical_id,
        "description": entity.description,
    }


def _evidence_dict(evidence: Evidence) -> dict:
    return {
        "id": str(evidence.id),
        "source": evidence.source,
        "source_id": evidence.source_id,
        "source_url": evidence.source_url,
        "source_type": evidence.source_type,
        "evidence_type": evidence.evidence_type,
        "license": evidence.license,
        "publication_id": str(evidence.publication_id) if evidence.publication_id else None,
        "context": json.loads(evidence.context) if evidence.context else None,
        "confidence": evidence.confidence,
        "claim_state": evidence.claim_state,
        "verification_status": evidence.verification_status,
        "retrieved_at": evidence.retrieved_at.isoformat(),
    }


def _relation_dict(relation: Relation, evidence_rows: list[Evidence]) -> dict:
    evidences = [_evidence_dict(e) for e in evidence_rows]
    claim_states = {e["claim_state"] for e in evidences}
    return {
        "id": str(relation.id),
        "subject_id": str(relation.subject_id),
        "predicate": relation.predicate,
        "object_id": str(relation.object_id),
        "evidence": evidences,
        "has_contradictory_evidence": "supports" in claim_states and "contradicts" in claim_states,
        "publication_ids": sorted({e["publication_id"] for e in evidences if e["publication_id"]}),
    }


def resolve_entity(session: Session, ref: str, entity_type: str | None = None) -> Entity | None:
    """Resolve a caller-supplied reference: an entity UUID, a canonical_id, or a name.

    Tried in that order (most to least specific), matching this repository's
    identifier-first policy: exact identifier matches win over name matches.
    """
    try:
        entity_id = UUID(ref)
    except (ValueError, AttributeError, TypeError):
        entity_id = None
    if entity_id is not None:
        entity = session.get(Entity, entity_id)
        if entity is not None and (entity_type is None or entity.type == entity_type):
            return entity

    stmt = select(Entity).where(Entity.canonical_id == ref)
    if entity_type is not None:
        stmt = stmt.where(Entity.type == entity_type)
    entity = session.exec(stmt).first()
    if entity is not None:
        return entity

    stmt = select(Entity).where(Entity.name.ilike(ref))
    if entity_type is not None:
        stmt = stmt.where(Entity.type == entity_type)
    return session.exec(stmt).first()


@dataclass(frozen=True)
class TraversalFilters:
    max_hops: int = 1
    predicates: frozenset[str] | None = None
    sources: frozenset[str] | None = None
    min_confidence: float | None = None
    require_publication: bool = False


def traverse(session: Session, root_id: UUID, filters: TraversalFilters | None = None) -> dict | None:
    """Evidence-aware N-hop traversal from ``root_id``.

    Explores both outgoing and incoming relations at each hop (this
    repository's graph isn't queried as strictly directional -- "genes
    associated with this disease" should work regardless of which side is
    stored as subject), applies ``filters`` per relation, and returns every
    reached entity, every relation actually traversed (with its full
    evidence, including contradictory/context-dependent rows), and the
    shortest relation-id path from the root to each entity.
    """
    filters = filters or TraversalFilters()
    root = session.get(Entity, root_id)
    if root is None:
        return None

    entities: dict[UUID, Entity] = {root_id: root}
    relations: dict[UUID, Relation] = {}
    evidence_by_relation: dict[UUID, list[Evidence]] = {}
    paths: dict[UUID, list[UUID]] = {root_id: []}
    frontier = {root_id}

    for _ in range(filters.max_hops):
        if not frontier:
            break
        statement = select(Relation).where(
            or_(Relation.subject_id.in_(frontier), Relation.object_id.in_(frontier))
        )
        if filters.predicates:
            statement = statement.where(Relation.predicate.in_(filters.predicates))
        candidates = session.exec(statement).all()

        next_frontier: set[UUID] = set()
        for rel in candidates:
            evidence_rows = session.exec(
                select(Evidence).where(Evidence.relation_id == rel.id)
            ).all()
            if filters.sources:
                evidence_rows = [e for e in evidence_rows if e.source in filters.sources]
            if filters.min_confidence is not None:
                evidence_rows = [
                    e
                    for e in evidence_rows
                    if e.confidence is not None and e.confidence >= filters.min_confidence
                ]
            if filters.require_publication:
                evidence_rows = [e for e in evidence_rows if e.publication_id is not None]
            if not evidence_rows:
                continue

            if rel.id not in relations:
                relations[rel.id] = rel
                evidence_by_relation[rel.id] = evidence_rows

            if rel.subject_id in frontier and rel.object_id not in entities:
                new_id, known_id = rel.object_id, rel.subject_id
            elif rel.object_id in frontier and rel.subject_id not in entities:
                new_id, known_id = rel.subject_id, rel.object_id
            else:
                continue

            new_entity = session.get(Entity, new_id)
            if new_entity is None:
                continue
            entities[new_id] = new_entity
            paths[new_id] = [*paths.get(known_id, []), rel.id]
            next_frontier.add(new_id)

        frontier = next_frontier

    return {
        "root": _entity_dict(root),
        "entities": [_entity_dict(e) for e in entities.values()],
        "relations": [_relation_dict(relations[rid], evidence_by_relation[rid]) for rid in relations],
        "paths": {str(eid): [str(rid) for rid in rel_ids] for eid, rel_ids in paths.items()},
    }


# --- Representative oncology query helpers ------------------------------------
#
# Each resolves a starting entity by name/canonical_id/UUID, then traverses.
# None hard-code predicate names: our sources use different predicates for
# similar claims (e.g. "associated_with" vs "clinically_associated_with"), so
# filtering out anything not on a hand-picked list would silently hide real,
# differently-sourced evidence. The helper's value is the entity-type-aware
# starting point and a sensible hop depth, not predicate guessing.


def disease_to_genes_to_drugs(session: Session, disease_ref: str) -> dict | None:
    disease = resolve_entity(session, disease_ref, entity_type="disease")
    if disease is None:
        return None
    return traverse(session, disease.id, TraversalFilters(max_hops=2))


def drug_to_target_to_pathway_to_disease(session: Session, drug_ref: str) -> dict | None:
    drug = resolve_entity(session, drug_ref, entity_type="drug")
    if drug is None:
        return None
    return traverse(session, drug.id, TraversalFilters(max_hops=3))


def gene_to_pathway_to_disease(session: Session, gene_ref: str) -> dict | None:
    gene = resolve_entity(session, gene_ref, entity_type="gene")
    if gene is None:
        return None
    return traverse(session, gene.id, TraversalFilters(max_hops=2))


def biomarker_to_response_to_drug(session: Session, biomarker_ref: str) -> dict | None:
    biomarker = resolve_entity(session, biomarker_ref, entity_type="biomarker")
    if biomarker is None:
        return None
    return traverse(session, biomarker.id, TraversalFilters(max_hops=2))


def trial_to_disease_to_intervention(session: Session, trial_ref: str) -> dict | None:
    trial = resolve_entity(session, trial_ref, entity_type="trial")
    if trial is None:
        return None
    return traverse(session, trial.id, TraversalFilters(max_hops=2))


def drug_to_publication_supported_disease_path(session: Session, drug_ref: str) -> dict | None:
    """Like drug_to_target_to_pathway_to_disease, but only hops with a citation."""
    drug = resolve_entity(session, drug_ref, entity_type="drug")
    if drug is None:
        return None
    return traverse(session, drug.id, TraversalFilters(max_hops=3, require_publication=True))


# --- Retrieval-strategy comparison interface -----------------------------------


@dataclass(frozen=True)
class RetrievalQuery:
    root_ref: str
    root_type: str | None = None
    max_hops: int = 2
    predicates: frozenset[str] | None = None
    sources: frozenset[str] | None = None
    min_confidence: float | None = None
    require_publication: bool = False


@dataclass
class RetrievalResult:
    query: RetrievalQuery
    root: dict | None
    entities: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    paths: dict[str, list[str]] = field(default_factory=dict)


class Retriever(Protocol):
    """Common interface for comparing retrieval strategies (see Issue #9).

    Only ``GraphRetriever`` is implemented in this codebase. LLM-only,
    flat/vector-RAG, and vanilla graph-retrieval baselines should implement
    this same interface rather than a bespoke one, so a benchmark harness can
    swap them in without touching the query layer.
    """

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult: ...


class GraphRetriever:
    """Evidence-aware OncoGraph retrieval: the one real ``Retriever`` here."""

    def __init__(self, session: Session):
        self.session = session

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
        return RetrievalResult(
            query=query,
            root=result["root"],
            entities=result["entities"],
            relations=result["relations"],
            paths=result["paths"],
        )
