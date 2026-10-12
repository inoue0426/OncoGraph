const assert = require("node:assert/strict");
const test = require("node:test");
const { buildEvidenceTree } = require("../web/evidence-tree.js");

const entities = [{ id: "d", type: "DISEASE", name: "Lung cancer", canonical_id: "doid:3908" },
  { id: "t", type: "DRUG", name: "Drug X", canonical_id: "ncit:123" }];
const record = (id, claim = "SUPPORTS", variants = ["EGFR T790M"]) => ({
  source: "civic", source_id: `EID${id}`, source_url: `https://civicdb.org/evidence/${id}`,
  claim_state: claim, retrieved_at: "2026-01-01", context: {
    civic_review_status: "ACCEPTED", civic_evidence_id: id, molecular_profile_id: 50,
    molecular_profile: "EGFR T790M", profile_variants: variants, gene_name: "EGFR",
    civic_evidence_type: "PREDICTIVE", significance: "RESISTANCE", citation_url: "https://pubmed.ncbi.nlm.nih.gov/123/",
  },
});
const relations = [
  { predicate: "has_civic_evidence_for", subject_id: "p", object_id: "d", evidence: [record(1), record(2, "CONTRADICTS")] },
  { predicate: "clinically_evidenced_for", subject_id: "t", object_id: "d", evidence: [record(1)] },
];
const query = { gene: "EGFR", variant: "T790M", disease: "DOID:3908" };

test("deduplicates therapeutic edges, preserves contradiction and provenance", () => {
  const tree = buildEvidenceTree(entities, relations, query);
  assert.equal(tree.total_evidence_items, 2);
  assert.equal(tree.evidence[0].therapies[0].name, "Drug X");
  assert.equal(tree.evidence[1].claim_state, "contradicts");
  assert.equal(tree.evidence[0].citation_url, "https://pubmed.ncbi.nlm.nih.gov/123/");
  assert.equal(tree.us_regulatory_label.status, "not_integrated");
  assert.equal(tree.civic_assertions.status, "not_integrated");
});

test("complex membership, legacy profile match and empty results stay distinct", () => {
  const complex = [{ ...relations[0], evidence: [record(3, "SUPPORTS", ["EGFR T790M", "EGFR C797S"])] }];
  assert.equal(buildEvidenceTree(entities, complex, query).evidence[0].profile.complex_profile, true);
  const legacy = [{ ...relations[0], evidence: [record(4, "SUPPORTS", [])] }];
  assert.equal(buildEvidenceTree(entities, legacy, query).evidence[0].profile.match_type, "profile_only");
  assert.equal(buildEvidenceTree(entities, relations, { ...query, variant: "L858R" }).status, "not_found_in_snapshot");
  assert.equal(buildEvidenceTree(entities, relations, { ...query, limit: 1 }).truncated, true);
  assert.throws(() => buildEvidenceTree(entities, relations, { ...query, jurisdiction: "GB" }));
});
