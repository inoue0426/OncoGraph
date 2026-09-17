"""Issue #7: Graph Query & Reasoning API."""

from uuid import UUID, uuid4

from sqlmodel import Session, SQLModel, create_engine

from oncograph.models import ClaimState, Entity, Evidence, Relation
from oncograph.query import (
    GraphRetriever,
    RetrievalQuery,
    TraversalFilters,
    disease_to_genes_to_drugs,
    resolve_entity,
    traverse,
)


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_graph(session: Session) -> dict[str, str]:
    """Drug -[targets]-> Gene -[associated_with]-> Disease (conflicting evidence),
    plus Drug -[studied_in]-> Trial, and a cited Publication.

    Returns plain string entity IDs (not ORM objects) so callers can use them
    after the session that created them has closed.
    """
    drug = Entity(type="drug", name="ExampleDrug", canonical_id="gtopdb:1")
    gene = Entity(type="gene", name="EXGENE", canonical_id="hgnc:HGNC:1")
    disease = Entity(type="disease", name="ExampleDisease", canonical_id="mondo:1")
    trial = Entity(type="trial", name="Example Trial", canonical_id="clinicaltrials.gov:NCT1")
    publication = Entity(type="paper", name="Example Paper", canonical_id="pubmed:111")
    session.add_all([drug, gene, disease, trial, publication])
    session.flush()

    targets = Relation(subject_id=drug.id, predicate="targets", object_id=gene.id)
    associated = Relation(subject_id=gene.id, predicate="associated_with", object_id=disease.id)
    studied_in = Relation(subject_id=drug.id, predicate="studied_in", object_id=trial.id)
    session.add_all([targets, associated, studied_in])
    session.flush()

    session.add_all(
        [
            Evidence(
                relation_id=targets.id,
                source="gtopdb",
                publication_id=publication.id,
                claim_state=ClaimState.SUPPORTS,
            ),
            Evidence(
                relation_id=associated.id,
                source="open_targets",
                confidence=0.8,
                claim_state=ClaimState.SUPPORTS,
                context='{"score": 0.8}',
            ),
            Evidence(
                relation_id=associated.id,
                source="lit_review",
                claim_state=ClaimState.CONTRADICTS,
                publication_id=publication.id,
            ),
            Evidence(relation_id=studied_in.id, source="clinicaltrials_gov"),
        ]
    )
    session.commit()
    return {
        "drug": str(drug.id),
        "gene": str(gene.id),
        "disease": str(disease.id),
        "trial": str(trial.id),
        "publication": str(publication.id),
    }


# --- resolve_entity ------------------------------------------------------------


def test_resolve_entity_by_uuid_canonical_id_and_name():
    with _memory_session() as session:
        ids = _seed_graph(session)

        by_uuid = resolve_entity(session, ids["drug"])
        by_canonical = resolve_entity(session, "gtopdb:1")
        by_name = resolve_entity(session, "ExampleDrug")
        wrong_type = resolve_entity(session, "gtopdb:1", entity_type="disease")

        assert str(by_uuid.id) == ids["drug"]
        assert str(by_canonical.id) == ids["drug"]
        assert str(by_name.id) == ids["drug"]
        assert wrong_type is None


# --- traverse ------------------------------------------------------------------


def test_traverse_one_hop_reaches_direct_neighbors_only():
    with _memory_session() as session:
        ids = _seed_graph(session)
        result = traverse(session, UUID(ids["drug"]), TraversalFilters(max_hops=1))

    entity_ids = {e["id"] for e in result["entities"]}
    assert entity_ids == {ids["drug"], ids["gene"], ids["trial"]}
    assert ids["disease"] not in entity_ids


def test_traverse_two_hops_reaches_transitive_entity():
    with _memory_session() as session:
        ids = _seed_graph(session)
        result = traverse(session, UUID(ids["drug"]), TraversalFilters(max_hops=2))

    entity_ids = {e["id"] for e in result["entities"]}
    assert ids["disease"] in entity_ids
    path_to_disease = result["paths"][ids["disease"]]
    assert len(path_to_disease) == 2  # drug->gene, gene->disease


def test_traverse_missing_root_returns_none():
    with _memory_session() as session:
        _seed_graph(session)
        assert traverse(session, uuid4(), TraversalFilters()) is None


def test_traverse_filters_by_predicate():
    with _memory_session() as session:
        ids = _seed_graph(session)
        result = traverse(
            session, UUID(ids["drug"]), TraversalFilters(max_hops=2, predicates=frozenset({"targets"}))
        )

    entity_ids = {e["id"] for e in result["entities"]}
    assert ids["trial"] not in entity_ids  # studied_in excluded
    assert ids["gene"] in entity_ids  # targets included


def test_traverse_filters_by_source():
    with _memory_session() as session:
        ids = _seed_graph(session)
        result = traverse(
            session,
            UUID(ids["drug"]),
            TraversalFilters(max_hops=1, sources=frozenset({"clinicaltrials_gov"})),
        )

    entity_ids = {e["id"] for e in result["entities"]}
    assert ids["trial"] in entity_ids
    assert ids["gene"] not in entity_ids  # gtopdb-sourced edge filtered out


def test_traverse_surfaces_contradictory_evidence():
    with _memory_session() as session:
        ids = _seed_graph(session)
        result = traverse(session, UUID(ids["gene"]), TraversalFilters(max_hops=1))

    (relation,) = [r for r in result["relations"] if r["predicate"] == "associated_with"]
    assert relation["has_contradictory_evidence"] is True
    assert len(relation["evidence"]) == 2
    assert relation["publication_ids"] == [ids["publication"]]


def test_traverse_min_confidence_filters_evidence_and_contradiction_flag():
    with _memory_session() as session:
        ids = _seed_graph(session)
        result = traverse(session, UUID(ids["gene"]), TraversalFilters(max_hops=1, min_confidence=0.5))

    (relation,) = [r for r in result["relations"] if r["predicate"] == "associated_with"]
    # Only the confident SUPPORTS row survives the filter; the unscored
    # CONTRADICTS row is excluded, so the flag reflects the filtered view.
    assert len(relation["evidence"]) == 1
    assert relation["has_contradictory_evidence"] is False


def test_traverse_require_publication_follows_only_cited_hops():
    with _memory_session() as session:
        ids = _seed_graph(session)
        result = traverse(
            session, UUID(ids["drug"]), TraversalFilters(max_hops=2, require_publication=True)
        )

    entity_ids = {e["id"] for e in result["entities"]}
    # drug->gene and gene->disease are both publication-cited; drug->trial isn't.
    assert ids["gene"] in entity_ids
    assert ids["disease"] in entity_ids
    assert ids["trial"] not in entity_ids


# --- representative helpers -----------------------------------------------------


def test_disease_to_genes_to_drugs_helper_resolves_by_name():
    with _memory_session() as session:
        ids = _seed_graph(session)
        result = disease_to_genes_to_drugs(session, "ExampleDisease")

    entity_ids = {e["id"] for e in result["entities"]}
    assert ids["drug"] in entity_ids
    assert ids["gene"] in entity_ids


def test_query_helper_returns_none_for_unknown_entity():
    with _memory_session() as session:
        _seed_graph(session)
        assert disease_to_genes_to_drugs(session, "NotARealDisease") is None


# --- retrieval-strategy comparison interface ------------------------------------


def test_graph_retriever_implements_retriever_protocol():
    with _memory_session() as session:
        ids = _seed_graph(session)
        retriever = GraphRetriever(session)
        result = retriever.retrieve(RetrievalQuery(root_ref="ExampleDrug", max_hops=2))

    assert result.root["id"] == ids["drug"]
    entity_ids = {e["id"] for e in result.entities}
    assert ids["disease"] in entity_ids


def test_graph_retriever_unknown_root_returns_empty_result():
    with _memory_session() as session:
        _seed_graph(session)
        retriever = GraphRetriever(session)
        result = retriever.retrieve(RetrievalQuery(root_ref="nope"))

    assert result.root is None
    assert result.entities == []
