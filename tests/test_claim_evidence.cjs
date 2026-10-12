const assert = require("node:assert/strict");
const test = require("node:test");
const { buildEvidenceTree } = require("../web/evidence-tree.js");
const { evaluateEvidenceClaim } = require("../web/claim-evidence.js");

const entities = [
  { id: "d", name: "Lung cancer", type: "DISEASE", canonical_id: "doid:3908" },
  { id: "t", name: "Osimertinib", type: "DRUG", canonical_id: "ncit:1" },
  { id: "t2", name: "Gefitinib", type: "DRUG", canonical_id: "ncit:2" },
  { id: "g", name: "EGFR", type: "GENE" },
];
function record(id, significance = "SENSITIVITY", direction = "SUPPORTS", members = ["EGFR T790M"],
  evidenceType = "PREDICTIVE") {
  return { source: "civic", source_id: `EID${id}`, source_url: `https://civicdb.org/evidence/${id}`,
    claim_state: direction, context: { civic_review_status: "ACCEPTED", civic_evidence_id: id,
      molecular_profile_id: id + 100, molecular_profile: "EGFR T790M", profile_variants: members,
      gene_name: "EGFR", civic_evidence_type: evidenceType, significance } };
}
function relation(subject, id, ...args) {
  return { subject_id: subject, object_id: "d", predicate: "clinically_evidenced_for",
    evidence: [record(id, ...args)] };
}
const query = { gene: "EGFR", variant: "T790M", disease: "Lung cancer" };

test("matches one therapy and effect without upgrading target paths or other drugs", () => {
  const relations = [relation("t", 1), relation("t2", 2),
    { subject_id: "t", object_id: "g", predicate: "targets", evidence: [{ source: "gtopdb" }] }];
  const tree = buildEvidenceTree(entities, relations, { ...query, limit: 200 });
  const result = evaluateEvidenceClaim(tree, { therapy: "Osimertinib", effect: "sensitivity" });
  assert.equal(result.status, "supporting_records");
  assert.deepEqual(result.evidence.supporting.map((item) => item.evidence_id), ["1"]);
  assert.equal(result.excluded.wrong_therapy, 1);
  assert.equal(evaluateEvidenceClaim(tree, { therapy: "missing", effect: "sensitivity" }).status, "not_found_in_snapshot");
});

test("keeps opposite reports and disputed significance separate; complex and legacy profiles abstain", () => {
  const relations = [relation("t", 1), relation("t", 2, "RESISTANCE"),
    relation("t", 3, "SENSITIVITY", "CONTRADICTS"),
    relation("t", 4, "SENSITIVITY", "SUPPORTS", ["EGFR T790M", "EGFR C797S"]),
    relation("t", 5, "SENSITIVITY", "SUPPORTS", []),
    relation("t", 6, "SENSITIVITY", "SUPPORTS", ["EGFR T790M"], "PROGNOSTIC")];
  const result = evaluateEvidenceClaim(buildEvidenceTree(entities, relations, { ...query, limit: 200 }),
    { therapy: "ncit:1", effect: "sensitivity" });
  assert.equal(result.status, "mixed_records");
  assert.deepEqual(result.counts, { supporting: 1, opposing: 1, disputed: 1, context_only: 2 });
  assert.equal(result.excluded.non_predictive, 1);
  assert.equal(result.evidence.context_only[0].profile.complex_profile, true);
});

test("truncation and display caps force incomplete review; invalid claims are rejected", () => {
  const tree = buildEvidenceTree(entities, [relation("t", 1)], { ...query, limit: 200 });
  assert.equal(evaluateEvidenceClaim({ ...tree, truncated: true }, { therapy: "Osimertinib", effect: "sensitivity" }).status,
    "incomplete_review");
  const extended = { ...tree, evidence: [tree.evidence[0], { ...tree.evidence[0], evidence_id: "2" }] };
  const checked = evaluateEvidenceClaim(extended, { therapy: "Osimertinib", effect: "sensitivity", limit: 1 });
  assert.equal(checked.status, "incomplete_review");
  assert.equal(checked.counts.supporting, 2);
  assert.throws(() => evaluateEvidenceClaim(tree, { therapy: "", effect: "sensitivity" }));
  assert.throws(() => evaluateEvidenceClaim(tree, { therapy: "Osimertinib", effect: "response" }));
});

test("legacy snapshot can answer exact whole-profile question while single variant still abstains", () => {
  const tree = buildEvidenceTree(entities, [relation("t", 9, "SENSITIVITY", "SUPPORTS", [])],
    { gene: "EGFR", variant: "EGFR T790M", disease: "Lung cancer" });
  assert.equal(evaluateEvidenceClaim(tree, { therapy: "Osimertinib", effect: "sensitivity" }).status,
    "insufficient_variant_context");
  const profile = evaluateEvidenceClaim(tree, { therapy: "Osimertinib", effect: "sensitivity", scope: "profile" });
  assert.equal(profile.status, "supporting_records");
  assert.equal(profile.query.scope, "profile");
});
