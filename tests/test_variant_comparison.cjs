const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");

const context = vm.createContext({});
vm.runInContext(fs.readFileSync("web/variant-comparison.js", "utf8"), context);

const disease = { id: "d1", canonical_id: "doid:3908", name: "Lung cancer", type: "disease" };
const drug = { id: "t1", canonical_id: "ncit:C1", name: "Drug A", type: "drug" };
const entities = new Map([[disease.id, disease], [drug.id, drug]]);
function record({ id, profile = "10", claim = "SUPPORTS", significance = "RESISTANCE",
                  variants = ["EGFR T790M"], level = "B", rating = 5 } = {}) {
  return { source: "civic", claim_state: claim, context: {
    civic_review_status: "ACCEPTED", civic_evidence_id: id,
    molecular_profile_id: profile, molecular_profile: "EGFR T790M",
    gene_name: "EGFR", profile_variants: variants,
    civic_evidence_type: "PREDICTIVE", significance,
    evidence_level: level, evidence_rating: rating,
  } };
}

test("deduplicates profile and therapy edges without converting resistance to sensitivity", () => {
  const r1 = record({ id: 123 });
  const r2 = record({ id: 124, claim: "CONTRADICTS" });
  const relations = [
    { subject_id: "p1", object_id: "d1", predicate: "has_civic_evidence_for", evidence: [r1, r2] },
    { subject_id: "t1", object_id: "d1", predicate: "clinically_evidenced_for", evidence: [r1, r2] },
  ];
  const rows = context.buildVariantComparisonRows(relations, entities);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].drug.name, "Drug A");
  assert.equal(context.civicComparisonCategory(rows[0]), "resistance");
  assert.equal(context.civicComparisonCategory(rows[1]), "contradicts");
});

test("keeps multi-variant profiles and no-therapy evidence explicit", () => {
  const variants = ["EGFR T790M", "EGFR C797S"];
  const relations = [{ subject_id: "p1", object_id: "d1",
    predicate: "has_civic_evidence_for", evidence: [record({ id: 125, variants })] }];
  const rows = context.buildVariantComparisonRows(relations, entities);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].drug, null);
  assert.equal(rows[0].variants.length, 2);
  assert.equal(rows[0].profileId, "10");
});

test("omits unaccepted records and marks legacy profiles without claiming a variant", () => {
  const unaccepted = record({ id: 126 });
  unaccepted.context.civic_review_status = "SUBMITTED";
  const legacy = record({ id: 127 });
  delete legacy.context.profile_variants;
  const relations = [{ subject_id: "p1", object_id: "d1",
    predicate: "has_civic_evidence_for", evidence: [unaccepted, legacy] }];
  const rows = context.buildVariantComparisonRows(relations, entities);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].hasExplicitVariants, false);
  assert.equal(rows[0].variants[0], "Profile: EGFR T790M");
});
