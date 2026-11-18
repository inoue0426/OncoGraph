"""Regression tests for common crosswalk namespace spellings."""

import pytest

from oncograph.normalization import normalize_identifier
from oncograph.sources.base import ExternalIdentifier


@pytest.mark.parametrize(
    ("namespace", "value", "expected_namespace", "expected_value"),
    [
        ("NCBI Gene", "1956", "ncbigene", "1956"),
        ("ncbi_gene", "1956", "ncbigene", "1956"),
        ("geneid", "1956", "ncbigene", "1956"),
        ("diseaseontology", "DOID:9351", "doid", "9351"),
        ("efo_id", "EFO:0000311", "efo", "0000311"),
        ("ncbigene", "NCBIGENE:1956", "ncbigene", "1956"),
        ("pubchem", "CID:2244", "pubchem", "2244"),
        ("hgnc", "hgnc:3236", "hgnc", "HGNC:3236"),
        ("uniprotkb", "p00533", "uniprot", "P00533"),
        ("mondo", "mondo:0005233", "mondo", "0005233"),
    ],
)
def test_common_identifier_spellings_normalize(namespace, value, expected_namespace, expected_value):
    result = normalize_identifier(ExternalIdentifier(namespace, value))
    assert (result.namespace, result.value) == (expected_namespace, expected_value)
