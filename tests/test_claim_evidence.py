"""Claim check never turns a target path or a multi-variant profile into drug efficacy."""

import pytest

from oncograph.claim_evidence import evaluate_evidence_claim
from oncograph.evidence_tree import build_evidence_tree


def test_claim_classifies_predictive_items_only():
    entities = [
        {"id": "d", "type": "DISEASE", "name": "Lung cancer", "canonical_id": "doid:3908"},
        {"id": "t", "type": "DRUG", "name": "Osimertinib", "canonical_id": "ncit:1"},
        {"id": "g", "type": "GENE", "name": "EGFR"},
    ]

    def item(eid, significance, members, state="SUPPORTS"):
        return {"source": "civic", "source_id": f"EID{eid}", "claim_state": state,
                "context": {"civic_evidence_id": eid, "molecular_profile_id": eid + 10,
                            "molecular_profile": "EGFR T790M", "gene_name": "EGFR",
                            "civic_review_status": "ACCEPTED", "civic_evidence_type": "PREDICTIVE",
                            "profile_variants": members, "significance": significance}}

    relations = [
        {"subject_id": "t", "object_id": "g", "predicate": "targets", "evidence": [{"source": "gtopdb"}]},
        {"subject_id": "t", "object_id": "d", "predicate": "clinically_evidenced_for",
         "evidence": [item(1, "SENSITIVITY", ["EGFR T790M"]),
                      item(2, "RESISTANCE", ["EGFR T790M"]),
                      item(3, "SENSITIVITY", ["EGFR T790M", "EGFR C797S"]),
                      item(4, "SENSITIVITY", ["EGFR T790M"], "CONTRADICTS")]},
    ]
    tree = build_evidence_tree(entities, relations, gene="EGFR", variant="T790M",
                               disease="Lung cancer", limit=200)
    result = evaluate_evidence_claim(tree, therapy="ncit:1", effect="sensitivity")
    assert result["status"] == "mixed_records"
    assert result["counts"] == {"supporting": 1, "opposing": 1, "disputed": 1, "context_only": 1}
    assert result["evidence"]["context_only"][0]["profile"]["complex_profile"] is True
    assert evaluate_evidence_claim(tree, therapy="unrecorded", effect="sensitivity")["status"] == "not_found_in_snapshot"
    assert evaluate_evidence_claim({**tree, "truncated": True}, therapy="ncit:1", effect="sensitivity")["status"] == "incomplete_review"
    with pytest.raises(ValueError):
        evaluate_evidence_claim(tree, therapy="ncit:1", effect="efficacy")
