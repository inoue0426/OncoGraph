"""MCP tool implementations. Every tool is a thin wrapper: entity resolution,
graph traversal, evidence shaping, and stats counting are all delegated to
``oncograph.query`` / ``oncograph.rank`` / ``oncograph.stats`` -- nothing
here re-derives or duplicates that logic.

Each public, MCP-registered function (the exact names/signatures in
docs/MCP.md) opens its own session via ``_common.session_scope()`` and
delegates immediately to a private, session-taking ``_...`` implementation
-- the private functions are what tests call directly, so tool logic is
testable without spinning up an MCP server or a real database file.

Research use only: nothing here infers, upgrades, or fabricates a
biomedical conclusion -- see docs/MCP.md's "Provenance behavior" section.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlmodel import Session, func, or_, select

from .. import stats as stats_module
from ..models import Entity, Evidence, Relation
from ..query import (
    RetrievalQuery,
    TraversalFilters,
    _entity_dict,
    _relation_dict,
    resolve_entity,
    traverse,
)
from ._common import (
    OncoGraphMCPError,
    clamp_hops,
    clamp_limit,
    entity_public_dict,
    make_retriever,
    session_scope,
    validate_entity_type,
)

# Real, enumerable evidence_type vocabulary for "this edge describes a
# mechanism of action / molecular target", drawn directly from the source
# adapters that emit it (docs/MECHANISTIC_SOURCES.md). DrugMechDB's
# mechanism-*path* predicate text is dynamic (derived from the curated
# source's own link labels), so mechanism relations are identified by
# evidence_type here, never by guessing at predicate names.
_MECHANISM_EVIDENCE_TYPES = frozenset(
    {
        "target_interaction",
        "chembl_mechanism_of_action",
        "drugmechdb_direct_target",
        "drugmechdb_mechanism_path",
        "drugcentral_mechanism_of_action",
        "signor_causal_signaling",
        "drug_gene_interaction_aggregated",
    }
)


def _is_mechanism_relation(relation: dict) -> bool:
    for evidence in relation["evidence"]:
        evidence_type = evidence.get("evidence_type") or ""
        if evidence_type in _MECHANISM_EVIDENCE_TYPES or evidence_type.startswith("bindingdb_"):
            return True
    return False


def _entity_or_error(session: Session, entity_id: str, entity_type: str | None = None) -> Entity:
    entity = resolve_entity(session, entity_id, entity_type)
    if entity is None:
        raise OncoGraphMCPError(f"No entity found for {entity_id!r}" + (f" (type={entity_type})" if entity_type else ""))
    return entity


def _relation_count_and_sources(session: Session, entity_id: UUID) -> tuple[int, int]:
    relation_count = session.exec(
        select(func.count()).select_from(Relation).where(or_(Relation.subject_id == entity_id, Relation.object_id == entity_id))
    ).one()
    source_count = session.exec(
        select(func.count(func.distinct(Evidence.source)))
        .select_from(Evidence)
        .join(Relation, Relation.id == Evidence.relation_id)
        .where(or_(Relation.subject_id == entity_id, Relation.object_id == entity_id))
    ).one()
    return relation_count, source_count


# --- search_entities ------------------------------------------------------------


def _rank_key(entity: Entity, lowered_query: str) -> tuple[int, str]:
    name = (entity.name or "").lower()
    canonical = (entity.canonical_id or "").lower()
    if canonical == lowered_query:
        tier = 0
    elif name == lowered_query:
        tier = 1
    elif name.startswith(lowered_query):
        tier = 2
    else:
        tier = 3
    return (tier, name)


def _search_entities(session: Session, query: str, entity_type: str | None, limit: int) -> dict[str, Any]:
    stripped = query.strip()
    if not stripped:
        return {"query": query, "entity_type": entity_type, "results": [], "result_count": 0}
    lowered = stripped.lower()
    like_pattern = f"%{stripped}%"
    stmt = select(Entity).where(
        or_(
            Entity.canonical_id.ilike(stripped),
            Entity.name.ilike(like_pattern),
            Entity.entity_metadata.ilike(like_pattern),
        )
    )
    if entity_type is not None:
        stmt = stmt.where(Entity.type == entity_type)
    candidates = session.exec(stmt).all()
    ranked = sorted(candidates, key=lambda e: _rank_key(e, lowered))[:limit]

    results = []
    for entity in ranked:
        relation_count, source_count = _relation_count_and_sources(session, entity.id)
        result = entity_public_dict(entity)
        result["relation_count"] = relation_count
        result["evidence_source_count"] = source_count
        results.append(result)

    return {"query": query, "entity_type": entity_type, "results": results, "result_count": len(results)}


def search_entities(query: str, entity_type: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Ranked entity search by canonical ID, name, or alias substring.

    Ranking: exact canonical_id > exact name > name-prefix > name/alias
    substring, ties broken by name. Returns at most ``limit`` (clamped to
    MAX_RESULT_LIMIT) results, each with its canonical ID, name, type,
    aliases, compact metadata, relation count, and distinct evidence-source
    count.
    """
    normalized_type = validate_entity_type(entity_type)
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _search_entities(session, query, normalized_type, limit)


# --- get_entity -------------------------------------------------------------


def _get_entity(session: Session, entity_id: str) -> dict[str, Any]:
    entity = _entity_or_error(session, entity_id)
    relation_count, source_count = _relation_count_and_sources(session, entity.id)
    predicate_rows = session.exec(
        select(Relation.predicate).where(or_(Relation.subject_id == entity.id, Relation.object_id == entity.id)).distinct()
    ).all()
    result = entity_public_dict(entity)
    result["relation_summary"] = {
        "relation_count": relation_count,
        "evidence_source_count": source_count,
        "distinct_predicates": sorted(predicate_rows),
    }
    return result


def get_entity(entity_id: str) -> dict[str, Any]:
    """Canonical entity data (identifiers, aliases, metadata) plus a relation
    summary (count, distinct predicates, distinct evidence sources).
    ``entity_id`` may be a UUID, a canonical_id, or an exact name (see
    ``oncograph.query.resolve_entity``)."""
    with session_scope() as session:
        return _get_entity(session, entity_id)


# --- get_neighbors ------------------------------------------------------------


def _get_neighbors(
    session: Session, entity_id: str, predicate: str | None, entity_type: str | None, limit: int
) -> dict[str, Any]:
    entity = _entity_or_error(session, entity_id)
    result = traverse(
        session,
        entity.id,
        _traversal_filters(max_hops=1, predicate=predicate),
    )
    root_id = str(entity.id)
    neighbors = []
    for candidate in result["entities"]:
        if candidate["id"] == root_id:
            continue
        if entity_type is not None and candidate["type"].lower() != entity_type:
            continue
        neighbors.append(candidate)
    neighbors.sort(key=lambda e: (e["name"] or "").lower())
    neighbors = neighbors[:limit]
    kept_ids = {n["id"] for n in neighbors} | {root_id}
    relations = [
        r for r in result["relations"] if r["subject_id"] in kept_ids and r["object_id"] in kept_ids
    ]
    return {
        "entity": result["root"],
        "predicate": predicate,
        "entity_type": entity_type,
        "neighbors": neighbors,
        "relations": relations,
        "neighbor_count": len(neighbors),
    }


def get_neighbors(
    entity_id: str,
    predicate: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Direct (1-hop) neighboring entities and the exact relations connecting
    them, optionally filtered by predicate and/or neighbor entity type."""
    normalized_type = validate_entity_type(entity_type)
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _get_neighbors(session, entity_id, predicate, normalized_type, limit)


# --- get_evidence -------------------------------------------------------------


def _get_evidence(session: Session, relation_id: str) -> dict[str, Any]:
    try:
        parsed_id = UUID(relation_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise OncoGraphMCPError(f"relation_id must be a UUID, got {relation_id!r}") from exc
    relation = session.get(Relation, parsed_id)
    if relation is None:
        raise OncoGraphMCPError(f"No relation found for {relation_id!r}")
    evidence_rows = session.exec(select(Evidence).where(Evidence.relation_id == parsed_id)).all()
    subject = session.get(Entity, relation.subject_id)
    obj = session.get(Entity, relation.object_id)
    relation_dict = _relation_dict(relation, list(evidence_rows))
    return {
        "relation": {
            "id": relation_dict["id"],
            "predicate": relation_dict["predicate"],
            "subject": _entity_dict(subject) if subject else None,
            "object": _entity_dict(obj) if obj else None,
            "has_contradictory_evidence": relation_dict["has_contradictory_evidence"],
        },
        "evidence": relation_dict["evidence"],
        "evidence_count": len(relation_dict["evidence"]),
    }


def get_evidence(relation_id: str) -> dict[str, Any]:
    """Every evidence record for one relation (by relation UUID), preserving
    source, source_type, evidence_type, source record identifier,
    publication reference, context, confidence, claim_state, verification
    status, retrieval date, and license -- exactly as stored, nothing
    upgraded or summarized into a single claim."""
    with session_scope() as session:
        return _get_evidence(session, relation_id)


# --- traverse_graph -------------------------------------------------------------


def _traversal_filters(
    max_hops: int,
    predicate: str | None,
    source: str | None = None,
    min_confidence: float | None = None,
    require_publication: bool = False,
) -> TraversalFilters:
    return TraversalFilters(
        max_hops=max_hops,
        predicates=frozenset({predicate}) if predicate else None,
        sources=frozenset({source}) if source else None,
        min_confidence=min_confidence,
        require_publication=require_publication,
    )


def _limit_retrieval_result(result, limit: int) -> dict[str, Any]:
    """Cap a RetrievalResult to at most ``limit`` non-root entities, keeping
    only the relations/paths that still connect a kept entity -- the same
    "filter to kept entities" pattern oncograph.rank's retrievers already use."""
    root_id = result.root["id"] if result.root else None
    non_root = [e for e in result.entities if e["id"] != root_id]
    kept = non_root[:limit]
    kept_ids = {e["id"] for e in kept} | ({root_id} if root_id else set())
    relations = [r for r in result.relations if r["subject_id"] in kept_ids and r["object_id"] in kept_ids]
    paths = {eid: path for eid, path in result.paths.items() if eid in kept_ids}
    entities = ([result.root] if result.root else []) + kept
    return {
        "root": result.root,
        "entities": entities,
        "relations": relations,
        "paths": paths,
        "entity_count": len(entities),
        "relation_count": len(relations),
        "truncated": len(non_root) > limit,
    }


def _traverse_graph(
    session: Session,
    entity_id: str,
    max_hops: int,
    predicate: str | None,
    source: str | None,
    min_confidence: float | None,
    require_publication: bool,
    limit: int,
    retrieval_strategy: str,
    question: str | None,
) -> dict[str, Any]:
    retriever = make_retriever(session, retrieval_strategy)
    query = RetrievalQuery(
        root_ref=entity_id,
        max_hops=max_hops,
        predicates=frozenset({predicate}) if predicate else None,
        sources=frozenset({source}) if source else None,
        min_confidence=min_confidence,
        require_publication=require_publication,
        question_text=question,
    )
    result = retriever.retrieve(query)
    if result.root is None:
        raise OncoGraphMCPError(f"No entity found for {entity_id!r}")
    payload = _limit_retrieval_result(result, limit)
    payload["retrieval_strategy"] = retrieval_strategy
    payload["max_hops"] = max_hops
    contradictory = [r["id"] for r in payload["relations"] if r.get("has_contradictory_evidence")]
    payload["contradictory_relation_ids"] = contradictory
    return payload


def traverse_graph(
    entity_id: str,
    max_hops: int = 2,
    predicate: str | None = None,
    source: str | None = None,
    min_confidence: float | None = None,
    require_publication: bool = False,
    limit: int = 100,
    retrieval_strategy: str = "query_conditioned",
    question: str | None = None,
) -> dict[str, Any]:
    """Evidence-aware N-hop traversal from an entity (UUID, canonical_id, or
    exact name).

    ``retrieval_strategy``: "graph" (no ranking, every reachable relation
    kept), "query_conditioned" (default -- lexical relevance ranking,
    dev-calibrated and held-out-validated, see docs/BENCHMARK_RUN_v3_ranked.md),
    or "hybrid_experimental" (semantic+structural ranking -- EXPERIMENTAL,
    documented in docs/BENCHMARK_RUN_v3_hybrid.md to underperform
    query_conditioned on the project's own benchmark; only used when asked
    for explicitly). ``question`` is an optional natural-language hint the
    ranking strategies use to score relevance -- ignored by "graph".

    Returns reached entities, the relations connecting them (each with
    full evidence), the shortest computed path (relation-id chain) to each
    entity, and which relations carry contradictory evidence. ``max_hops``
    is capped at 5 regardless of the requested value.
    """
    max_hops = clamp_hops(max_hops)
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _traverse_graph(
            session, entity_id, max_hops, predicate, source, min_confidence, require_publication, limit, retrieval_strategy, question
        )


# --- get_graph_stats ------------------------------------------------------------


def _stats_export(session: Session) -> tuple[list[dict], list[dict]]:
    """Build the minimal entity/relation dict shape oncograph.stats.compute_stats
    needs, directly from the live database -- the same shape
    scripts/build_static_site.py's read_entities/read_relations produce from
    a frozen SQLite snapshot, so the exact same counting function applies to
    either source without modification."""
    entities = [{"type": str(entity.type)} for entity in session.exec(select(Entity)).all()]

    relations_by_id: dict[UUID, dict] = {}
    for relation in session.exec(select(Relation)).all():
        relations_by_id[relation.id] = {"predicate": relation.predicate, "evidence": []}
    for evidence in session.exec(select(Evidence)).all():
        relation = relations_by_id.get(evidence.relation_id)
        if relation is None:
            continue
        context = json.loads(evidence.context) if evidence.context else None
        relation["evidence"].append({"source": evidence.source, "source_type": evidence.source_type, "context": context})
    return entities, list(relations_by_id.values())


def get_graph_stats() -> dict[str, Any]:
    """Canonical graph coverage statistics -- entity counts by type, total
    entities/relations, evidence-record and distinct-source counts, and
    (when available) explicit stored/curated path counts (DrugMechDB
    mechanistic paths, benchmark gold-evidence paths). Computed by
    ``oncograph.stats.compute_stats`` (the same function
    ``scripts/build_static_site.py`` uses for the homepage's
    ``web/data/stats.json``) against the live database, not a separate
    counter."""
    with session_scope() as session:
        entities, relations = _stats_export(session)
    return stats_module.compute_stats(entities, relations)


# ---------------------------------------------------------------------------
# Domain convenience tools -- thin wrappers over traverse()/resolve_entity(),
# no new query semantics beyond filtering to a specific, real evidence_type
# or entity_type vocabulary already emitted by the source adapters.
# ---------------------------------------------------------------------------


def _find_drugs_for_disease(session: Session, disease: str, limit: int) -> dict[str, Any]:
    disease_entity = _entity_or_error(session, disease, entity_type="disease")
    result = traverse(session, disease_entity.id, _traversal_filters(max_hops=1, predicate=None))
    root_id = str(disease_entity.id)
    drug_relations = [r for r in result["relations"] if r["subject_id"] != r["object_id"]]
    drugs_by_id = {e["id"]: e for e in result["entities"] if e["id"] != root_id and e["type"].lower() == "drug"}
    drug_ids = set(drugs_by_id)
    relations = [r for r in drug_relations if drug_ids & {r["subject_id"], r["object_id"]}]
    drugs = sorted(drugs_by_id.values(), key=lambda e: (e["name"] or "").lower())[:limit]
    kept_ids = {d["id"] for d in drugs}
    relations = [r for r in relations if kept_ids & {r["subject_id"], r["object_id"]}]
    return {
        "disease": result["root"],
        "drugs": drugs,
        "relations": relations,
        "drug_count": len(drugs),
    }


def find_drugs_for_disease(disease: str, limit: int = 20) -> dict[str, Any]:
    """Drugs with a direct real relation (any predicate -- e.g. indicated_for)
    to the given disease, with the connecting relations and their evidence.
    Not restricted to any one predicate, since different sources describe a
    drug-disease relationship with different real predicates."""
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _find_drugs_for_disease(session, disease, limit)


def _trial_metadata(entity: Entity) -> dict:
    return json.loads(entity.entity_metadata) if entity.entity_metadata else {}


def _find_trials(
    session: Session, query: str | None, disease: str | None, drug: str | None, status: str | None, limit: int
) -> dict[str, Any]:
    candidates: dict[UUID, Entity]
    if drug is not None:
        drug_entity = _entity_or_error(session, drug, entity_type="drug")
        result = traverse(session, drug_entity.id, _traversal_filters(max_hops=1, predicate=None))
        trial_ids = [
            UUID(e["id"]) for e in result["entities"] if e["id"] != str(drug_entity.id) and e["type"].lower() == "trial"
        ]
        candidates = {tid: session.get(Entity, tid) for tid in trial_ids}
    elif query:
        stmt = select(Entity).where(
            Entity.type == "trial",
            or_(Entity.name.ilike(f"%{query}%"), Entity.canonical_id.ilike(query)),
        )
        candidates = {e.id: e for e in session.exec(stmt).all()}
    else:
        candidates = {e.id: e for e in session.exec(select(Entity).where(Entity.type == "trial")).all()}

    filtered = []
    lowered_disease = disease.lower() if disease else None
    lowered_status = status.lower() if status else None
    for entity in candidates.values():
        if entity is None:
            continue
        metadata = _trial_metadata(entity)
        if lowered_disease is not None:
            haystack = " ".join([entity.description or "", " ".join(metadata.get("conditions") or [])]).lower()
            if lowered_disease not in haystack:
                continue
        if lowered_status is not None and (metadata.get("overall_status") or "").lower() != lowered_status:
            continue
        filtered.append(entity)

    filtered.sort(key=lambda e: (e.name or "").lower())
    limited = filtered[:limit]
    trials = []
    for entity in limited:
        entity_dict = entity_public_dict(entity)
        entity_dict["metadata"] = _trial_metadata(entity) or None
        trials.append(entity_dict)
    return {
        "query": query,
        "disease": disease,
        "drug": drug,
        "status": status,
        "trials": trials,
        "trial_count": len(trials),
    }


def find_trials(
    query: str | None = None,
    disease: str | None = None,
    drug: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Registered trials matching any combination of a free-text name/ID
    query, a disease/condition substring, a specific drug (via a real
    studied_in-style relation), and/or an exact overall_status. Trial
    registration only -- never implies efficacy (see docs/MCP.md)."""
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _find_trials(session, query, disease, drug, status, limit)


def _find_drug_mechanism(session: Session, drug: str, disease: str | None, max_hops: int, limit: int) -> dict[str, Any]:
    drug_entity = _entity_or_error(session, drug, entity_type="drug")
    result = traverse(session, drug_entity.id, _traversal_filters(max_hops=max_hops, predicate=None))
    mechanism_relations = [r for r in result["relations"] if _is_mechanism_relation(r)]
    mechanism_entity_ids = {drug_entity.id.__str__()} | {
        eid for r in mechanism_relations for eid in (r["subject_id"], r["object_id"])
    }
    entities = [e for e in result["entities"] if e["id"] in mechanism_entity_ids]

    # disease, when given, is informational context only -- not a filter:
    # a mechanism relation is still a real fact about the drug whether or
    # not it happens to lie on a path to this specific disease. Callers
    # wanting disease-constrained paths should use find_mechanism_paths.
    disease_entity = resolve_entity(session, disease, entity_type="disease") if disease is not None else None

    entities = entities[:limit]
    kept_ids = {e["id"] for e in entities}
    mechanism_relations = [r for r in mechanism_relations if kept_ids & {r["subject_id"], r["object_id"]}]

    return {
        "drug": result["root"],
        "disease_filter": _entity_dict(disease_entity) if disease_entity else disease,
        "mechanism_entities": entities,
        "mechanism_relations": mechanism_relations,
        "entity_count": len(entities),
        "note": "Filtered to relations whose evidence_type identifies a mechanism-of-action/molecular-target "
        "claim (ChEMBL, DrugMechDB, SIGNOR, DrugCentral, GtoPdb primary targets, DGIdb). "
        "disease_filter is informational -- mechanism relations are not required to lead to it.",
    }


def find_drug_mechanism(drug: str, disease: str | None = None, max_hops: int = 4, limit: int = 20) -> dict[str, Any]:
    """The drug's real mechanism-of-action relations (target binding,
    inhibition/agonism, curated mechanism paths) up to max_hops, identified
    by evidence_type -- never a predicate guess. See find_mechanism_paths
    for the ordered-path form of the same data."""
    max_hops = clamp_hops(max_hops)
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _find_drug_mechanism(session, drug, disease, max_hops, limit)


def _stored_mechanism_paths(session: Session, drug_entity: Entity, disease_filter: str | None) -> list[dict]:
    """Real stored/curated paths: DrugMechDB's implicated_in_mechanism_for
    relations carry their *entire* curated drug -> ... -> disease chain in
    evidence.context (sources/drugmechdb.py) -- this reads that chain back
    out, it does not compute anything."""
    rows = session.exec(
        select(Relation, Evidence)
        .join(Evidence, Evidence.relation_id == Relation.id)
        .where(Relation.subject_id == drug_entity.id, Relation.predicate == "implicated_in_mechanism_for")
    ).all()
    paths = []
    lowered_disease = disease_filter.lower() if disease_filter else None
    for relation, evidence in rows:
        context = json.loads(evidence.context) if evidence.context else {}
        nodes = context.get("nodes") or []
        links = context.get("links") or []
        if lowered_disease is not None:
            node_names = " ".join(str(n.get("name", "")) for n in nodes).lower()
            if lowered_disease not in node_names:
                continue
        paths.append(
            {
                "path_type": "stored_curated",
                "source": "drugmechdb",
                "nodes": nodes,
                "relation_predicates": [link.get("key") for link in links],
                "length": len(links),
                "evidence_summary": {
                    "source": evidence.source,
                    "source_id": evidence.source_id,
                    "evidence_type": evidence.evidence_type,
                    "retrieved_at": evidence.retrieved_at.isoformat(),
                },
            }
        )
    return paths


def _computed_mechanism_paths(session: Session, drug_entity: Entity, disease: str | None, max_hops: int) -> list[dict]:
    """Everything else: a BFS traversal computed at query time (traverse()),
    filtered to mechanism-flagged relations -- explicitly labeled
    "computed_traversal", never presented as a curated path."""
    result = traverse(session, drug_entity.id, _traversal_filters(max_hops=max_hops, predicate=None))
    relations_by_id = {r["id"]: r for r in result["relations"]}
    entities_by_id = {e["id"]: e for e in result["entities"]}
    root_id = str(drug_entity.id)

    disease_entity_id = None
    if disease is not None:
        disease_entity = resolve_entity(session, disease, entity_type="disease")
        if disease_entity is not None:
            disease_entity_id = str(disease_entity.id)

    paths = []
    for entity_id, relation_ids in result["paths"].items():
        if entity_id == root_id or not relation_ids:
            continue
        if disease_entity_id is not None and entity_id != disease_entity_id:
            continue
        path_relations = [relations_by_id[rid] for rid in relation_ids if rid in relations_by_id]
        if not any(_is_mechanism_relation(r) for r in path_relations):
            continue
        # Walk the chain hop by hop: traverse() explores both directions, so
        # the already-known node can be either endpoint of the next relation.
        node_chain = [entities_by_id[root_id]]
        current_id = root_id
        for relation in path_relations:
            next_id = relation["object_id"] if relation["subject_id"] == current_id else relation["subject_id"]
            node_chain.append(entities_by_id[next_id])
            current_id = next_id
        paths.append(
            {
                "path_type": "computed_traversal",
                "nodes": node_chain,
                "relation_ids": relation_ids,
                "predicates": [r["predicate"] for r in path_relations],
                "length": len(path_relations),
                "evidence_summary": [
                    {"source": e.get("source"), "evidence_type": e.get("evidence_type")}
                    for r in path_relations
                    for e in r["evidence"]
                ],
            }
        )
    return paths


def _find_mechanism_paths(session: Session, drug: str, disease: str | None, max_hops: int, limit: int) -> dict[str, Any]:
    drug_entity = _entity_or_error(session, drug, entity_type="drug")
    stored = _stored_mechanism_paths(session, drug_entity, disease)
    computed = _computed_mechanism_paths(session, drug_entity, disease, max_hops)
    combined = (stored + computed)[:limit]
    return {
        "drug": _entity_dict(drug_entity),
        "disease_filter": disease,
        "paths": combined,
        "path_count": len(combined),
        "stored_curated_count": len(stored),
        "computed_traversal_count": len(computed),
    }


def find_mechanism_paths(drug: str, disease: str | None = None, max_hops: int = 4, limit: int = 20) -> dict[str, Any]:
    """Ordered mechanism paths for a drug, clearly distinguishing
    ``path_type: "stored_curated"`` (DrugMechDB's own curated chain,
    preserved exactly as stored) from ``path_type: "computed_traversal"``
    (a BFS path computed at query time) -- never labels a computed
    traversal as curated."""
    max_hops = clamp_hops(max_hops)
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _find_mechanism_paths(session, drug, disease, max_hops, limit)


def _find_combination_treatments(session: Session, drug: str | None, disease: str | None, limit: int) -> dict[str, Any]:
    if drug is not None:
        drug_entity = _entity_or_error(session, drug, entity_type="drug")
        result = traverse(session, drug_entity.id, _traversal_filters(max_hops=1, predicate="has_component"))
        combo_ids = {
            UUID(e["id"]) for e in result["entities"] if e["type"].lower() == "combination_treatment"
        }
        combos = [session.get(Entity, cid) for cid in combo_ids]
    else:
        combos = list(session.exec(select(Entity).where(Entity.type == "combination_treatment")).all())

    def combo_conditions(combo: Entity) -> str:
        trial_rows = session.exec(
            select(Entity)
            .join(Relation, Relation.object_id == Entity.id)
            .where(Relation.subject_id == combo.id, Relation.predicate == "tested_in", Entity.type == "trial")
        ).all()
        return " ".join((t.description or "") + " " + " ".join(_trial_metadata(t).get("conditions") or []) for t in trial_rows).lower()

    if disease is not None:
        lowered = disease.lower()
        combos = [c for c in combos if c is not None and lowered in combo_conditions(c)]

    combos = sorted((c for c in combos if c is not None), key=lambda e: (e.name or "").lower())[:limit]

    results = []
    for combo in combos:
        component_rows = session.exec(
            select(Entity)
            .join(Relation, Relation.object_id == Entity.id)
            .where(Relation.subject_id == combo.id, Relation.predicate == "has_component")
        ).all()
        trial_rows = session.exec(
            select(Entity)
            .join(Relation, Relation.object_id == Entity.id)
            .where(Relation.subject_id == combo.id, Relation.predicate == "tested_in")
        ).all()
        results.append(
            {
                "combination": entity_public_dict(combo),
                "components": [entity_public_dict(c) for c in component_rows],
                "trials": [entity_public_dict(t) for t in trial_rows],
            }
        )

    return {"drug": drug, "disease": disease, "combinations": results, "combination_count": len(results)}


def find_combination_treatments(drug: str | None = None, disease: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Real CombinationTreatment entities (Issue #11, derived from
    ClinicalTrials.gov trials matched to 2+ drugs) with their component
    drugs and the trial(s) they were tested in, optionally filtered by a
    component drug and/or a disease/condition substring on the trial."""
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _find_combination_treatments(session, drug, disease, limit)


_RESPONSE_MODEL_TYPES = frozenset({"cell_line", "pdx", "organoid", "cohort"})


def _find_contextual_response_evidence(
    session: Session, drug: str, disease: str | None, model: str | None, biomarker: str | None, limit: int
) -> dict[str, Any]:
    drug_entity = _entity_or_error(session, drug, entity_type="drug")
    result = traverse(session, drug_entity.id, _traversal_filters(max_hops=2, predicate=None))
    response_relations = [
        r
        for r in result["relations"]
        if any((e.get("evidence_type") or "").startswith("drug_response_") for e in r["evidence"])
    ]

    if model is not None or biomarker is not None:
        entities_by_id = {e["id"]: e for e in result["entities"]}
        lowered_model = model.lower() if model else None
        lowered_biomarker = biomarker.lower() if biomarker else None
        filtered = []
        for relation in response_relations:
            endpoints = [entities_by_id.get(relation["subject_id"]), entities_by_id.get(relation["object_id"])]
            if lowered_model and not any(
                e and e["type"].lower() in _RESPONSE_MODEL_TYPES and lowered_model in (e["name"] or "").lower() for e in endpoints
            ):
                continue
            if lowered_biomarker and not any(
                e and e["type"].lower() == "biomarker" and lowered_biomarker in (e["name"] or "").lower() for e in endpoints
            ):
                continue
            filtered.append(relation)
        response_relations = filtered

    response_relations = response_relations[:limit]
    note = None
    if not response_relations:
        note = (
            "No context-specific drug-response evidence currently exists in the deployed graph for this "
            "query. sources/drug_response.py (Issue #6) is schema/adapter-only -- no real drug-response "
            "dataset is wired into the scheduled pipeline (see docs/DRUG_RESPONSE.md). This is not "
            "evidence of a null or negative result; it means no data has been ingested."
        )

    return {
        "drug": result["root"],
        "disease": disease,
        "model": model,
        "biomarker": biomarker,
        "response_relations": response_relations,
        "response_relation_count": len(response_relations),
        "note": note,
    }


def find_contextual_response_evidence(
    drug: str,
    disease: str | None = None,
    model: str | None = None,
    biomarker: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Context-specific drug-response evidence (identified by a
    drug_response_* evidence_type -- see sources/drug_response.py), optionally
    filtered by experimental model (cell line/PDX/organoid/cohort name
    substring) and/or biomarker name substring. Returns only evidence that
    actually exists; an empty result includes a note explaining why rather
    than a fabricated response label."""
    limit = clamp_limit(limit)
    with session_scope() as session:
        return _find_contextual_response_evidence(session, drug, disease, model, biomarker, limit)
