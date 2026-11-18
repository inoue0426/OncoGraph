"""Lewis CLI exit status must distinguish complete and partial imports."""

import pytest
from sqlmodel import Session, create_engine, select
from typer.testing import CliRunner

from oncograph import cli, db
from oncograph.models import Evidence, Relation


@pytest.mark.parametrize("extra_row,expected_exit", [("", 0), ("UNKNOWN\tB\n", 1)])
def test_lewis_cli_reports_partial_persistence_and_exit_status(tmp_path, monkeypatch, extra_row, expected_exit):
    """Valid rows persist idempotently, but unresolved rows cannot produce success."""
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
    for _ in range(2):
        result = CliRunner().invoke(cli.app, [
            "import-source", "lewis_ramilowski_2015", str(source), "--identifier-map", str(mapping),
        ])
        assert result.exit_code == expected_exit, result.output
        if extra_row:
            assert "Import incomplete" in result.output
            assert "accepted records were persisted" in result.output
            assert "1 unresolved" in result.output
        with Session(engine) as session:
            assert len(session.exec(select(Relation)).all()) == 1
            assert len(session.exec(select(Evidence)).all()) == 1
    engine.dispose()
