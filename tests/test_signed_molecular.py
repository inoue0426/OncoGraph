"""Scientific identity, polarity, provenance and idempotency regression tests."""

import json
from dataclasses import replace

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.models import Entity, EntityIdentifier, Evidence, Relation
from oncograph.signed_molecular import (
    SIGNED_RELATIONS,
    SignedImportReport,
    TypedCrosswalk,
    import_signed_observations,
    signed_effects,
)
from oncograph.sources.base import EdgeRecord, EntityRecord, ExternalIdentifier, SourceDescriptor

LINCS_DESCRIPTOR = SourceDescriptor(
    key="test_signed_source",
    name="Synthetic test source",
    homepage="https://example.org",
    license="Synthetic test fixture",
)


def eid(namespace, value):
    return ExternalIdentifier(namespace, value)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def identities(session):
    crosswalk = TypedCrosswalk(session)
    crosswalk.register(
        [
            EntityRecord("drug", "Drug", (eid("chembl", "CHEMBL1"), eid("pubchem", "1"))),
            EntityRecord(
                "gene",
                "Gene",
                (eid("hgnc", "HGNC:2"), eid("ncbigene", "2"), eid("ensembl", "ENSG2")),
                metadata={"taxon_id": 9606},
            ),
            EntityRecord(
                "protein", "Protein", (eid("uniprot", "P00002"),), metadata={"taxon_id": 9606}
            ),
            EntityRecord("disease", "Disease", (eid("mondo", "0000001"),)),
        ]
    )
    return crosswalk


def observation(predicate="upregulates", context=None):
    spec = SIGNED_RELATIONS[predicate]
    endpoints = {
        "drug": eid("pubchem", "1"),
        "gene": eid("ncbigene", "2"),
        "protein": eid("uniprot", "P00002"),
        "disease": eid("mondo", "0000001"),
    }
    return EdgeRecord(
        endpoints[spec[0]],
        predicate,
        endpoints[spec[1]],
        source_record_id="row-1",
        context={
            "original_source_dataset": "synthetic test",
            "release": "test-v1",
            "file_sha256": "test-digest",
            "original_predicate": predicate,
            "effect_sign": spec[2],
            "biological_relationship": spec[3],
            "observation_status": "transformed",
            "model_generated": False,
            "taxon_id": 9606,
            **(context or {}),
        },
    )


def ingest(session, crosswalk, records):
    return import_signed_observations(
        session, records, LINCS_DESCRIPTOR, crosswalk, SignedImportReport()
    )


@pytest.mark.parametrize("predicate", SIGNED_RELATIONS)
def test_all_signed_families_are_typed_and_directed(session, predicate):
    crosswalk = identities(session)
    report = ingest(session, crosswalk, [observation(predicate)])
    assert report.relations_created == report.evidence_created == 1
    relation = session.exec(select(Relation)).one()
    spec = SIGNED_RELATIONS[predicate]
    assert session.get(Entity, relation.subject_id).type == spec[0]
    assert session.get(Entity, relation.object_id).type == spec[1]
    evidence = session.exec(select(Evidence)).one()
    assert evidence.evidence_type == spec[3]
    assert json.loads(evidence.context)["effect_sign"] == spec[2]
    assert evidence.confidence is None


def test_context_conflicts_independent_sources_and_reimport(session):
    crosswalk = identities(session)
    up = observation(context={"cell_line": "A", "dose": "10 nM"})
    other_context = observation(context={"cell_line": "B"})
    down = observation("downregulates", {"cell_line": "A"})
    records = [up, up, other_context, down]
    report = ingest(session, crosswalk, records)
    assert (report.relations_created, report.evidence_created, report.duplicate_evidence) == (
        2,
        3,
        1,
    )
    assert report.duplicate_relationships == 2
    again = ingest(session, TypedCrosswalk(session), records)
    assert again.relations_created == again.evidence_created == 0
    assert again.duplicate_evidence == 4
    import_signed_observations(
        session,
        [up],
        replace(LINCS_DESCRIPTOR, key="independent_source"),
        crosswalk,
        SignedImportReport(),
    )
    assert len(session.exec(select(Evidence)).all()) == 4
    drug, _ = crosswalk.resolve(eid("pubchem", "1"), "drug", None)
    results = signed_effects(session, drug)
    assert len(results) == 4
    assert all(r["opposite_direction_observed"] for r in results)
    assert any(r["context"].get("cell_line") == "B" for r in results)


@pytest.mark.parametrize(
    "context",
    [
        {"effect_sign": -1},
        {"biological_relationship": "binding"},
        {"model_generated": True},
        {"release": None},
        {"observation_status": "prediction"},
    ],
)
def test_invalid_contract_or_predictions_not_imported(session, context):
    report = ingest(session, identities(session), [observation(context=context)])
    assert report.skipped["invalid_signed_contract"] == 1
    assert not session.exec(select(Evidence)).all()


def test_gene_protein_and_species_conflicts_rejected(session):
    crosswalk = identities(session)
    bad = replace(observation("activates"), object=eid("ncbigene", "2"))
    wrong_species = observation(context={"taxon_id": 10090})
    report = ingest(session, crosswalk, [bad, wrong_species])
    assert report.skipped["unresolved_or_conflicting_endpoint"] == 2
    assert report.relations_created == 0
    assert "conflicting" in {item["status"] for item in report.identifiers.values()}


def test_canonical_collision_does_not_override_alternate_claim(session):
    crosswalk = identities(session)
    drug, _ = crosswalk.resolve(eid("pubchem", "1"), "drug", None)
    other = Entity(type="drug", name="Other", canonical_id="pubchem:1")
    session.add(other)
    session.commit()
    assert crosswalk.entities[drug].canonical_id == "chembl:CHEMBL1"
    assert TypedCrosswalk(session).resolve(eid("pubchem", "1"), "drug", None)[1] == "ambiguous"


def test_unknown_species_and_legacy_uniprot_gene_alias_rejected(session):
    gene = Entity(type="gene", name="Legacy", canonical_id="ncbigene:2")
    session.add(gene)
    session.flush()
    session.add(EntityIdentifier(entity_id=gene.id, namespace="uniprot", value="P00002"))
    session.commit()
    crosswalk = TypedCrosswalk(session)
    assert crosswalk.resolve(eid("ncbigene", "2"), "gene", 9606)[1] == "conflicting"
    report = crosswalk.register(
        [
            EntityRecord(
                "protein", "Product", (eid("uniprot", "P00002"),), metadata={"taxon_id": 9606}
            )
        ]
    )
    assert report["conflicting"] == 1
    assert len(session.exec(select(Entity)).all()) == 1


def test_registration_never_merges_by_name_and_crosswalk_is_idempotent(session):
    records = [EntityRecord("drug", "Same name", (eid("pubchem", str(i)),)) for i in (1, 2)]
    index = TypedCrosswalk(session)
    assert index.register(records)["created"] == 2
    assert TypedCrosswalk(session).register(records).get("created", 0) == 0
    assert len(session.exec(select(EntityIdentifier)).all()) == 2


def test_conflicting_mapping_batch_is_order_independent(session):
    records = [
        EntityRecord("drug", str(i), (eid("gtopdb", str(i)), eid("pubchem", "1"))) for i in (1, 2)
    ]
    assert TypedCrosswalk(session).register(records)["ambiguous"] == 2
    assert TypedCrosswalk(session).register(reversed(records))["ambiguous"] == 2
    assert session.exec(select(Entity)).all() == []


def test_native_confidence_changes_are_preserved(session):
    crosswalk = identities(session)
    records = [replace(observation(), confidence=score) for score in (0.5, 0.7)]
    report = ingest(session, crosswalk, records)
    assert report.relations_created == 1 and report.evidence_created == 2
    assert {e.confidence for e in session.exec(select(Evidence))} == {0.5, 0.7}
    assert ingest(session, crosswalk, records).evidence_created == 0


def test_conflicting_evidence_family_not_reinterpreted(session):
    record = replace(observation(), evidence_type="direct_binding")
    assert ingest(session, identities(session), [record]).skipped["invalid_signed_contract"] == 1
