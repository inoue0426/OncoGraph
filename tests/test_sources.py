from oncograph.importing import validate_edge
from oncograph.normalization import normalize_identifier
from oncograph.sources.base import EdgeRecord, ExternalIdentifier


def test_identifier_normalization():
    result = normalize_identifier(ExternalIdentifier("NCT", "nct01234567"))
    assert result.namespace == "clinicaltrials.gov"
    assert result.value == "NCT01234567"


def test_edge_validation():
    edge = EdgeRecord(
        subject=ExternalIdentifier("drugbank", "DB0001"),
        predicate="targets",
        object=ExternalIdentifier("hgnc", "EGFR"),
        source_record_id="example",
    )
    validate_edge(edge)
