"""Conservative LINCS identity and bounded persistence regression tests."""

import csv
import json
from dataclasses import replace

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from test_signed_molecular import LINCS_DESCRIPTOR, identities, observation

from oncograph.models import Evidence, Relation
from oncograph.signed_molecular import SignedImportReport, import_signed_observations
from oncograph.sources.lincs_identity import NATIVE_NAMESPACE, compound_resolutions
from oncograph.sources.sigma_sources import LincsConsensusAdapter

KEY = "AAAAAAAAAAAAAA-BBBBBBBBBB-C"
STEREO = "AAAAAAAAAAAAAA-CCCCCCCCCC-C"
OTHER = "DDDDDDDDDDDDDD-BBBBBBBBBB-C"


@pytest.fixture
def session():
    """Provide a clean graph with the production schema."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def metadata(tmp_path, new, old):
    paths = []
    for name, fields, rows in (
        ("new.tsv", ["pert_id", "cmap_name", "inchi_key"], new),
        ("old.tsv", ["pert_id", "pert_iname", "pert_type", "pubchem_cid", "inchi_key"], old),
    ):
        path = tmp_path / name
        with path.open("w") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(fields)
            writer.writerows(rows)
        paths.append(path)
    return compound_resolutions(*paths)


def test_exact_native_and_structure_bridge_are_distinct_strategies(tmp_path):
    mapping, _, _ = metadata(
        tmp_path,
        [("BRD-A", "label-a", KEY), ("BRD-B", "label-b", KEY)],
        [("BRD-A", "label-a", "trt_cp", "123", KEY)],
    )
    assert mapping["BRD-A"].identifier.value == "123"
    assert mapping["BRD-A"].provenance["strategy"] == "native_id_and_full_inchikey"
    assert mapping["BRD-B"].provenance["strategy"] == "full_inchikey"
    # Exact names can describe consensus membership, but cannot establish identity.
    assert mapping["label-a"].identifier.namespace == NATIVE_NAMESPACE
    assert "LABEL-A" not in mapping
    assert mapping["label-a"].provenance["native_perturbagen_ids"] == ["BRD-A"]


@pytest.mark.parametrize(
    "new_key,old_rows",
    [
        (STEREO, [("BRD-A", "same", "trt_cp", "123", KEY)]),
        (
            KEY,
            [("BRD-A", "same", "trt_cp", "123", KEY), ("BRD-B", "other", "trt_cp", "123", STEREO)],
        ),
        (KEY, [("BRD-A", "same", "trt_cp", "123", KEY), ("BRD-B", "other", "trt_cp", "456", KEY)]),
    ],
)
def test_conflicting_stereo_cid_or_metadata_stays_source_native(tmp_path, new_key, old_rows):
    mapping, _, _ = metadata(tmp_path, [("BRD-A", "same", new_key)], old_rows)
    assert mapping["BRD-A"].identifier.namespace == NATIVE_NAMESPACE
    assert mapping["BRD-A"].provenance["metadata_conflict"] is True


def test_names_shared_structures_and_missing_keys_never_force_equivalence(tmp_path):
    mapping, records, _ = metadata(
        tmp_path,
        [("BRD-A", "same", KEY), ("BRD-B", "same", OTHER), ("BRD-C", "unknown", "")],
        [("BRD-D", "same", "trt_cp", "123", KEY)],
    )
    assert mapping["same"].identifier.namespace == NATIVE_NAMESPACE
    assert mapping["same"].provenance["metadata_conflict"]
    assert mapping["BRD-C"].identifier.namespace == NATIVE_NAMESPACE
    assert all(len(record.identifiers) == 1 for record in records)


def test_native_id_collision_with_consensus_label_is_quarantined(tmp_path):
    mapping, _, _ = metadata(
        tmp_path,
        [("BRD-A", "name", KEY), ("BRD-B", "BRD-A", OTHER)],
        [("BRD-A", "name", "trt_cp", "123", KEY)],
    )
    assert mapping["BRD-A"].identifier.namespace == NATIVE_NAMESPACE
    assert mapping["BRD-A"].provenance["metadata_conflict"]
    assert mapping["BRD-A"].provenance["native_perturbagen_ids"] == ["BRD-A", "BRD-B"]


def test_native_preservation_sign_raw_score_and_source_record(tmp_path, session):
    mapping, compounds, _ = metadata(tmp_path, [("BRD-A", "label", "")], [])
    path = tmp_path / "edges.tsv"
    path.write_text(
        "\tGene\tGene ID\tChemical Perturbation\tZ-score\tThreshold Value\n"
        "row-1\tGENE\t2\tBRD-A\t4.25\t1\n"
        "row-2\tGENE\t2\tBRD-A\t-3.5\t-1\n"
    )
    crosswalk = identities(session)
    crosswalk.register(compounds)
    adapter = LincsConsensusAdapter(
        path, {}, release="fixture", mapping_sha256="frozen", compound_resolutions=mapping
    )
    for attempt in range(2):
        report = import_signed_observations(
            session, adapter.iter_edges(), adapter.descriptor, crosswalk, adapter.report
        )
        assert report.mapped_records == 2
        assert report.evidence_created == (2 if attempt == 0 else 0)
        assert report.duplicate_evidence == (0 if attempt == 0 else 2)
    assert {r.predicate for r in session.exec(select(Relation))} == {"upregulates", "downregulates"}
    evidence = session.exec(select(Evidence)).all()
    contexts = [json.loads(item.context) for item in evidence]
    assert {c["original_score"] for c in contexts} == {4.25, -3.5}
    assert {c["original_source_record_id"] for c in contexts} == {"row-1", "row-2"}
    assert all(c["source_gene_id"] == "2" and c["experimental_context"] is None for c in contexts)
    assert all(item.confidence is None for item in evidence)


def test_batch_boundaries_duplicates_context_and_reimport(session):
    crosswalk = identities(session)
    rows = [
        replace(observation(context={"cell_line": f"cell-{i}"}), source_record_id=str(i))
        for i in range(601)
    ]
    rows += [rows[0], rows[250], rows[-1]]
    for attempt in range(2):
        report = import_signed_observations(
            session, iter(rows), LINCS_DESCRIPTOR, crosswalk, SignedImportReport()
        )
        assert report.relations_created == (1 if attempt == 0 else 0)
        assert report.evidence_created == (601 if attempt == 0 else 0)
        assert report.duplicate_evidence == (3 if attempt == 0 else 604)
    assert len(session.exec(select(Evidence)).all()) == 601


def test_late_parser_failure_rolls_back_flushed_batches(session):
    crosswalk = identities(session)

    def broken_rows():
        for i in range(300):
            yield replace(observation(), source_record_id=str(i))
        raise ValueError("broken source")

    with pytest.raises(ValueError, match="broken source"):
        import_signed_observations(
            session, broken_rows(), LINCS_DESCRIPTOR, crosswalk, SignedImportReport()
        )
    assert session.exec(select(Relation)).all() == []
    assert session.exec(select(Evidence)).all() == []


def test_queries_keep_downstream_responses_separate_from_existing_targets(session):
    from oncograph.signed_molecular import signed_compounds, signed_effects
    from oncograph.sources.base import ExternalIdentifier

    crosswalk = identities(session)
    drug, _ = crosswalk.resolve(ExternalIdentifier("pubchem", "1"), "drug", None)
    gene, _ = crosswalk.resolve(ExternalIdentifier("ncbigene", "2"), "gene", 9606)
    direct = Relation(subject_id=drug, predicate="targets", object_id=gene)
    session.add(direct)
    session.commit()
    direct_id = direct.id
    rows = [observation(), observation("downregulates")]
    import_signed_observations(session, rows, LINCS_DESCRIPTOR, crosswalk, SignedImportReport())
    forward = signed_effects(session, drug)
    reverse = signed_compounds(session, gene)
    assert {r["source_id"] for r in forward} == {r["source_id"] for r in reverse}
    assert all(r["opposite_direction_observed"] for r in forward + reverse)
    assert all(r["predicate"] != "targets" for r in forward + reverse)
    assert session.get(Relation, direct_id).predicate == "targets"


def test_existing_duplicate_relationship_identity_is_not_arbitrarily_selected(session):
    from oncograph.sources.base import ExternalIdentifier

    crosswalk = identities(session)
    drug, _ = crosswalk.resolve(ExternalIdentifier("pubchem", "1"), "drug", None)
    gene, _ = crosswalk.resolve(ExternalIdentifier("ncbigene", "2"), "gene", 9606)
    session.add_all(
        [Relation(subject_id=drug, predicate="upregulates", object_id=gene) for _ in range(2)]
    )
    session.commit()
    with pytest.raises(ValueError, match="Ambiguous existing relation identity"):
        import_signed_observations(
            session, [observation()], LINCS_DESCRIPTOR, crosswalk, SignedImportReport()
        )
    assert session.exec(select(Evidence)).all() == []


def test_audit_and_public_comparison_count_evidence_without_conflating_targets(tmp_path):
    import runpy
    from pathlib import Path

    from oncograph.sources.sigma_sources import LINCS_DESCRIPTOR as SOURCE_DESCRIPTOR

    database = tmp_path / "graph.sqlite"
    engine = create_engine(f"sqlite:///{database}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        crosswalk = identities(session)
        rows = [
            observation(),
            observation("downregulates"),
            replace(observation(), source_record_id="independent-row"),
        ]
        import_signed_observations(
            session, rows, SOURCE_DESCRIPTOR, crosswalk, SignedImportReport()
        )
    engine.dispose()
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    audit = runpy.run_path(str(scripts / "audit_lincs_import.py"))["audit_database"](database)
    assert audit["signed_relations"] == 2
    assert audit["evidence_records"] == 3
    assert audit["opposite_sign_pairs"] == 1
    assert audit["endpoint_type_violations"] == audit["gene_taxon_violations"] == 0
    entities = tmp_path / "entities.json"
    relations = tmp_path / "relations.json"
    entities.write_text(
        json.dumps(
            [
                {"id": "drug", "type": "DRUG", "canonical_id": "gtopdb:1"},
                {"id": "gene", "type": "GENE", "canonical_id": "hgnc:HGNC:2"},
                {"id": "protein", "type": "PROTEIN", "canonical_id": "uniprot:P00002"},
            ]
        )
    )
    relations.write_text(
        json.dumps(
            [
                {
                    "subject_id": "drug",
                    "predicate": "targets",
                    "object_id": "gene",
                    "evidence": [{"source": "fixture"}],
                },
                {
                    "subject_id": "drug",
                    "predicate": "targets",
                    "object_id": "protein",
                    "evidence": [{"source": "fixture"}],
                },
            ]
        )
    )
    ligands = tmp_path / "ligands.csv"
    ligands.write_text(
        "# GtoPdb Version: fixture\nType,Ligand id,Name,PubChem CID,ChEMBl ID,DrugBank ID\n"
        "Synthetic organic,1,Not used for matching,1,CHEMBL1,\n"
    )
    comparison = runpy.run_path(str(scripts / "compare_lincs_graph.py"))["compare_graph"](
        database, entities, relations, ligands
    )
    assert comparison["target_overlap"]["unique_local_drug_gene_pairs"] == 1
    assert comparison["target_overlap"]["public_drug_gene_target_relations"] == 1
    assert comparison["public_pathway_entities"] == 0


def test_native_identifier_is_source_scoped_and_gene_protein_roles_stay_separate(session):
    from oncograph.sources.base import EntityRecord, ExternalIdentifier

    crosswalk = identities(session)
    crosswalk.register(
        [
            EntityRecord("drug", "Same name", (ExternalIdentifier("other_source", "BRD-A"),)),
            EntityRecord("drug", "Same name", (ExternalIdentifier(NATIVE_NAMESPACE, "BRD-A"),)),
        ]
    )
    native, _ = crosswalk.resolve(ExternalIdentifier(NATIVE_NAMESPACE, "BRD-A"), "drug", None)
    other, _ = crosswalk.resolve(ExternalIdentifier("other_source", "BRD-A"), "drug", None)
    assert native != other
    assert (
        crosswalk.resolve(ExternalIdentifier("uniprot", "P00002"), "gene", 9606)[1] == "conflicting"
    )
    assert crosswalk.resolve(ExternalIdentifier("ncbigene", "2"), "gene", 10090)[1] == "conflicting"
    assert crosswalk.resolve(ExternalIdentifier("ncbigene", "999"), "gene", 9606)[1] == "unmatched"


def test_source_audit_distinguishes_row_identity_duplicates_and_opposite_signs(tmp_path):
    import runpy
    from pathlib import Path

    path = tmp_path / "edges.tsv"
    path.write_text(
        "\tGene\tGene ID\tChemical Perturbation\tZ-score\tThreshold Value\n"
        "1\tGENE\t2\tBRD-A\t3.2\t1\n"
        "2\tGENE\t2\tBRD-A\t3.2\t1\n"
        "1\tGENE\t2\tBRD-A\t-3.4\t-1\n"
        "4\tGENE\t2\tBRD-A\t3.2\t-1\n"
    )
    module = Path(__file__).resolve().parents[1] / "scripts/audit_lincs_import.py"
    result = runpy.run_path(str(module))["audit_source"](path)
    assert result["original_records"] == 4
    assert result["valid_records"] == 3
    assert result["invalid_records"] == 1
    assert result["repeated_record_ids"] == 1
    assert result["duplicate_observations_ignoring_row_id"] == 1
    assert result["opposite_sign_native_compound_gene_pairs"] == 1
