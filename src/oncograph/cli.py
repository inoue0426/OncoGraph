import typer

from .db import create_db_and_tables
from .seed import seed as seed_db

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
