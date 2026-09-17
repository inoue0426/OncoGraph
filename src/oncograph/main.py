from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlmodel import Session, select

from . import query as graph_query
from .db import create_db_and_tables, get_session
from .models import Entity, EntityType, Evidence, Relation
from .schemas import EntityCreate, EvidenceCreate, RelationCreate

SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(
    title="OncoGraph API",
    version="0.1.0",
    description="Evidence-first oncology knowledge graph for research use.",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/entities", response_model=list[Entity])
def list_entities(
    session: SessionDep,
    entity_type: EntityType | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Entity]:
    statement = select(Entity)
    if entity_type is not None:
        statement = statement.where(Entity.type == entity_type)
    if q:
        statement = statement.where(Entity.name.ilike(f"%{q}%"))
    return list(session.exec(statement.limit(limit)).all())


@app.post("/entities", response_model=Entity, status_code=201)
def create_entity(payload: EntityCreate, session: SessionDep) -> Entity:
    entity = Entity.model_validate(payload)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity


@app.get("/entities/{entity_id}", response_model=Entity)
def get_entity(entity_id: UUID, session: SessionDep) -> Entity:
    entity = session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(404, "Entity not found")
    return entity


@app.post("/relations", response_model=Relation, status_code=201)
def create_relation(payload: RelationCreate, session: SessionDep) -> Relation:
    if session.get(Entity, payload.subject_id) is None or session.get(Entity, payload.object_id) is None:
        raise HTTPException(400, "Both relation endpoints must exist")
    relation = Relation.model_validate(payload)
    session.add(relation)
    session.commit()
    session.refresh(relation)
    return relation


@app.get("/evidence", response_model=list[Evidence])
def list_evidence(session: SessionDep, relation_id: UUID | None = None) -> list[Evidence]:
    statement = select(Evidence)
    if relation_id is not None:
        statement = statement.where(Evidence.relation_id == relation_id)
    return list(session.exec(statement.limit(200)).all())


@app.post("/evidence", response_model=Evidence, status_code=201)
def create_evidence(payload: EvidenceCreate, session: SessionDep) -> Evidence:
    if session.get(Relation, payload.relation_id) is None:
        raise HTTPException(400, "Relation does not exist")
    evidence = Evidence.model_validate(payload)
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    return evidence


@app.get("/graph/{entity_id}")
def graph(entity_id: UUID, session: SessionDep, depth: Annotated[int, Query(ge=1, le=3)] = 1):
    root = session.get(Entity, entity_id)
    if root is None:
        raise HTTPException(404, "Entity not found")

    entity_ids = {entity_id}
    relations: dict[UUID, Relation] = {}
    frontier = {entity_id}
    for _ in range(depth):
        if not frontier:
            break
        outgoing = session.exec(select(Relation).where(Relation.subject_id.in_(frontier))).all()
        incoming = session.exec(select(Relation).where(Relation.object_id.in_(frontier))).all()
        found = list(outgoing) + list(incoming)
        new_ids: set[UUID] = set()
        for rel in found:
            relations[rel.id] = rel
            new_ids.update((rel.subject_id, rel.object_id))
        frontier = new_ids - entity_ids
        entity_ids.update(new_ids)

    entities = session.exec(select(Entity).where(Entity.id.in_(entity_ids))).all()
    relation_ids = set(relations)
    evidence = (
        session.exec(select(Evidence).where(Evidence.relation_id.in_(relation_ids))).all()
        if relation_ids
        else []
    )
    return {"root": root, "entities": entities, "relations": list(relations.values()), "evidence": evidence}


def _parse_csv(value: str | None) -> frozenset[str] | None:
    if not value:
        return None
    return frozenset(part.strip() for part in value.split(",") if part.strip())


@app.get("/query/traverse")
def query_traverse(
    session: SessionDep,
    ref: str,
    entity_type: EntityType | None = None,
    max_hops: Annotated[int, Query(ge=1, le=5)] = 1,
    predicates: str | None = Query(None, description="Comma-separated predicate names"),
    sources: str | None = Query(None, description="Comma-separated source keys"),
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    require_publication: bool = False,
):
    """Evidence-aware N-hop traversal from an entity referenced by UUID, canonical_id, or name."""
    root = graph_query.resolve_entity(session, ref, entity_type)
    if root is None:
        raise HTTPException(404, "Entity not found")
    result = graph_query.traverse(
        session,
        root.id,
        graph_query.TraversalFilters(
            max_hops=max_hops,
            predicates=_parse_csv(predicates),
            sources=_parse_csv(sources),
            min_confidence=min_confidence,
            require_publication=require_publication,
        ),
    )
    return result


_QUERY_HELPERS = {
    "disease-to-genes-to-drugs": graph_query.disease_to_genes_to_drugs,
    "drug-to-target-to-pathway-to-disease": graph_query.drug_to_target_to_pathway_to_disease,
    "gene-to-pathway-to-disease": graph_query.gene_to_pathway_to_disease,
    "biomarker-to-response-to-drug": graph_query.biomarker_to_response_to_drug,
    "trial-to-disease-to-intervention": graph_query.trial_to_disease_to_intervention,
    "drug-to-publication-supported-disease-path": graph_query.drug_to_publication_supported_disease_path,
}


@app.get("/query/{helper_name}")
def query_helper(helper_name: str, session: SessionDep, ref: str):
    """Representative oncology query helpers -- see docs/QUERY_API.md for the full list."""
    helper = _QUERY_HELPERS.get(helper_name)
    if helper is None:
        raise HTTPException(404, f"Unknown query helper {helper_name!r}")
    result = helper(session, ref)
    if result is None:
        raise HTTPException(404, "Starting entity not found")
    return result
