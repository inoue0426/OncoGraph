const assert = require("node:assert/strict");
const test = require("node:test");
const { findQuestionEvidence, asksForBestTreatment, citedMolecularProfiles } = require("../web/ask-evidence.js");

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

test("broad gene questions keep different relationship types in the AI context", () => {
  const related = [
    ...Array.from({ length: 14 }, (_, i) => ({
      subject_id: "g", object_id: `t${i}`, predicate: "expressed_in",
      evidence: [{ source: "gtex" }],
    })),
    { subject_id: "g", object_id: "d", predicate: "associated_with", evidence: [{ source: "open_targets" }] },
    { subject_id: "drug", object_id: "g", predicate: "targets", evidence: [{ source: "gtopdb" }] },
    { subject_id: "g", object_id: "v", predicate: "has_civic_variant", evidence: [{ source: "civic" }] },
  ];
  const items = [
    ...entities,
    ...Array.from({ length: 14 }, (_, i) => ({ id: `t${i}`, name: `Tissue ${i}`, type: "tissue" })),
    { id: "drug", name: "Gefitinib", type: "drug" },
    { id: "v", name: "EGFR V600E", type: "biomarker" },
  ];
  const result = findQuestionEvidence("What do we know about EGFR?", items, related);
  assert.equal(result.records.length, 12);
  assert.equal(result.omitted, true);
  const prioritized = result.records.slice(0, result.aiCount);
  assert.equal(result.aiCount, 5);
  assert(prioritized.some((record) => record.predicate === "associated_with"));
  assert(prioritized.some((record) => record.predicate === "targets"));
  assert(prioritized.some((record) => record.predicate === "has_civic_variant"));
  assert.equal(prioritized.filter((record) => record.predicate === "expressed_in").length, 2);
  assert.deepEqual(result.records.map((record, i) => record.id),
    Array.from({ length: 12 }, (_, i) => `R${i + 1}`));
});

test("a topic question prefers the requested relationship and a named pair", () => {
  const items = [...entities, { id: "t", name: "Liver", type: "tissue" },
    { id: "drug", name: "Gefitinib", type: "drug" }];
  const related = [
    { subject_id: "g", object_id: "t", predicate: "expressed_in", evidence: [{ source: "gtex" }] },
    { subject_id: "g", object_id: "d", predicate: "associated_with", evidence: [{ source: "open_targets" }] },
    { subject_id: "drug", object_id: "g", predicate: "targets", evidence: [{ source: "gtopdb" }] },
    { subject_id: "g", object_id: "trial", predicate: "studied_in", evidence: [{ source: "clinicaltrials_gov" }] },
  ];
  items.push({ id: "trial", name: "Trial ABC", type: "trial" });
  const drugs = findQuestionEvidence("EGFR drugs", items, related);
  assert.equal(drugs.records[0].predicate, "targets");
  assert.equal(drugs.aiCount, 4);
  assert.equal(findQuestionEvidence("EGFR 発現", items, related).records[0].predicate, "expressed_in");
  assert.equal(findQuestionEvidence("EGFR clinical trials in lung cancer", items, related).records[0].predicate,
    "studied_in");
  assert.equal(findQuestionEvidence("EGFR clinical trials", items, related).records[0].predicate, "studied_in");
  assert.equal(findQuestionEvidence("How are EGFR and Gefitinib linked?", items, related).records[0].predicate,
    "targets");
  const pair = findQuestionEvidence("How is EGFR linked to lung cancer?", items, related);
  assert.equal(pair.records[0].object, "Lung cancer");
});

test("specific cancer queries do not pull generic cancer drugs into the evidence", () => {
  const items = [
    { id: "breast", type: "disease", name: "Breast Cancer" },
    { id: "cancer", type: "disease", name: "Cancer" },
    { id: "specific", type: "drug", name: "Drug A" },
    { id: "generic", type: "drug", name: "Drug B" },
  ];
  const links = [
    { subject_id: "specific", object_id: "breast", predicate: "indicated_for", evidence: [{ source: "dataset" }] },
    { subject_id: "generic", object_id: "cancer", predicate: "indicated_for", evidence: [{ source: "dataset" }] },
  ];
  const result = findQuestionEvidence("What is the best drug for Breast Cancer?", items, links);
  assert.deepEqual(result.matches.map((item) => item.name), ["Breast Cancer"]);
  assert.deepEqual(result.records.map((record) => record.subject), ["Drug A"]);
  assert(asksForBestTreatment(result.question));
  assert(asksForBestTreatment("乳がんに最適な薬は？"));
  assert(!asksForBestTreatment("What drugs target EGFR?"));
});

test("CIViC molecular profiles stay attached to their record IDs", () => {
  const records = [
    { id: "R1", sources: [
      { source: "civic", molecular_profile: "ERBB2 L755S" },
      { source: "civic", molecular_profile: "ERBB2 L866M" },
    ] },
    { id: "R2", sources: [
      { source: "civic", molecular_profile: "ERBB2 L755S" },
      { source: "other", molecular_profile: "unknown" },
    ] },
  ];
  assert.deepEqual(citedMolecularProfiles(records), [
    { name: "ERBB2 L755S", ids: ["R1", "R2"] },
    { name: "ERBB2 L866M", ids: ["R1"] },
  ]);
});
