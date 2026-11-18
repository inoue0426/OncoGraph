"""Lewis CLI exit status must distinguish complete and partial imports."""

import pytest
from sqlmodel import Session, create_engine, select
from typer.testing import CliRunner

from oncograph import cli, db
from oncograph.models import Entity, Evidence, Relation


@pytest.mark.parametrize("atomic", [False, True])
@pytest.mark.parametrize("extra_row,wrong_type,expected_exit,relation_count", [
    ("", False, 0, 1), ("UNKNOWN\tB\n", False, 1, 1), ("", True, 1, 0),
])
def test_lewis_cli_reports_partial_persistence_and_exit_status(tmp_path, monkeypatch, extra_row, wrong_type, expected_exit, relation_count, atomic):
    """Valid rows persist idempotently, but unresolved rows cannot produce success."""
    if atomic and expected_exit:
        relation_count = 0
    source = tmp_path / "Human-2015-Ramilowski-LR-pairs.txt"
    source.write_text("Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\nA\tB\n" + extra_row)
    mapping = tmp_path / "mapping.tsv"
    mapping.write_text(
        "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\n"
        "9606\tA\thgnc\tHGNC:1\tgene\n9606\tB\thgnc\tHGNC:2\tgene\n"
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'import.db'}")
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr(db, "engine", engine)
    if wrong_type:
        db.create_db_and_tables()
        with Session(engine) as session:
            session.add(Entity(type="protein", name="LegacyProtein", canonical_id="hgnc:HGNC:1"))
            session.commit()
    for _ in range(2):
        result = CliRunner().invoke(cli.app, [
            "import-source", "lewis_ramilowski_2015", str(source), "--identifier-map", str(mapping),
        ] + (["--atomic"] if atomic else []))
        assert result.exit_code == expected_exit, result.output
        if expected_exit:
            assert "Import incomplete" in result.output
            assert ("all source writes were rolled back" if atomic else "accepted records were persisted") in result.output
        if extra_row:
            assert "1 unresolved" in result.output
        if wrong_type:
            assert "type conflict" in result.output
        with Session(engine) as session:
            assert len(session.exec(select(Relation)).all()) == relation_count
            assert len(session.exec(select(Evidence)).all()) == relation_count
    engine.dispose()
