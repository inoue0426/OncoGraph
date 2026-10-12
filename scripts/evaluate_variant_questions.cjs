#!/usr/bin/env node
// Reproducible retrieval comparison. Claims of biomedical accuracy require an
// independently adjudicated, snapshot-matched gold file; the review queue is not gold.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { buildEvidenceTree } = require("../web/evidence-tree.js");

const normal = (value) => String(value ?? "").trim().toLocaleLowerCase();
function context(item) {
  if (typeof item.context === "object" && item.context) return item.context;
  try { return JSON.parse(item.context || "{}"); } catch { return {}; }
}
function readSnapshot(dir) {
  const names = ["search-index.json", "relations.json"];
  const files = names.map((name) => fs.readFileSync(path.join(dir, name)));
  const [entities, relations] = files.map((file) => JSON.parse(file.toString("utf8")));
  if (!Array.isArray(entities) || !Array.isArray(relations)) throw Error("Invalid snapshot arrays");
  const hashes = Object.fromEntries(names.map((name, i) =>
    [name, crypto.createHash("sha256").update(files[i]).digest("hex")]));
  return { entities, relations, hashes };
}

// This baseline looks at the same accepted CIViC drug, disease and gene
// evidence, but ignores the molecular profile. It is an explicit ablation.
function contextBlindIds(item, relations, byId) {
  const ids = new Set();
  for (const relation of relations) {
    if (relation.predicate !== "clinically_evidenced_for") continue;
    const drug = byId.get(String(relation.subject_id));
    const disease = byId.get(String(relation.object_id));
    if (normal(drug?.name) !== normal(item.therapy) || normal(disease?.name) !== normal(item.disease)) continue;
    for (const evidence of relation.evidence || []) {
      const ctx = context(evidence);
      if (normal(evidence.source) === "civic" && ctx.civic_review_status === "ACCEPTED" &&
          normal(ctx.gene_name) === normal(item.gene) && ctx.civic_evidence_id != null) {
        ids.add(String(ctx.civic_evidence_id));
      }
    }
  }
  return [...ids].sort();
}

function scopedIds(item, entities, relations) {
  const tree = buildEvidenceTree(entities, relations,
    { gene: item.gene, variant: item.variant, disease: item.disease, limit: 200 });
  if (tree.truncated) return { ids: null, truncated: true };
  const ids = tree.evidence.filter((row) => row.therapies.some((drug) =>
    normal(drug.name) === normal(item.therapy))).map((row) => String(row.evidence_id));
  return { ids: [...new Set(ids)].sort(), truncated: false };
}

function generatedCandidates(existing, relations, byId, limit = 20) {
  const taken = new Set(existing.map((row) => [row.gene, row.variant, row.disease, row.therapy]
    .map(normal).join("|")));
  const candidates = new Map();
  for (const relation of relations) {
    if (relation.predicate !== "clinically_evidenced_for") continue;
    const drug = byId.get(String(relation.subject_id));
    const disease = byId.get(String(relation.object_id));
    if (normal(drug?.type) !== "drug" || normal(disease?.type) !== "disease") continue;
    for (const evidence of relation.evidence || []) {
      const ctx = context(evidence);
      if (normal(evidence.source) !== "civic" || ctx.civic_review_status !== "ACCEPTED" ||
          !ctx.civic_evidence_id || !ctx.gene_name || !Array.isArray(ctx.profile_variants)) continue;
      for (const member of ctx.profile_variants) {
        if (typeof member !== "string" || !member.trim()) continue;
        const variant = normal(member).startsWith(`${normal(ctx.gene_name)} `)
          ? member.trim().slice(ctx.gene_name.length + 1) : member.trim();
        const values = { gene: ctx.gene_name, variant, disease: disease.name, therapy: drug.name };
        const key = Object.values(values).map(normal).join("|");
        if (!taken.has(key) && !candidates.has(key)) {
          candidates.set(key, { ...values, review_status: "pending", gold_answer: null,
            verified_evidence_ids: [], primary_publications: [], reviewed_by: [],
            source_evidence_hint: String(ctx.civic_evidence_id),
            source_url_hint: evidence.source_url || null,
            complex_profile_hint: ctx.profile_variants.length > 1 });
        }
      }
    }
  }
  // Deterministic round-robin across genes to keep one gene from filling the set.
  const groups = new Map();
  for (const candidate of [...candidates.values()].sort((a, b) =>
    [a.gene, a.disease, a.variant, a.therapy].join("|").localeCompare(
      [b.gene, b.disease, b.variant, b.therapy].join("|")))) {
    if (!groups.has(candidate.gene)) groups.set(candidate.gene, []);
    groups.get(candidate.gene).push(candidate);
  }
  const chosen = [];
  while (chosen.length < limit && [...groups.values()].some((group) => group.length)) {
    for (const group of groups.values()) {
      if (group.length && chosen.length < limit) chosen.push(group.shift());
    }
  }
  return chosen.map((row, i) => ({ id: `snapshot-review-${String(i + 1).padStart(2, "0")}`,
    question: `What accepted CIViC evidence in this snapshot links ${row.gene} ${row.variant} in ${row.disease} with ${row.therapy}?`,
    ...row }));
}

function loadReviewedGold(filename, hashes) {
  const rows = filename ? JSON.parse(fs.readFileSync(filename, "utf8")) : [];
  if (!Array.isArray(rows)) throw Error("Gold must be a JSON array");
  const gold = new Map();
  for (const row of rows) {
    if (row.review_status !== "adjudicated" || !row.id || gold.has(row.id) ||
        !Array.isArray(row.reviewed_by) || new Set(row.reviewed_by).size < 2 ||
        !Array.isArray(row.verified_evidence_ids) ||
        row.snapshot_sha256?.["search-index.json"] !== hashes["search-index.json"] ||
        row.snapshot_sha256?.["relations.json"] !== hashes["relations.json"] ||
        (row.verified_evidence_ids.length && !row.primary_publications?.length) ||
        (!row.verified_evidence_ids.length && row.negative_checked_in_snapshot !== true)) {
      throw Error(`Unadjudicated or snapshot-mismatched gold row: ${row.id || "unknown"}`);
    }
    gold.set(row.id, row);
  }
  return gold;
}

function score(prediction, goldIds) {
  if (prediction === null) return null;
  const expected = new Set(goldIds.map(String));
  const predicted = new Set(prediction);
  const hit = [...predicted].filter((id) => expected.has(id)).length;
  const precision = predicted.size ? hit / predicted.size : expected.size ? 0 : 1;
  const recall = expected.size ? hit / expected.size : predicted.size ? 0 : 1;
  return { precision, recall, f1: precision + recall ? 2 * precision * recall / (precision + recall) : 0,
    exact: predicted.size === expected.size && hit === expected.size ? 1 : 0 };
}
function summarize(rows, method) {
  const scored = rows.map((row) => row.scores?.[method]).filter(Boolean);
  if (!scored.length) return null;
  return Object.fromEntries(["precision", "recall", "f1", "exact"].map((metric) =>
    [metric, scored.reduce((sum, row) => sum + row[metric], 0) / scored.length]));
}

function evaluate({ snapshotDir, queueFile, goldFile, candidateLimit = 20 }) {
  const { entities, relations, hashes } = readSnapshot(snapshotDir);
  const queue = JSON.parse(fs.readFileSync(queueFile, "utf8"));
  if (!Array.isArray(queue) || queue.some((row) =>
    !row.id || !["gene", "variant", "disease", "therapy"].every((key) => typeof row[key] === "string"))) {
    throw Error("Invalid review queue");
  }
  const byId = new Map(entities.map((entity) => [String(entity.id), entity]));
  const generated = generatedCandidates(queue, relations, byId, candidateLimit);
  const questions = [...queue, ...generated];
  const gold = loadReviewedGold(goldFile, hashes);
  for (const id of gold.keys()) if (!questions.some((row) => row.id === id)) throw Error(`Unknown gold id: ${id}`);
  const rows = questions.map((item) => {
    const baseline = contextBlindIds(item, relations, byId);
    const scoped = scopedIds(item, entities, relations);
    const reviewed = gold.get(item.id);
    return { id: item.id, baseline_evidence_ids: baseline, scoped_evidence_ids: scoped.ids,
      scoped_truncated: scoped.truncated, review_status: reviewed ? "adjudicated" : "pending",
      ...(reviewed ? { verified_evidence_ids: reviewed.verified_evidence_ids,
        scores: { baseline: score(baseline, reviewed.verified_evidence_ids),
          scoped: score(scoped.ids, reviewed.verified_evidence_ids) } } : {}) };
  });
  return { report: { experiment: "variant-conditioned retrieval vs context-blind CIViC ablation",
    snapshot_sha256: hashes, candidate_count: questions.length, prewritten_count: queue.length,
    snapshot_generated_count: generated.length, adjudicated_count: gold.size,
    note: "Unreviewed predictions and source-derived candidates are diagnostics, not clinical accuracy or independent gold.",
    metrics_on_adjudicated_only: { baseline: summarize(rows, "baseline"), scoped: summarize(rows, "scoped") },
    questions: rows }, generated };
}

if (require.main === module) {
  const args = process.argv.slice(2);
  const option = (flag, fallback) => {
    const i = args.indexOf(flag);
    return i < 0 ? fallback : args[i + 1];
  };
  const snapshotDir = option("--snapshot", "web/data");
  const queueFile = option("--queue", "data/benchmarks/variant_review_queue.json");
  const goldFile = option("--gold", null);
  const out = option("--out", "variant-evaluation");
  const limit = Number(option("--new-candidates", "20"));
  if (!Number.isInteger(limit) || limit < 0 || limit > 100) throw Error("Invalid candidate limit");
  const { report, generated } = evaluate({ snapshotDir, queueFile, goldFile, candidateLimit: limit });
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2) + "\n");
  fs.writeFileSync(path.join(out, "review_candidates.json"), JSON.stringify(generated, null, 2) + "\n");
  process.stdout.write(`Evaluated ${report.candidate_count} questions; ${report.adjudicated_count} adjudicated. ` +
    `Report: ${path.join(out, "report.json")}\n`);
}

module.exports = { evaluate, generatedCandidates, loadReviewedGold, contextBlindIds, score };
