import sqlite3
from pathlib import Path

from oncograph.public_index import build_index, write_index


def create_snapshot(path: Path) -> None:
    """Create a minimal graph snapshot for index tests.

    Args:
        path: SQLite file to create.
    """
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE entity (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            canonical_id TEXT,
            description TEXT
        );
        CREATE TABLE relation (
            id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_id TEXT NOT NULL
        );
        CREATE TABLE evidence (
            id TEXT PRIMARY KEY,
            relation_id TEXT NOT NULL
        );
        INSERT INTO entity VALUES
            ('1', 'gene', 'EGFR', 'HGNC:3236', 'epidermal growth factor receptor'),
            ('2', 'disease', 'Glioblastoma', 'DOID:3068', NULL);
        INSERT INTO relation VALUES ('r1', '1', 'associated_with', '2');
        INSERT INTO evidence VALUES ('e1', 'r1'), ('e2', 'r1');
        """
    )
    connection.commit()
    connection.close()


def test_missing_database_produces_empty_index(tmp_path: Path) -> None:
    payload = build_index(tmp_path / "missing.db", "test snapshot")

    assert payload["source"]["status"] == "not_found"
    assert payload["counts"] == {"entities": 0}
    assert payload["entities"] == []


def test_index_contains_public_fields_and_evidence_counts(tmp_path: Path) -> None:
    database = tmp_path / "snapshot.db"
    create_snapshot(database)

    payload = build_index(database, "test snapshot")

    assert payload["source"]["status"] == "ready"
    assert len(payload["source"]["sha256"]) == 64
    assert payload["counts"] == {"entities": 2}
    assert payload["entities"][0] == {
        "id": "1",
        "type": "gene",
        "name": "EGFR",
        "canonical_id": "HGNC:3236",
        "description": "epidermal growth factor receptor",
        "relation_count": 1,
        "evidence_count": 2,
    }


def test_index_writer_creates_parent_directories(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "entities.json"
    payload = build_index(tmp_path / "missing.db", "test snapshot")

    write_index(payload, output)

    assert output.is_file()
    assert '"entities": []' in output.read_text(encoding="utf-8")
