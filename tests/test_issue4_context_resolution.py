"""Issue #4: Context, Contradictions & Entity Resolution."""

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_edges, import_entities, validate_edge
from oncograph.models import (
    ClaimState,
    Entity,
    EntityResolutionIssue,
    Evidence,
    Relation,
    ResolutionIssueType,
)
from oncograph.normalization import normalize_identifier
from oncograph.sources.base import EdgeRecord, EntityRecord, ExternalIdentifier
from oncograph.sources.hgnc import HGNCAdapter


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed_gene_pair(session: Session) -> None:
    import_entities(
        session,
        [
            EntityRecord(
                entity_type="gene", name="A", identifiers=(ExternalIdentifier("hgnc", "HGNC:1"),)
            ),
            EntityRecord(
                entity_type="disease", name="D", identifiers=(ExternalIdentifier("mondo", "1"),)
            ),
        ],
    )


# --- New identifier namespaces -----------------------------------------------


@pytest.mark.parametrize(
    ("namespace", "value", "expected_namespace", "expected_value"),
    [
        ("ensembl", "ENSG00000146648", "ensembl", "ENSG00000146648"),
        ("ENSG", "ENSG00000146648", "ensembl", "ENSG00000146648"),
        ("uniprot", "P00533", "uniprot", "P00533"),
        ("chembl", "chembl939", "chembl", "CHEMBL939"),
        ("pubchem", "2244", "pubchem", "2244"),
        ("cid", "2244", "pubchem", "2244"),
        ("reactome", "r-hsa-166520", "reactome", "R-HSA-166520"),
        ("go", "go:0000001", "go", "GO:0000001"),
    ],
)
def test_new_namespaces_normalize(namespace, value, expected_namespace, expected_value):
    result = normalize_identifier(ExternalIdentifier(namespace, value))
    assert result.namespace == expected_namespace
    assert result.value == expected_value


# --- Conflicting / context-specific evidence coexistence ---------------------


def test_conflicting_evidence_coexists_without_overwriting():
    with _memory_session() as session:
        _seed_gene_pair(session)
        supports = EdgeRecord(
            subject=ExternalIdentifier("hgnc", "HGNC:1"),
            predicate="associated_with",
            object=ExternalIdentifier("mondo", "1"),
            source_record_id="study-1",
            claim_state="supports",
        )
        contradicts = EdgeRecord(
            subject=ExternalIdentifier("hgnc", "HGNC:1"),
            predicate="associated_with",
            object=ExternalIdentifier("mondo", "1"),
            source_record_id="study-2",
            claim_state="contradicts",
        )
        report = import_edges(session, [supports, contradicts], source_key="lit_review")

        relations = session.exec(select(Relation)).all()
        evidence_rows = session.exec(select(Evidence)).all()

    assert report.edges_created == 1  # one relation
    assert len(relations) == 1
    assert len(evidence_rows) == 2  # two coexisting, non-overwritten evidence rows
    states = {e.claim_state for e in evidence_rows}
    assert states == {ClaimState.SUPPORTS, ClaimState.CONTRADICTS}


def test_context_specific_relations_are_distinct_evidence():
    """Same relation, different biological context -> both evidence rows persist."""
    with _memory_session() as session:
        _seed_gene_pair(session)
        lung_context = EdgeRecord(
            subject=ExternalIdentifier("hgnc", "HGNC:1"),
            predicate="associated_with",
            object=ExternalIdentifier("mondo", "1"),
            source_record_id="cohort-lung",
            context={"tissue": "lung", "cancer_type": "NSCLC"},
            claim_state="context_dependent",
        )
        breast_context = EdgeRecord(
            subject=ExternalIdentifier("hgnc", "HGNC:1"),
            predicate="associated_with",
            object=ExternalIdentifier("mondo", "1"),
            source_record_id="cohort-breast",
            context={"tissue": "breast", "cancer_type": "TNBC"},
            claim_state="context_dependent",
        )
        import_edges(session, [lung_context, breast_context], source_key="cohort_study")

        evidence_rows = session.exec(select(Evidence)).all()

    assert len(evidence_rows) == 2
    contexts = {json.loads(e.context)["tissue"] for e in evidence_rows}
    assert contexts == {"lung", "breast"}
    assert all(e.claim_state == ClaimState.CONTEXT_DEPENDENT for e in evidence_rows)


def test_claim_state_defaults_to_supports_when_unset():
    with _memory_session() as session:
        _seed_gene_pair(session)
        edge = EdgeRecord(
            subject=ExternalIdentifier("hgnc", "HGNC:1"),
            predicate="associated_with",
            object=ExternalIdentifier("mondo", "1"),
            source_record_id="legacy",
        )
        import_edges(session, [edge], source_key="legacy_source")
        evidence = session.exec(select(Evidence)).one()

    assert evidence.claim_state == ClaimState.SUPPORTS


def test_invalid_claim_state_is_rejected():
    edge = EdgeRecord(
        subject=ExternalIdentifier("hgnc", "HGNC:1"),
        predicate="associated_with",
        object=ExternalIdentifier("mondo", "1"),
        claim_state="definitely_true",
    )
    with pytest.raises(ValueError, match="claim_state"):
        validate_edge(edge)


# --- Unresolved mappings / identifier conflicts ------------------------------


def test_unresolved_endpoint_is_logged_as_resolution_issue():
    with _memory_session() as session:
        _seed_gene_pair(session)
        edge = EdgeRecord(
            subject=ExternalIdentifier("hgnc", "HGNC:1"),
            predicate="associated_with",
            object=ExternalIdentifier("mondo", "does-not-exist"),
        )
        report = import_edges(session, [edge], source_key="some_source")
        issues = session.exec(select(EntityResolutionIssue)).all()

    assert report.edges_skipped == 1
    assert len(issues) == 1
    assert issues[0].issue_type == ResolutionIssueType.UNRESOLVED
    assert issues[0].namespace == "mondo"
    assert issues[0].value == "does-not-exist"
    assert issues[0].source == "some_source"


def test_entity_type_conflict_is_logged_and_does_not_overwrite():
    with _memory_session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="gene",
                    name="Original",
                    identifiers=(ExternalIdentifier("hgnc", "HGNC:99"),),
                )
            ],
        )
        conflicting_report = import_entities(
            session,
            [
                EntityRecord(
                    entity_type="disease",
                    name="Conflicting",
                    identifiers=(ExternalIdentifier("hgnc", "HGNC:99"),),
                )
            ],
        )
        entity = session.exec(select(Entity).where(Entity.canonical_id == "hgnc:HGNC:99")).one()
        issues = session.exec(select(EntityResolutionIssue)).all()

    # The original entity's type is authoritative; the conflicting record is
    # rejected rather than silently overwriting it.
    assert entity.type == "gene"
    assert entity.name == "Original"
    assert conflicting_report.entities_conflicted == 1
    assert conflicting_report.entities_updated == 0
    assert len(issues) == 1
    assert issues[0].issue_type == ResolutionIssueType.CONFLICT
    assert issues[0].namespace == "hgnc"
    assert issues[0].value == "HGNC:99"


def test_name_collision_does_not_merge_distinct_entities():
    """Entity resolution is identifier-first: name is an alias, never identity."""
    with _memory_session() as session:
        import_entities(
            session,
            [
                EntityRecord(
                    entity_type="gene", name="Ambiguous", identifiers=(ExternalIdentifier("hgnc", "HGNC:1"),)
                ),
                EntityRecord(
                    entity_type="gene", name="Ambiguous", identifiers=(ExternalIdentifier("hgnc", "HGNC:2"),)
                ),
            ],
        )
        entities = session.exec(select(Entity).where(Entity.name == "Ambiguous")).all()

    assert len(entities) == 2
    assert {e.canonical_id for e in entities} == {"hgnc:HGNC:1", "hgnc:HGNC:2"}


def test_hgnc_adapter_treats_alias_and_prev_symbols_as_aliases(tmp_path):
    tsv_path = tmp_path / "hgnc_complete_set.txt"
    tsv_path.write_text(
        "hgnc_id\tsymbol\tname\tentrez_id\tensembl_gene_id\tuniprot_ids\talias_symbol\tprev_symbol\n"
        "HGNC:3236\tEGFR\tepidermal growth factor receptor\t1956\tENSG00000146648\tP00533\t"
        "ERBB1|HER1\tERBB\n",
        encoding="utf-8",
    )
    adapter = HGNCAdapter(tsv_path, release="2024-01")
    (record,) = list(adapter.iter_entities())

    assert record.metadata["aliases"] == ["ERBB1", "HER1", "ERBB"]
