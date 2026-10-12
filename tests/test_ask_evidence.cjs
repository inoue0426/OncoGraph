const assert = require("node:assert/strict");
const test = require("node:test");
const { findQuestionEvidence } = require("../web/ask-evidence.js");

const entities = [
  { id: "g", type: "gene", name: "EGFR", canonical_id: "hgnc:3236" },
  { id: "d", type: "disease", name: "Lung cancer", canonical_id: "doid:123" },
  { id: "other", type: "gene", name: "ALK", canonical_id: "hgnc:xxx" },
];
const relations = [{ subject_id: "g", object_id: "d", predicate: "associated_with", evidence: [
  { source: "civic", source_url: "https://civicdb.org/links/evidence/1", source_id: "EID1",
    claim_state: "CONTRADICTS", context: { significance: "RESISTANCE" } },
] }];

test("answers only with graph links and preserves negative provenance", () => {
  const result = findQuestionEvidence("What evidence links EGFR and lung cancer?", entities, relations);
  assert.equal(result.records.length, 1);
  assert.equal(result.records[0].id, "R1");
  assert.equal(result.records[0].sources[0].claim_state, "contradicts");
  assert.equal(result.records[0].sources[0].significance, "RESISTANCE");
  assert.equal(result.records[0].sources[0].source_url, "https://civicdb.org/links/evidence/1");
  assert.deepEqual(result.matches.map((item) => item.name).sort(), ["EGFR", "Lung cancer"]);
});

test("unmatched and clipped queries do not become claims", () => {
  assert.equal(findQuestionEvidence("What is unknown?", entities, relations).records.length, 0);
  const many = Array.from({ length: 15 }, () => relations[0]);
  const result = findQuestionEvidence("EGFR", entities, many);
  assert.equal(result.records.length, 12);
  assert.equal(result.omitted, true);
  assert.throws(() => findQuestionEvidence("a", entities, relations));
});
