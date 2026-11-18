"""Reject structurally ambiguous source rows before resolving their identifiers."""

import csv
import zipfile
from pathlib import Path

import pytest

from oncograph.sources.lewis_lab import (
    LewisBrowaeysAdapter,
    LewisRamilowskiAdapter,
    load_identifier_map,
)


@pytest.mark.parametrize("row", ["A\tB\t123\textra\n", "A\tB\n"])
def test_source_rejects_wrong_width_on_every_access(tmp_path: Path, row: str) -> None:
    """Reject extra or omitted fields even when both endpoint columns exist.

    Args:
        tmp_path: Temporary fixture directory.
        row: Malformed row after a correctly shaped row.

    Returns:
        None.
    """
    path = tmp_path / LewisRamilowskiAdapter.profile.filename
    path.write_text(
        "Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\tPMID.Manual\nA\tB\t123\n" + row,
        encoding="utf-8",
    )
    adapter = LewisRamilowskiAdapter(path, {})
    for access in (adapter.iter_entities, adapter.iter_edges, adapter.validation_report):
        with pytest.raises(ValueError, match="incorrect field count"):
            access()


def test_archive_rejects_extra_fields(tmp_path: Path) -> None:
    """Apply field-count validation to the selected archive member.

    Args:
        tmp_path: Temporary fixture directory.

    Returns:
        None.
    """
    path = tmp_path / LewisBrowaeysAdapter.profile.filename
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("NicheNet-LR-pairs.csv", "from,to\nA,B,unexpected\n")
    with pytest.raises(ValueError, match="incorrect field count"):
        LewisBrowaeysAdapter(path, {}).validation_report()


@pytest.mark.parametrize(
    "body, error",
    [
        (
            "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\tidentifier\n"
            + "9606\tA\thgnc\tHGNC:1\tgene\tHGNC:2\n",
            "duplicate column",
        ),
        (
            "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\n"
            + "9606\tA\thgnc\tHGNC:1\tgene\textra\n",
            "incorrect field count",
        ),
        (
            "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\tcomment\n"
            + "9606\tA\thgnc\tHGNC:1\tgene\n",
            "incorrect field count",
        ),
    ],
)
def test_identifier_map_rejects_ambiguous_columns(tmp_path: Path, body: str, error: str) -> None:
    """Do not silently discard a conflicting identifier or a shifted column.

    Args:
        tmp_path: Temporary fixture directory.
        body: Malformed mapping table.
        error: Expected diagnostic fragment.

    Returns:
        None.
    """
    path = tmp_path / "map.tsv"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        load_identifier_map(path)


def test_explicit_blank_optional_mapping_field_and_bom_are_supported(tmp_path: Path) -> None:
    """Preserve valid empty cells while rejecting absent columns.

    Args:
        tmp_path: Temporary fixture directory.

    Returns:
        None.
    """
    path = tmp_path / "map.tsv"
    path.write_text(
        "taxon_id\tsymbol\tnamespace\tidentifier\tentity_type\tcomment\n"
        "9606\tA\thgnc\tHGNC:1\tgene\t\n",
        encoding="utf-8-sig",
    )
    assert load_identifier_map(path)[(9606, "A")][0].identifier.value == "HGNC:1"


def test_unterminated_quote_is_not_accepted_as_a_partner(tmp_path: Path) -> None:
    """Fail on malformed CSV quoting instead of reporting a misleading unresolved ID.

    Args:
        tmp_path: Temporary fixture directory.

    Returns:
        None.
    """
    path = tmp_path / LewisRamilowskiAdapter.profile.filename
    path.write_text(
        'Ligand.ApprovedSymbol\tReceptor.ApprovedSymbol\nA\t"B\n',
        encoding="utf-8",
    )
    with pytest.raises(csv.Error):
        LewisRamilowskiAdapter(path, {}).validation_report()
