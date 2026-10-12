const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { evaluate } = require("../scripts/evaluate_variant_questions.cjs");

test("variant scope removes a different variant without claiming unreviewed accuracy", () => {
  const dir = fs.mkdtempSync(path.join(process.cwd(), "data/benchmarks/evaluation-test-"));
  try {
    const entities = [
      { id: "drug", type: "drug", name: "Drug X" },
      { id: "disease", type: "disease", name: "Lung cancer" },
    ];
    const civic = (id, variant) => ({ source: "civic", source_url: `https://civicdb.org/evidence/${id}`,
      context: { civic_review_status: "ACCEPTED", civic_evidence_id: id,
        molecular_profile_id: id, molecular_profile: `EGFR ${variant}`,
        profile_variants: [`EGFR ${variant}`], gene_name: "EGFR" } });
    const relations = [{ predicate: "clinically_evidenced_for", subject_id: "drug", object_id: "disease",
      evidence: [civic(101, "T790M"), civic(102, "L858R")] }];
    const queue = [{ id: "q1", gene: "EGFR", variant: "T790M", disease: "Lung cancer",
      therapy: "Drug X", review_status: "pending" }];
    for (const [name, value] of [["search-index.json", entities], ["relations.json", relations],
                                  ["queue.json", queue]]) {
      fs.writeFileSync(path.join(dir, name), JSON.stringify(value));
    }
    const args = { snapshotDir: dir, queueFile: path.join(dir, "queue.json"), candidateLimit: 20 };
    const unreviewed = evaluate(args);
    assert.equal(unreviewed.report.candidate_count, 2);
    assert.deepEqual(unreviewed.report.questions[0].baseline_evidence_ids, ["101", "102"]);
    assert.deepEqual(unreviewed.report.questions[0].scoped_evidence_ids, ["101"]);
    assert.equal(unreviewed.report.metrics_on_adjudicated_only.scoped, null);
    assert.deepEqual(unreviewed.generated.map((row) => row.variant), ["L858R"]);

    const goldFile = path.join(dir, "gold.json");
    const gold = [{ id: "q1", review_status: "adjudicated", reviewed_by: ["reviewer1", "reviewer2"],
      snapshot_sha256: unreviewed.report.snapshot_sha256, verified_evidence_ids: ["101"],
      primary_publications: ["https://pubmed.ncbi.nlm.nih.gov/12345/"] }];
    fs.writeFileSync(goldFile, JSON.stringify(gold));
    const reviewed = evaluate({ ...args, goldFile });
    assert.equal(reviewed.report.metrics_on_adjudicated_only.baseline.precision, 0.5);
    assert.equal(reviewed.report.metrics_on_adjudicated_only.scoped.precision, 1);
    gold[0].snapshot_sha256 = { ...gold[0].snapshot_sha256, "relations.json": "wrong" };
    fs.writeFileSync(goldFile, JSON.stringify(gold));
    assert.throws(() => evaluate({ ...args, goldFile }), /snapshot-mismatched/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
