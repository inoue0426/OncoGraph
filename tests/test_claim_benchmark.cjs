const test = require("node:test");
const assert = require("node:assert/strict");
const { evaluate, makeQuestions, readSourceRecords } = require("../scripts/benchmark_claim_abstention.cjs");

function fixture() {
  const entities = [];
  const relations = [];
  let eid = 1;
  for (let gene = 0; gene < 3; gene++) {
    for (let variant = 0; variant < 6; variant++) {
      for (let drug = 0; drug < 3; drug++) {
        const drugId = `drug-${drug}`;
        const cancerId = `cancer-${gene}`;
        if (!entities.some((item) => item.id === drugId)) entities.push({ id: drugId, type: "drug", name: `Drug ${drug}` });
        if (!entities.some((item) => item.id === cancerId)) entities.push({ id: cancerId,
          type: "disease", name: `Cancer ${gene}`, canonical_id: `doid:${gene}` });
        const member = `GENE${gene} V${variant}`;
        relations.push({ subject_id: drugId, object_id: cancerId, predicate: "clinically_evidenced_for",
          evidence: [{ source: "civic", claim_state: "SUPPORTS", source_id: `EID${eid}`,
            context: { civic_review_status: "ACCEPTED", civic_evidence_id: eid,
              molecular_profile_id: eid, molecular_profile: member, profile_variants: [member],
              gene_name: `GENE${gene}`, civic_evidence_type: "PREDICTIVE",
              significance: variant % 2 ? "RESISTANCE" : "SENSITIVITY" } }] });
        eid++;
      }
    }
  }
  entities.push({ id: "complex-drug", type: "drug", name: "Combo-only" });
  for (let i = 0; i < 12; i++) {
    const gene = i % 3;
    relations.push({ subject_id: "complex-drug", object_id: `cancer-${gene}`,
      predicate: "clinically_evidenced_for", evidence: [{ source: "civic", claim_state: "SUPPORTS",
        context: { civic_review_status: "ACCEPTED", civic_evidence_id: eid,
          molecular_profile_id: eid, molecular_profile: `GENE${gene} V${i} + V${i + 1}`,
          profile_variants: [`GENE${gene} V${i}`, `GENE${gene} V${i + 1}`],
          gene_name: `GENE${gene}`, civic_evidence_type: "PREDICTIVE", significance: "SENSITIVITY" } }] });
    eid++;
  }
  return { entities, relations };
}

test("100 unique snapshot-derived questions compare two ablations and safe abstention", () => {
  const { entities, relations } = fixture();
  const source = readSourceRecords(entities, relations).rows;
  assert.equal(makeQuestions(source).length, 100);
  const report = evaluate(entities, relations);
  assert.equal(new Set(report.questions.map((row) => JSON.stringify(row.query))).size, 100);
  assert(report.categories.direct > 0);
  assert(report.categories.other_variant > 0);
  assert(report.categories.complex_profile > 0);
  assert(report.metrics.context_blind.false_answer_rate_on_unanswerable > 0);
  assert(report.metrics.variant_only.false_answer_rate_on_unanswerable > 0);
  assert.equal(report.metrics.claim_scoped.false_answer_rate_on_unanswerable, 0);
  assert.equal(report.metrics.claim_scoped.answer_rate_on_answerable, 1);
  assert.equal(report.truncated_count, 0);
});

test("fails rather than reporting 100 questions if there are too few unique source perturbations", () => {
  const { entities, relations } = fixture();
  assert.throws(() => evaluate(entities, relations, 1000), /unique eligible questions/);
});

test("legacy snapshot runs 100 profile-level questions without inventing variant membership", () => {
  const { entities, relations } = fixture();
  for (const relation of relations) for (const item of relation.evidence) {
    delete item.context.profile_variants;
  }
  const report = evaluate(entities, relations);
  assert.equal(report.scope, "profile");
  assert.equal(report.source_coverage.variant_member_items, 0);
  assert.equal(report.question_count, 100);
  assert(report.questions.every((row) => row.query.scope === "profile"));
  assert.equal(report.metrics.claim_scoped.false_answer_rate_on_unanswerable, 0);
  assert.equal(report.metrics.claim_scoped.answer_rate_on_answerable, 1);
});
