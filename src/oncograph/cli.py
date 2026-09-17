import typer
from sqlmodel import Session

from .db import create_db_and_tables, engine
from .importing import import_adapter
from .seed import seed as seed_db
from .sources import registry

app = typer.Typer(help="OncoGraph command line tools")


@app.command()
def init_db() -> None:
    """Create database tables."""
    create_db_and_tables()
    typer.echo("Database initialized.")


@app.command()
def seed() -> None:
    """Load a tiny synthetic demonstration graph."""
    seed_db()
    typer.echo("Seed complete.")


@app.command()
def import_source(
    source: str = typer.Argument(..., help="Registered source key, e.g. hgnc or gene_ontology"),
    path: str = typer.Argument(..., help="Path to a locally permitted source file"),
    release: str = typer.Option(None, help="Upstream release/version label to record"),
    hgnc_mapping: str = typer.Option(
        None,
        "--hgnc-mapping",
        help="GtoPdb target-to-HGNC mapping CSV (required for the gtopdb source)",
    ),
    publication_metadata: str = typer.Option(
        None,
        "--publication-metadata",
        help=(
            "Fetched publication metadata JSON (required for the europe_pmc source; "
            "'path' is its curated citations file)"
        ),
    ),
) -> None:
    """Import a locally permitted source file into the database.

    The file must already be present on disk under terms that allow this use;
    this command does not fetch or redistribute upstream data.
    """
    adapter_cls = registry.get(source)
    if source == "gtopdb":
        if not hgnc_mapping:
            raise typer.BadParameter("--hgnc-mapping is required for the gtopdb source")
        adapter = adapter_cls(path, hgnc_mapping, release=release)
    elif source == "europe_pmc":
        if not publication_metadata:
            raise typer.BadParameter("--publication-metadata is required for the europe_pmc source")
        adapter = adapter_cls(path, publication_metadata, release=release)
    else:
        adapter = adapter_cls(path, release=release)
    create_db_and_tables()
    with Session(engine) as session:
        report = import_adapter(session, adapter)
    typer.echo(
        f"entities: {report.entities_created} created, {report.entities_updated} updated; "
        f"edges: {report.edges_created} created, {report.edges_skipped} skipped"
    )
    for error in report.errors[:20]:
        typer.echo(f"  {error}")
    if len(report.errors) > 20:
        typer.echo(f"  ... and {len(report.errors) - 20} more errors")
