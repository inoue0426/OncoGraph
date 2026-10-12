"""Evidence tree keeps negative claims and missing US regulatory data explicit."""

from oncograph.evidence_tree import build_evidence_tree


def test_projection_deduplicates_and_preserves_context():
    entities = [
        {"id": "d", "type": "DISEASE", "name": "Lung cancer", "canonical_id": "doid:3908"},
        {"id": "t", "type": "DRUG", "name": "Drug X", "canonical_id": "ncit:123"},
    ]
    item = {"source": "civic", "source_id": "EID1", "source_url": "https://civicdb.org/evidence/1",
            "claim_state": "CONTRADICTS", "context": {"civic_review_status": "ACCEPTED",
            "civic_evidence_id": 1, "molecular_profile_id": 50, "molecular_profile": "EGFR T790M",
            "profile_variants": ["EGFR T790M", "EGFR C797S"], "gene_name": "EGFR",
            "citation_url": "https://pubmed.ncbi.nlm.nih.gov/123/"}}
    relations = [
        {"predicate": "has_civic_evidence_for", "subject_id": "p", "object_id": "d", "evidence": [item]},
        {"predicate": "clinically_evidenced_for", "subject_id": "t", "object_id": "d", "evidence": [item]},
    ]
    kwargs = {"gene": "EGFR", "variant": "T790M", "disease": "DOID:3908"}
    tree = build_evidence_tree(entities, relations, **kwargs)
    assert tree["total_evidence_items"] == 1
    assert tree["evidence"][0]["claim_state"] == "contradicts"
    assert tree["evidence"][0]["profile"]["complex_profile"] is True
    assert tree["evidence"][0]["therapies"] == [{"id": "ncit:123", "name": "Drug X"}]
    assert tree["us_regulatory_label"]["status"] == "not_integrated"
    assert build_evidence_tree(entities, relations, **{**kwargs, "variant": "L858R"})["status"] == "not_found_in_snapshot"


def test_legacy_profile_is_not_asserted_as_confirmed_member():
    item = {"source": "civic", "context": {"civic_review_status": "ACCEPTED",
            "civic_evidence_id": 1, "molecular_profile_id": 50, "molecular_profile": "EGFR T790M",
            "gene_name": "EGFR"}}
    tree = build_evidence_tree(
        [{"id": "d", "type": "disease", "name": "Lung cancer", "canonical_id": "doid:3908"}],
        [{"predicate": "has_civic_evidence_for", "subject_id": "p", "object_id": "d", "evidence": [item]}],
        gene="EGFR", variant="T790M", disease="doid:3908",
    )
    assert tree["evidence"][0]["profile"]["match_type"] == "profile_only"
