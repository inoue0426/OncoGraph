"""Focused tests for the permission-gated, human Lewis Lab adapters."""

import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_edges, import_entities, validate_edge
from oncograph.models import Entity, Evidence, Relation
from oncograph.sources.base import EdgeRecord, EntityRecord, ExternalIdentifier
from oncograph.sources.lewis_lab import (
    HUMAN_TAXON,
    LewisBrowaeysAdapter,
    LewisCabelloAguilarAdapter,
    LewisDelimitedAdapter,
    LewisDimitrovAdapter,
    LewisHouAdapter,
    LewisJinAdapter,
    LewisMetSensorAdapter,
    LewisNoelAdapter,
    LewisPavlicevAdapter,
    LewisQiaoAdapter,
    LewisRamilowskiAdapter,
    LewisResolvedIdentifier,
    LewisShaoAdapter,
    LewisSourceProfile,
    LewisWangAdapter,
    LewisZhaoAdapter,
    load_identifier_map,
)

VALIDATOR = Path(__file__).resolve().parents[1] / "scripts" / "validate_lewis_source.py"
validator_spec = importlib.util.spec_from_file_location("validate_lewis_source", VALIDATOR)
validator = importlib.util.module_from_spec(validator_spec)
assert validator_spec.loader is not None
validator_spec.loader.exec_module(validator)


def _map(*rows):
    return {(HUMAN_TAXON, symbol): (LewisResolvedIdentifier(identifier, entity_type),)
            for symbol, identifier, entity_type in rows}


def test_ramilowski_parser_requires_explicit_human_symbol_map(tmp_path):
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    path.write_text(
        "Pair.Name\tLigand.ApprovedSymbol\tLigand.Name\tReceptor.ApprovedSymbol\t"
        "Receptor.Name\tPMID.Manual\tPair.Evidence\n"
        "A2M_LRP1\tA2M\talpha-2-macroglobulin\tLRP1\tLRP1\t16630822\tliterature supported\n"
        "A2M_LRP1\tA2M\talpha-2-macroglobulin\tLRP1\tLRP1\t16630822\tliterature supported\n"
        "BAD\tUNKNOWN\tunknown\tLRP1\tLRP1\t\t\n",
        encoding="utf-8",
    )
    adapter = LewisRamilowskiAdapter(
        path,
        _map(
            ("A2M", ExternalIdentifier("hgnc", "HGNC:7"), "gene"),
            ("LRP1", ExternalIdentifier("hgnc", "HGNC:6692"), "gene"),
        ),
        release="audit-fixture",
    )
    edges = list(adapter.iter_edges())
    report = adapter.validation_report()
    assert len(edges) == 1
    assert report.input_rows == 3
    assert report.duplicate_rows == 1
    assert report.unresolved_identifiers == 1
    assert report.unresolved_values == ["UNKNOWN"]
    assert report.to_dict()["valid"] is False
    assert edges[0].source_record_id.startswith("lewis_ramilowski_2015:v2:")
    assert edges[0].context["upstream_record_id"] == "A2M_LRP1"
    assert edges[0].context["taxon_id"] == HUMAN_TAXON
    assert edges[0].context["source_ligand"] == "A2M"
    assert edges[0].context["source_receptor"] == "LRP1"
    assert edges[0].context["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_validation_command_writes_source_report_without_database(tmp_path, monkeypatch):
    source_path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    source_path.write_text(
        "Pair.Name\tLigand.ApprovedSymbol\tReceptor.ApprovedSymbol\n"
        "A2M_LRP1\tA2M\tLRP1\n",
        encoding="utf-8",
    )
    map_path = tmp_path / "human-symbol-map.tsv"
    map_path.write_text(
        "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\n"
        "9606\tA2M\thgnc\tHGNC:7\tgene\n"
        "9606\tLRP1\thgnc\tHGNC:6692\tgene\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "validation.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_lewis_source.py",
            "lewis_ramilowski_2015",
            str(source_path),
            "--identifier-map",
            str(map_path),
            "--out",
            str(report_path),
        ],
    )
    validator.main()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["valid"] is True
    assert report["input_rows"] == 1
    assert report["entities_emitted"] == 2
    assert report["edges_emitted"] == 1
    assert report["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert report["identifier_map_sha256"] == hashlib.sha256(map_path.read_bytes()).hexdigest()
    assert report["taxon_id"] == HUMAN_TAXON

    monkeypatch.setattr(sys, "argv", [
        "validate_lewis_source.py", "lewis_ramilowski_2015", str(source_path),
        "--identifier-map", str(map_path), "--out", str(source_path),
    ])
    original = source_path.read_bytes()
    with pytest.raises(SystemExit) as error:
        validator.main()
    assert error.value.code == 2
    assert source_path.read_bytes() == original


@pytest.mark.parametrize("failure", ["quarantined", "schema", "mapping", "missing", "changed"])
def test_validation_failure_replaces_stale_success_report(tmp_path, monkeypatch, failure):
    """Failed validation must leave an explicit current report, never stale success."""
    source_path = tmp_path / LewisJinAdapter.profile.filename
    source_path.write_text("ligand_symbol,receptor_symbol,evidence\nA,A,fixture\n")
    map_path = tmp_path / "map.tsv"
    map_path.write_text(
        "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\n9606\tA\thgnc\tHGNC:1\tgene\n"
    )
    report_path = tmp_path / "report.json"
    report_path.write_text('{"valid": true, "obsolete": true}\n')
    if failure == "quarantined":
        source_path.write_text("ligand_symbol,receptor_symbol\nA,H2-T23\n")
    elif failure == "schema":
        source_path.write_text("wrong,columns\nA,A\n")
    elif failure == "mapping":
        map_path.write_text("wrong\nvalue\n")
    elif failure == "missing":
        source_path.unlink()
    elif failure == "changed":
        original_hash = validator.file_sha256
        calls = 0

        def changing_hash(path):
            nonlocal calls
            calls += 1
            return "changed" if calls > 2 else original_hash(path)

        monkeypatch.setattr(validator, "file_sha256", changing_hash)
    monkeypatch.setattr(sys, "argv", [
        "validate_lewis_source.py", "lewis_jin_2020", str(source_path),
        "--identifier-map", str(map_path), "--out", str(report_path),
    ])
    with pytest.raises(SystemExit) as error:
        validator.main()
    assert error.value.code == 1
    payload = json.loads(report_path.read_text())
    assert payload["valid"] is False
    assert payload["status"] == "validation_failed"
    assert payload["errors"]
    assert payload["entities_emitted"] == payload["edges_emitted"] == 0
    assert "obsolete" not in payload
    if failure != "missing":
        assert payload["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()


def test_validation_runs_ingestion_record_checks(tmp_path, monkeypatch):
    """Record validation must catch a parser emitting an invalid self association."""
    source_path = tmp_path / LewisMetSensorAdapter.profile.filename
    source_path.write_text("HMDB_ID\tGene_name\nHMDB0000001\tA\n")
    map_path = tmp_path / "map.tsv"
    map_path.write_text(
        "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\n"
        "9606\tHMDB0000001\thmdb\tHMDB0000001\tmetabolite\n"
        "9606\tA\thgnc\tHGNC:1\tgene\n"
    )
    report_path = tmp_path / "report.json"
    # Inject an invalid emitted edge to exercise the command's importer contract.
    invalid_edge = EdgeRecord(
        subject=ExternalIdentifier("hgnc", "HGNC:1"),
        object=ExternalIdentifier("hgnc", "HGNC:1"), predicate="metabolite_target_association",
    )
    monkeypatch.setattr(LewisMetSensorAdapter, "iter_edges", lambda self: iter([invalid_edge]))
    monkeypatch.setattr(sys, "argv", [
        "validate_lewis_source.py", "lewis_zheng_2022", str(source_path),
        "--identifier-map", str(map_path), "--out", str(report_path),
    ])
    with pytest.raises(SystemExit) as error:
        validator.main()
    assert error.value.code == 1
    payload = json.loads(report_path.read_text())
    assert payload["valid"] is False
    assert any("Self edges" in message for message in payload["errors"])


def test_distinct_evidence_survives_reused_pair_ids_and_row_reordering(tmp_path):
    """Preserve separate citations and source evidence on the same relation."""
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    header = "Pair.Name\tLigand.ApprovedSymbol\tReceptor.ApprovedSymbol\tPMID.Manual\tPair.Evidence\n"
    rows = ["pair\tA\tB\t1\tsource-a\n", "pair\tA\tB\t2\tsource-a\n",
            "pair\tA\tB\t1\tsource-b\n"]
    mapping = _map(("A", ExternalIdentifier("hgnc", "HGNC:1"), "gene"),
                   ("B", ExternalIdentifier("hgnc", "HGNC:2"), "gene"))
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for index, ordered in enumerate((rows + rows, list(reversed(rows)))):
            path.write_text(header + "".join(ordered), encoding="utf-8")
            adapter = LewisRamilowskiAdapter(path, mapping, release="fixture")
            result = import_adapter(session, adapter)
            assert result.evidence_created == (3 if index == 0 else 0)
        assert len(session.exec(select(Relation)).all()) == 1
        evidence = session.exec(select(Evidence)).all()
        assert len(evidence) == 3
        assert {(json.loads(item.context)["citation"], json.loads(item.context)["source_evidence"])
                for item in evidence} == {("1", "source-a"), ("2", "source-a"), ("1", "source-b")}


def test_source_profile_rejects_wrong_file_name(tmp_path):
    path = tmp_path / "renamed.txt"
    path.write_text("ligand\treceptor\nA\tB\n", encoding="utf-8")
    adapter = LewisRamilowskiAdapter(path, {})
    try:
        list(adapter.iter_edges())
    except ValueError as exc:
        assert "Human-2015-Ramilowski-LR-pairs.txt" in str(exc)
    else:
        raise AssertionError("wrong source file name was accepted")


def test_nonhuman_profile_is_rejected():
    class MouseProfileAdapter(LewisDelimitedAdapter):
        profile = LewisSourceProfile(
            source_key="mouse_fixture",
            filename="mouse.tsv",
            species="Mus musculus",
            taxon_id=10090,
            delimiter="\t",
            ligand_column="ligand",
            receptor_column="receptor",
        )

    with pytest.raises(ValueError, match="human taxon 9606"):
        MouseProfileAdapter("mouse.tsv", {})


@pytest.mark.parametrize("content", [
    "taxon_id\tsymbol\tnamespace\tidentifier\n9606\tA\tuniprot\tP00001\n",
    "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\n9606\tA\tuniprot\tP00001\t\n",
    "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\n9606\tA\tuniprot\tP00001\n",
])
def test_identifier_map_never_infers_gene_type_for_incomplete_rows(tmp_path, content):
    """A missing molecular type must not silently turn a protein into a gene."""
    path = tmp_path / "map.tsv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns|empty required field"):
        load_identifier_map(path)


@pytest.mark.parametrize("reverse", [False, True])
def test_mapping_type_conflicts_across_symbols_fail_before_import(reverse):
    """Normalized identity collisions must not depend on symbol insertion order."""
    rows = [
        ("A", ExternalIdentifier("uniprot", "P00001"), "gene"),
        ("B", ExternalIdentifier("uniprotkb", "P00001"), "protein"),
    ]
    if reverse:
        rows.reverse()
    with pytest.raises(ValueError, match="Conflicting entity types"):
        LewisRamilowskiAdapter("unused.txt", _map(*rows))


def test_equivalent_mapping_spellings_deduplicate_without_false_ambiguity(tmp_path):
    """Namespace aliases denote the same identifier, not competing candidates."""
    path = tmp_path / LewisRamilowskiAdapter.profile.filename
    path.write_text(
        "Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\nA\tB\n", encoding="utf-8",
    )
    mapping = {
        (9606, " a "): (LewisResolvedIdentifier(ExternalIdentifier("uniprot", "P00001"), "protein"),),
        (9606, "A"): (LewisResolvedIdentifier(ExternalIdentifier("uniprotkb", "P00001"), "protein"),),
        (9606, "B"): (LewisResolvedIdentifier(ExternalIdentifier("uniprot", "P00002"), "protein"),),
    }
    adapter = LewisRamilowskiAdapter(path, mapping)
    edges = list(adapter.iter_edges())
    assert len(edges) == 1
    assert edges[0].subject == ExternalIdentifier("uniprot", "P00001")
    assert adapter.validation_report().valid is True
    mapping[(9606, " a ")] = (
        LewisResolvedIdentifier(ExternalIdentifier("uniprot", "P00003"), "protein"),
    )
    ambiguous = LewisRamilowskiAdapter(path, mapping)
    assert list(ambiguous.iter_edges()) == []
    assert ambiguous.validation_report().ambiguous_identifiers == 1


@pytest.mark.parametrize("content, message", [
    ("", "missing required columns"),
    ("wrong\theader\n", "missing required columns"),
    ("Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\n", "no data rows"),
    (("Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\tReceptor.ApprovedSymbol\n"
      "A\tB\tC\n"), "duplicate column names"),
])
def test_invalid_source_headers_never_report_valid(tmp_path, content, message):
    """Reject truncated or ambiguous schemas before resolving any rows."""
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    path.write_text(content, encoding="utf-8")
    adapter = LewisRamilowskiAdapter(path, {})
    with pytest.raises(ValueError, match=message):
        adapter.validation_report()


def test_missing_complex_component_column_cannot_shrink_complex(tmp_path):
    """A missing column is not equivalent to a blank optional subunit cell."""
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / LewisNoelAdapter.profile.filename
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "All"
    sheet.append(["Ligand 1", "Ligand 2", "Receptor 1", "Receptor 2"])
    sheet.append(["A", None, "B", None])
    workbook.save(path)
    adapter = LewisNoelAdapter(path, {})
    with pytest.raises(ValueError, match="Receptor 3"):
        list(adapter.iter_entities())


def test_parse_failure_remains_failure_for_every_public_accessor(tmp_path):
    """A failed read must not become an empty, valid cached import."""
    adapter = LewisRamilowskiAdapter(tmp_path / "renamed.txt", {})
    for accessor in (
        adapter.iter_entities, adapter.iter_edges, adapter.validation_report,
        adapter.iter_entities,
    ):
        with pytest.raises(ValueError, match="Expected"):
            accessor()


def test_cabello_parser_preserves_source_evidence(tmp_path):
    path = tmp_path / "Human-2020-Cabello-Aguilar-LR-pairs.csv"
    path.write_text(
        "ligand,receptor,source,PMIDs\nTGFB1,TGFBR1,HPRD,12809600\n",
        encoding="utf-8",
    )
    adapter = LewisCabelloAguilarAdapter(
        path,
        _map(
            ("TGFB1", ExternalIdentifier("hgnc", "HGNC:11766"), "gene"),
            ("TGFBR1", ExternalIdentifier("hgnc", "HGNC:11772"), "gene"),
        ),
    )
    edge = next(adapter.iter_edges())
    assert edge.context["source_evidence"] == "HPRD"
    assert edge.context["citation"] == "12809600"
    assert edge.context["interaction_mode"] == "compiled_prior"
    assert edge.evidence_type == "compiled_ligand_receptor"
    assert edge.context["source_reference"] == "https://doi.org/10.1093/nar/gkaa183"
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        assert import_adapter(session, adapter).errors == []
        evidence = session.exec(select(Evidence)).one()
        context = json.loads(evidence.context)
        assert context["citation"] == "12809600"
        assert context["source_reference"] == adapter.descriptor.citation
        assert evidence.source_url == adapter.descriptor.homepage
        assert evidence.publication_id is None
        assert import_adapter(session, adapter).evidence_created == 0
    engine.dispose()


def test_zhao_parser_preserves_interaction_type(tmp_path):
    path = tmp_path / "Human-2023-Zhao-LR-pairs.tsv"
    path.write_text(
        "interaction_name\tligand_type\tinteraction_type\tlig_contributor\ttarget_subunit\n"
        "VIP_VIPR1\tNeuropeptide\tligand-receptor\tVIP\tVIPR1\n",
        encoding="utf-8",
    )
    adapter = LewisZhaoAdapter(
        path,
        _map(
            ("VIP", ExternalIdentifier("hgnc", "HGNC:12690"), "gene"),
            ("VIPR1", ExternalIdentifier("hgnc", "HGNC:12694"), "gene"),
        ),
    )
    for accessor in (adapter.iter_edges, adapter.iter_entities, adapter.validation_report):
        with pytest.raises(ValueError, match="NeuronChat import is disabled"):
            accessor()


def test_metsensor_is_not_labeled_as_protein_ligand_receptor(tmp_path):
    path = tmp_path / "Human-2022-Zheng-MetSensor-pairs.tsv"
    path.write_text(
        "HMDB_ID\tstandard_metName\tmetName\tGene_name\tProtein_name\tAnnotation\tEvidence\n"
        "HMDB0006247\t25-Hydroxycholesterol\t25-Hydroxycholesterol\tABCA1\t"
        "Phospholipid-transporting ATPase ABCA1\tTransporter\t16611739\n",
        encoding="utf-8",
    )
    adapter = LewisMetSensorAdapter(
        path,
        _map(
            ("HMDB0006247", ExternalIdentifier("hmdb", "HMDB0006247"), "metabolite"),
            ("ABCA1", ExternalIdentifier("hgnc", "HGNC:29"), "gene"),
        ),
    )
    edge = next(adapter.iter_edges())
    assert edge.predicate == "metabolite_target_association"
    assert edge.evidence_type == "metabolite_source_association"
    assert edge.context["ligand_kind"] == "metabolite"
    assert edge.context["interaction_mode"] == "metabolic_association"
    assert edge.context["interaction_type"] == "Transporter"


@pytest.mark.parametrize("invalid_type", ["metabolite", "disease", "drug", "molecular_complex"])
def test_protein_side_rejects_incompatible_entity_mapping(tmp_path, invalid_type):
    """An explicit map cannot turn a protein partner into another molecular kind."""
    path = tmp_path / LewisRamilowskiAdapter.profile.filename
    path.write_text(
        "Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\nA\tB\n", encoding="utf-8",
    )
    adapter = LewisRamilowskiAdapter(path, _map(
        ("A", ExternalIdentifier("hgnc", "HGNC:1"), "gene"),
        ("B", ExternalIdentifier("hgnc", "HGNC:2"), invalid_type),
    ))
    assert list(adapter.iter_edges()) == []
    assert list(adapter.iter_entities()) == []
    report = adapter.validation_report()
    assert report.skipped_rows == 1
    assert report.valid is False
    assert any("incompatible type" in error for error in report.errors)


def test_verified_human_xlsx_profiles_use_explicit_headers(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    cases = [
        (
            LewisQiaoAdapter,
            "Human-2014-Qiao-LR-pairs.xlsx",
            "Sheet1",
            ["#", "Ligand      (Entrez ID)", "Receptor (Entrez ID)", "Ligand (Symbol)", "Receptor (Symbols)", "miScore from iRefWeb", "Confidence from iRefWeb"],
            [1, 116, 117, "ADCYAP1", "ADCYAP1R1", 0.921, "high"],
            {"ADCYAP1": "HGNC:100", "ADCYAP1R1": "HGNC:101"},
        ),
        (
            LewisPavlicevAdapter,
            "Human-2017-Pavlicev-LR-pairs.xlsx",
            "Sheet1",
            ["Receptor", "Ligand"],
            ["VIPR1", "ADCYAP1"],
            {"ADCYAP1": "HGNC:100", "VIPR1": "HGNC:101"},
        ),
        (
            LewisHouAdapter,
            "Human-2020-Hou-LR-pairs.xlsx",
            "Sheet1",
            ["Ligand gene symbol", "Ligand HGNC ID", "Ligand location", "Receptor gene symbol", "Receptor HGNC ID", "PMID support"],
            ["A2M", "HGNC:7", "secreted", "LRP1", "HGNC:6692", 1702392],
            {"A2M": "HGNC:7", "LRP1": "HGNC:6692"},
        ),
    ]
    for adapter_class, filename, sheet_name, headers, row, ids in cases:
        path = tmp_path / filename
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = sheet_name
        worksheet.append(headers)
        worksheet.append(row)
        workbook.save(path)
        adapter = adapter_class(
            path,
            _map(*[(symbol, ExternalIdentifier("hgnc", identifier), "gene") for symbol, identifier in ids.items()]),
        )
        edges = list(adapter.iter_edges())
        assert len(edges) == 1
        assert edges[0].context["taxon_id"] == HUMAN_TAXON
        if adapter_class in (LewisPavlicevAdapter, LewisHouAdapter):
            assert edges[0].evidence_type == "source_derived_ligand_receptor"
            assert edges[0].context["interaction_mode"] == "source_derived"


def test_verified_human_delimited_profiles_preserve_complex_and_source_columns(tmp_path):
    cases = [
        (
            LewisWangAdapter,
            "Human-2019-Wang-LR-pairs.csv",
            (
                "Pair.Name,Ligand.ApprovedSymbol,Ligand.Name,Receptor.ApprovedSymbol,"
                "Receptor.Name,Classification\n"
                "A2M_LRP1,A2M,alpha-2-macroglobulin,LRP1,LRP1,other\n"
            ),
            {"A2M": "HGNC:7", "LRP1": "HGNC:6692"},
        ),
        (
            LewisJinAdapter,
            "Human-2020-Jin-LR-pairs.csv",
            (
                "interaction_name,pathway_name,ligand_symbol,receptor_symbol,evidence\n"
                "TGFB1_TGFBR1_TGFBR2,TGFb,TGFB1,TGFBR1&TGFBR2,KEGG: hsa04350\n"
            ),
            {"TGFB1": "HGNC:11766", "TGFBR1": "HGNC:11772", "TGFBR2": "HGNC:11773"},
        ),
        (
            LewisShaoAdapter,
            "Human-2020-Shao-LR-pairs.txt",
            (
                "lr_pair\tligand_gene_symbol\treceptor_gene_symbol\tevidence\n"
                "SEMA3F_PLXNA3\tSEMA3F\tPLXNA3\t15721238\n"
            ),
            {"SEMA3F": "HGNC:10724", "PLXNA3": "HGNC:9101"},
        ),
        (
            LewisDimitrovAdapter,
            "Human-2022-Dimitrov-LR-pairs.csv",
            (
                "source,target,source_genesymbol,target_genesymbol,resource\n"
                "O00182,P08575,LGALS9,PTPRC,consensus\n"
            ),
            {"LGALS9": "HGNC:6566", "PTPRC": "HGNC:9662"},
        ),
    ]
    for adapter_class, filename, content, ids in cases:
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        adapter = adapter_class(
            path,
            _map(*[(symbol, ExternalIdentifier("hgnc", identifier), "gene") for symbol, identifier in ids.items()]),
        )
        edges = list(adapter.iter_edges())
        interaction_edges = [edge for edge in edges if edge.predicate == "ligand_receptor_interaction"]
        assert len(interaction_edges) == 1
        assert interaction_edges[0].context["taxon_id"] == HUMAN_TAXON
        if adapter_class in (LewisWangAdapter, LewisJinAdapter):
            assert interaction_edges[0].evidence_type == "source_derived_ligand_receptor"
            assert interaction_edges[0].context["interaction_mode"] == "source_derived"
        if adapter_class is LewisJinAdapter:
            assert sum(edge.predicate == "has_subunit" for edge in edges) == 2
            assert adapter.validation_report().emitted_membership_edges == 2


def test_noel_xlsx_preserves_multi_subunit_sides(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "Human-2020-Noël-LR-pairs.xlsx"
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "All"
    worksheet.append([
        "Ligand 1", "Ligand 2", "Receptor 1", "Receptor 2", "Receptor 3",
        "Source for interaction", "PubMed ID", "Classifications",
    ])
    worksheet.append([
        "HLA-A", "  ", "LILRB1", "LILRB2", "  ",
        "curated", "9285411", "Antigen binding",
    ])
    workbook.save(path)
    adapter = LewisNoelAdapter(
        path,
        _map(
            ("HLA-A", ExternalIdentifier("hgnc", "HGNC:4931"), "gene"),
            ("LILRB1", ExternalIdentifier("hgnc", "HGNC:6606"), "gene"),
            ("LILRB2", ExternalIdentifier("hgnc", "HGNC:6607"), "gene"),
        ),
    )
    edges = list(adapter.iter_edges())
    assert sum(edge.predicate == "ligand_receptor_interaction" for edge in edges) == 1
    assert adapter.validation_report().emitted_membership_edges == 2
    assert all(edge.metadata["taxon_id"] == HUMAN_TAXON for edge in edges)


def test_lewis_edges_resolve_human_aliases_in_mixed_species_graph(tmp_path):
    """Pass source species to the DB resolver, beyond display provenance."""
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    path.write_text(
        "Pair.Name\tLigand.ApprovedSymbol\tReceptor.ApprovedSymbol\n"
        "A_B\tA\tB\n", encoding="utf-8",
    )
    identifiers = [ExternalIdentifier("ensembl", value) for value in ("ENSG_SHARED1", "ENSG_SHARED2")]
    adapter = LewisRamilowskiAdapter(
        path, _map(*[(symbol, identifier, "gene")
                     for symbol, identifier in zip(("A", "B"), identifiers)]),
    )
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for taxon, namespace, prefix in ((9606, "hgnc", "HGNC:"), (10090, "mgi", "MGI:")):
            import_entities(session, [
                EntityRecord(
                    entity_type="gene", name=f"{taxon}-{index}",
                    identifiers=(ExternalIdentifier(namespace, f"{prefix}{index}"), alias),
                    metadata={"taxon_id": taxon},
                )
                for index, alias in enumerate(identifiers, start=1)
            ])
        result = import_edges(session, adapter.iter_edges(), source_key=adapter.descriptor.key)
        assert result.edges_created == 1
        assert result.edges_skipped == 0
        relation = session.exec(select(Relation)).one()
        for entity_id in (relation.subject_id, relation.object_id):
            assert session.get(Entity, entity_id).canonical_id.startswith("hgnc:")


def test_browaeys_zip_selects_only_lr_member(tmp_path):
    path = tmp_path / "Human-2019-Browaeys-LR-pairs.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "NicheNet-LR-pairs.csv",
            '",","from","to","source","database"\n'
            '"1","CXCL1","CXCR2","kegg_cytokines","kegg"\n',
        )
        archive.writestr(
            "NicheNet-Sig-Network.csv",
            '",","from","to"\n"1","IL6","SH3GL2"\n',
        )
    adapter = LewisBrowaeysAdapter(
        path,
        _map(
            ("CXCL1", ExternalIdentifier("hgnc", "HGNC:4601"), "gene"),
            ("CXCR2", ExternalIdentifier("hgnc", "HGNC:6027"), "gene"),
        ),
    )
    edges = list(adapter.iter_edges())
    assert len(edges) == 1
    assert edges[0].context["interaction_type"] == "kegg"


def test_complex_and_metabolite_rows_are_not_split_or_inferred(tmp_path):
    path = tmp_path / "fixture.tsv"
    path.write_text(
        "ligand\treceptor\tligand_kind\treceptor_kind\n"
        "COL1A1|COL1A2\tITGB1\tprotein\tprotein\n"
        "ATP\tP2RY2\tmetabolite\tprotein\n",
        encoding="utf-8",
    )
    fixture_profile = LewisSourceProfile(
        source_key="test_complex_metabolite",
        filename=path.name,
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="\t",
        ligand_column="ligand",
        receptor_column="receptor",
        ligand_kind_column="ligand_kind",
        receptor_kind_column="receptor_kind",
        complex_separator="|",
    )
    class FixtureAdapter(LewisDelimitedAdapter):
        profile = fixture_profile

    adapter = FixtureAdapter(
        path,
        _map(
            ("COL1A1", ExternalIdentifier("hgnc", "HGNC:2197"), "gene"),
            ("COL1A2", ExternalIdentifier("hgnc", "HGNC:2198"), "gene"),
            ("ITGB1", ExternalIdentifier("hgnc", "HGNC:6153"), "gene"),
            ("ATP", ExternalIdentifier("chebi", "CHEBI:15422"), "metabolite"),
            ("P2RY2", ExternalIdentifier("hgnc", "HGNC:8541"), "gene"),
        ),
    )
    entities = list(adapter.iter_entities())
    edges = list(adapter.iter_edges())
    assert any(entity.entity_type == "molecular_complex" for entity in entities)
    assert any(entity.entity_type == "metabolite" for entity in entities)
    assert sum(edge.predicate == "has_subunit" for edge in edges) == 2
    assert sum(edge.predicate == "ligand_receptor_interaction" for edge in edges) == 2
    assert all(edge.predicate != "ligand_receptor_interaction" or "COL1A1" not in edge.subject.value for edge in edges)


@pytest.mark.parametrize("receptor", ["&B", "B&", "B&&C", "B& &C"])
def test_missing_complex_components_are_not_silently_removed(tmp_path, receptor):
    """Malformed complex syntax must never become a smaller supported complex."""
    path = tmp_path / LewisJinAdapter.profile.filename
    path.write_text(
        f"ligand_symbol,receptor_symbol\nA,{receptor}\n", encoding="utf-8",
    )
    mapping = _map(*[
        (symbol, ExternalIdentifier("hgnc", f"HGNC:{index}"), "gene")
        for index, symbol in enumerate(("A", "B", "C"), start=1)
    ])
    adapter = LewisJinAdapter(path, mapping)
    assert list(adapter.iter_entities()) == []
    assert list(adapter.iter_edges()) == []
    report = adapter.validation_report()
    assert report.skipped_rows == 1
    assert report.valid is False
    assert any("empty component" in error for error in report.errors)


def test_liana_complex_retains_all_subunits_without_pairwise_bindings(tmp_path):
    """LIANA underscore partners identify one multi-subunit endpoint."""
    path = tmp_path / LewisDimitrovAdapter.profile.filename
    path.write_text(
        "source_genesymbol,target_genesymbol,resource\nA,B_C,consensus\n",
        encoding="utf-8",
    )
    mapping = _map(*[
        (symbol, ExternalIdentifier("hgnc", f"HGNC:{index}"), "gene")
        for index, symbol in enumerate(("A", "B", "C"), start=1)
    ])
    adapter = LewisDimitrovAdapter(path, mapping)
    edges = list(adapter.iter_edges())
    interactions = [edge for edge in edges if edge.predicate == "ligand_receptor_interaction"]
    assert len(interactions) == 1
    assert interactions[0].object.namespace == "lewis_complex"
    assert sum(edge.predicate == "has_subunit" for edge in edges) == 2
    for edge in edges:
        assert edge.context["source_reference"] == "https://doi.org/10.1038/s41467-022-30755-0"
        assert edge.source_url == adapter.descriptor.homepage
        assert edge.context["citation"] is None
    del mapping[(HUMAN_TAXON, "C")]
    unresolved = LewisDimitrovAdapter(path, mapping)
    assert list(unresolved.iter_edges()) == []
    assert unresolved.validation_report().unresolved_values == ["C"]


@pytest.mark.parametrize("complex_expression", ["B_ALIAS", "ALIAS_B"])
def test_distinct_complex_components_cannot_collapse_to_one_id(tmp_path, complex_expression):
    """Alias collisions must not invent repeated-subunit complex composition."""
    path = tmp_path / LewisDimitrovAdapter.profile.filename
    path.write_text(f"source_genesymbol,target_genesymbol,resource\nA,{complex_expression},fixture\n")
    adapter = LewisDimitrovAdapter(path, _map(
        ("A", ExternalIdentifier("hgnc", "HGNC:1"), "gene"),
        ("B", ExternalIdentifier("hgnc", "HGNC:2"), "gene"),
        ("ALIAS", ExternalIdentifier("HGNC", "hgnc:2"), "gene"),
    ))
    assert list(adapter.iter_entities()) == []
    assert list(adapter.iter_edges()) == []
    report = adapter.validation_report()
    assert report.valid is False
    assert report.skipped_rows == 1
    assert report.emitted_membership_edges == 0
    assert any("distinct complex components" in error for error in report.errors)


def test_complex_import_order_and_reimport_preserve_source_evidence(tmp_path):
    """Two sources keep opaque complexes and stable provenance in either order."""
    jin_path = tmp_path / LewisJinAdapter.profile.filename
    jin_path.write_text(
        "ligand_symbol,receptor_symbol,evidence\nA,B&C,fixture\n", encoding="utf-8",
    )
    liana_path = tmp_path / LewisDimitrovAdapter.profile.filename
    liana_path.write_text(
        "source_genesymbol,target_genesymbol,resource\nA,C_B,fixture\n", encoding="utf-8",
    )
    mapping = _map(*[
        (symbol, ExternalIdentifier("hgnc", f"HGNC:{index}"), "gene")
        for index, symbol in enumerate(("A", "B", "C"), start=1)
    ])
    factories = [(LewisJinAdapter, jin_path), (LewisDimitrovAdapter, liana_path)]
    signatures = []
    for order in (factories, list(reversed(factories))):
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            for repeat in range(2):
                for cls, path in order:
                    report = import_adapter(session, cls(path, mapping))
                    assert report.errors == []
                    if repeat:
                        assert report.edges_created == report.evidence_created == 0
            entities = {item.id: item for item in session.exec(select(Entity)).all()}
            relations = session.exec(select(Relation)).all()
            evidence = session.exec(select(Evidence)).all()
            assert len(entities) == 5
            assert len(relations) == len(evidence) == 6
            assert sum(item.type == "molecular_complex" for item in entities.values()) == 2
            signatures.append({
                (entities[item.subject_id].canonical_id, item.predicate,
                 entities[item.object_id].canonical_id) for item in relations
            })
            assert {item.source for item in evidence} == {
                "lewis_jin_2020", "lewis_dimitrov_2022",
            }
            for item in relations:
                if item.predicate == "ligand_receptor_interaction":
                    assert entities[item.object_id].type == "molecular_complex"
        engine.dispose()
    assert signatures[0] == signatures[1]


def test_import_is_idempotent_and_preserves_each_source_evidence(tmp_path):
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    path.write_text(
        "Pair.Name\tLigand.ApprovedSymbol\tReceptor.ApprovedSymbol\n"
        "A2M_LRP1\tA2M\tLRP1\n",
        encoding="utf-8",
    )
    adapter = LewisRamilowskiAdapter(
        path,
        _map(
            ("A2M", ExternalIdentifier("hgnc", "HGNC:7"), "gene"),
            ("LRP1", ExternalIdentifier("hgnc", "HGNC:6692"), "gene"),
        ),
    )
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = import_adapter(session, adapter)
        second = import_adapter(session, adapter)
        assert first.edges_created == 1
        assert second.edges_created == 0
        assert second.evidence_created == 0
        assert len(session.exec(select(Entity)).all()) == 2
        assert len(session.exec(select(Relation)).all()) == 1
        assert len(session.exec(select(Evidence)).all()) == 1


def test_source_reported_same_partner_import_is_idempotent(tmp_path):
    """Retain explicitly reported same-partner contact without inferring autocrine signaling."""
    path = tmp_path / LewisJinAdapter.profile.filename
    path.write_text("ligand_symbol,receptor_symbol,evidence\nA,A,fixture\n")
    adapter = LewisJinAdapter(path, _map(("A", ExternalIdentifier("hgnc", "HGNC:1"), "gene")))
    edge = next(iter(adapter.iter_edges()))
    assert edge.context["source_reported_self_interaction"] is True
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = import_adapter(session, adapter)
        second = import_adapter(session, adapter)
        assert first.errors == second.errors == []
        assert first.edges_created == first.evidence_created == 1
        assert second.edges_created == second.evidence_created == 0
        relation = session.exec(select(Relation)).one()
        assert relation.subject_id == relation.object_id
        assert len(session.exec(select(Entity)).all()) == 1
    engine.dispose()


@pytest.mark.parametrize("mouse_symbol", ["H2-T23", "PIRA2", "A&H2-K1"])
def test_cellchat_quarantines_entire_table_with_mouse_partners(tmp_path, mouse_symbol):
    """Matching conserved human symbols cannot rescue an unverified-species table."""
    path = tmp_path / LewisJinAdapter.profile.filename
    path.write_text(f"ligand_symbol,receptor_symbol,evidence\nA,A,fixture\nA,{mouse_symbol},fixture\n")
    adapter = LewisJinAdapter(path, _map(("A", ExternalIdentifier("hgnc", "HGNC:1"), "gene")))
    for iterator in (adapter.iter_entities, adapter.iter_edges, adapter.iter_entities):
        with pytest.raises(ValueError, match="human scope unverified"):
            list(iterator())


def test_alias_collapse_does_not_create_self_interaction(tmp_path):
    """Different raw partners cannot silently become a self interaction."""
    path = tmp_path / LewisJinAdapter.profile.filename
    path.write_text("ligand_symbol,receptor_symbol,evidence\nA,ALIAS,fixture\n")
    adapter = LewisJinAdapter(path, _map(*[
        (symbol, ExternalIdentifier("hgnc", "HGNC:1"), "gene") for symbol in ("A", "ALIAS")
    ]))
    assert list(adapter.iter_edges()) == []
    report = adapter.validation_report()
    assert report.skipped_rows == 1
    assert "distinct partners" in report.errors[0]


@pytest.mark.parametrize("predicate,context", [
    ("ligand_receptor_interaction", {}),
    ("has_subunit", {"source_reported_self_interaction": True, "source_ligand": "A", "source_receptor": "A"}),
    ("ligand_receptor_interaction", {"source_reported_self_interaction": True, "source_ligand": "A", "source_receptor": "B"}),
])
def test_self_edge_guard_requires_explicit_matching_lr_partners(predicate, context):
    """Ordinary self edges and normalized aliases still fail validation."""
    with pytest.raises(ValueError, match="Self edges"):
        validate_edge(EdgeRecord(
            subject=ExternalIdentifier("HGNC", "hgnc:1"), predicate=predicate,
            object=ExternalIdentifier("hgnc", "HGNC:1"), context=context,
        ))


def test_lewis_mapping_rejects_gene_protein_collision(tmp_path):
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    path.write_text(
        "Pair.Name\tLigand.ApprovedSymbol\tReceptor.ApprovedSymbol\n"
        "A2M_LRP1\tA2M\tLRP1\n",
        encoding="utf-8",
    )
    adapter = LewisRamilowskiAdapter(
        path,
        {
            (HUMAN_TAXON, "A2M"): (
                LewisResolvedIdentifier(ExternalIdentifier("hgnc", "HGNC:7"), "gene"),
                LewisResolvedIdentifier(ExternalIdentifier("uniprot", "P01023"), "protein"),
            ),
            (HUMAN_TAXON, "LRP1"): (
                LewisResolvedIdentifier(ExternalIdentifier("hgnc", "HGNC:6692"), "gene"),
            ),
        },
    )

    assert list(adapter.iter_edges()) == []
    report = adapter.validation_report()
    assert report.ambiguous_identifiers == 1
    assert report.skipped_rows == 1
    assert report.valid is False


@pytest.mark.parametrize("conflicting_id", ["HGNC:1", "HGNC:2"])
def test_existing_wrong_type_canonical_entity_cannot_receive_lewis_edges(tmp_path, conflicting_id):
    """A canonical hit cannot override the explicit type in a Lewis mapping."""
    path = tmp_path / LewisRamilowskiAdapter.profile.filename
    path.write_text("Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\nA\tB\n")
    adapter = LewisRamilowskiAdapter(path, _map(
        ("A", ExternalIdentifier("hgnc", "HGNC:1"), "gene"),
        ("B", ExternalIdentifier("hgnc", "HGNC:2"), "gene"),
    ))
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        old_entity = Entity(type="protein", name="LegacyProtein", canonical_id=f"hgnc:{conflicting_id}",
                            entity_metadata='{"taxon_id": 9606}')
        session.add(old_entity)
        session.commit()
        old_id = old_entity.id
        report = import_adapter(session, adapter)
        assert report.entities_conflicted == 1
        assert report.edges_skipped == 1
        assert report.edges_created == report.evidence_created == 0
        assert session.exec(select(Relation)).all() == []
        assert session.exec(select(Evidence)).all() == []
        assert session.get(Entity, old_id).type == "protein"
        direct_report = import_edges(session, adapter.iter_edges(), source_key=adapter.descriptor.key)
        assert direct_report.edges_created == direct_report.evidence_created == 0
        assert direct_report.edges_skipped == 1
        assert any("type conflict" in error for error in direct_report.errors)
    engine.dispose()


def test_rejected_subunit_cannot_leave_a_complex_interaction(tmp_path):
    """A component registration failure blocks the entire source's edge import."""
    path = tmp_path / LewisDimitrovAdapter.profile.filename
    path.write_text("source_genesymbol,target_genesymbol,resource\nA,B_C,fixture\n")
    adapter = LewisDimitrovAdapter(path, _map(*[
        (symbol, ExternalIdentifier("hgnc", f"HGNC:{index}"), "gene")
        for index, symbol in enumerate(("A", "B", "C"), start=1)
    ]))
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Entity(type="protein", name="ConflictingSubunit", canonical_id="hgnc:HGNC:2"))
        session.commit()
        report = import_adapter(session, adapter)
        assert report.entities_conflicted == 1
        assert report.edges_skipped == 3
        assert report.edges_created == report.evidence_created == 0
        assert session.exec(select(Relation)).all() == []
        assert session.exec(select(Evidence)).all() == []
    engine.dispose()


def test_lewis_mapping_does_not_fall_back_to_another_species(tmp_path):
    path = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    path.write_text(
        "Pair.Name\tLigand.ApprovedSymbol\tReceptor.ApprovedSymbol\n"
        "A2M_LRP1\tA2M\tLRP1\n",
        encoding="utf-8",
    )
    adapter = LewisRamilowskiAdapter(
        path,
        {
            (10090, "A2M"): (
                LewisResolvedIdentifier(ExternalIdentifier("mgi", "MGI:88000"), "gene"),
            ),
            (HUMAN_TAXON, "LRP1"): (
                LewisResolvedIdentifier(ExternalIdentifier("hgnc", "HGNC:6692"), "gene"),
            ),
        },
    )

    assert list(adapter.iter_edges()) == []
    report = adapter.validation_report()
    assert report.unresolved_identifiers == 1
    assert report.unresolved_values == ["A2M"]
    assert report.valid is False
