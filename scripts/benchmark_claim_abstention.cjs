#!/usr/bin/env node
// A 100-question source-consistency stress test, NOT independent clinical gold.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { buildEvidenceTree } = require("../web/evidence-tree.js");
const { evaluateEvidenceClaim } = require("../web/claim-evidence.js");
const { contextBlindIds } = require("./evaluate_variant_questions.cjs");

const normal = (value) => String(value || "").trim().toLowerCase();
function context(row) {
  if (row.context && typeof row.context === "object") return row.context;
  try { return JSON.parse(row.context || "{}"); } catch { return {}; }
}
function memberName(member, gene) {
  const value = String(member).trim();
  return normal(value).startsWith(`${normal(gene)} `) ? value.slice(gene.length + 1) : value;
}
function key(q) {
  return [q.gene, q.variant, q.disease, q.therapy, q.effect].map(normal).join("|");
}

// Independently enumerate upstream-shaped CIViC records (before calling either
// retrieval method). This reference is still source-derived, not expert gold.
function readSourceRecords(entities, relations) {
  const byId = new Map(entities.map((entity) => [String(entity.id), entity]));
  const rows = [];
  const inspected = { clinical_relations: 0, drug_disease_relations: 0, civic_items: 0,
    accepted_items: 0, predictive_items: 0, valid_effect_items: 0, variant_member_items: 0 };
  for (const relation of relations) {
    if (relation.predicate !== "clinically_evidenced_for") continue;
    inspected.clinical_relations++;
    const drug = byId.get(String(relation.subject_id));
    const cancer = byId.get(String(relation.object_id));
    if (normal(drug?.type) !== "drug" || normal(cancer?.type) !== "disease") continue;
    inspected.drug_disease_relations++;
    for (const item of relation.evidence || []) {
      const ctx = context(item);
      if (normal(item.source) !== "civic") continue;
      inspected.civic_items++;
      if (ctx.civic_review_status !== "ACCEPTED") continue;
      inspected.accepted_items++;
      if (normal(ctx.civic_evidence_type) !== "predictive") continue;
      inspected.predictive_items++;
      if (!["sensitivity", "resistance"].includes(normal(ctx.significance))) continue;
      inspected.valid_effect_items++;
      if (!ctx.civic_evidence_id || !ctx.gene_name || !Array.isArray(ctx.profile_variants)) continue;
      inspected.variant_member_items++;
      rows.push({ id: String(ctx.civic_evidence_id), gene: String(ctx.gene_name),
        members: ctx.profile_variants.map((member) => memberName(member, ctx.gene_name)),
        disease: cancer.name, therapy: drug.name, effect: normal(ctx.significance),
        direction: normal(item.claim_state) });
    }
  }
  return { rows, byId, inspected };
}

function referenceIndex(records) {
  const index = new Map();
  for (const row of records) {
    if (row.members.length !== 1) continue;
    const base = [row.gene, row.members[0], row.disease, row.therapy].map(normal).join("|");
    if (!index.has(base)) index.set(base, []);
    index.get(base).push(row);
  }
  return index;
}
function sourceReference(q, recordsOrIndex) {
  const supporting = new Set(), opposing = new Set(), disputed = new Set();
  const index = recordsOrIndex instanceof Map ? recordsOrIndex : referenceIndex(recordsOrIndex);
  const base = [q.gene, q.variant, q.disease, q.therapy].map(normal).join("|");
  for (const row of index.get(base) || []) {
    if (row.direction === "supports" && row.effect === q.effect) supporting.add(row.id);
    else if (row.direction === "supports") opposing.add(row.id);
    else if (row.direction === "contradicts" && row.effect === q.effect) disputed.add(row.id);
  }
  return { answerable: supporting.size > 0 && !opposing.size && !disputed.size,
    supporting_eids: [...supporting].sort(), opposing_count: opposing.size, disputed_count: disputed.size };
}

function makeQuestions(records, count = 100) {
  if (!Number.isInteger(count) || count < 1 || count > 1000) throw Error("Invalid question count");
  const ordered = records.filter((row) => row.members.length === 1 && row.direction === "supports")
    .sort((a, b) => [a.gene, a.disease, a.therapy, a.members[0], a.effect, a.id].join("|")
      .localeCompare([b.gene, b.disease, b.therapy, b.members[0], b.effect, b.id].join("|")));
  if (!ordered.length) throw Error("No eligible accepted CIViC predictive records in snapshot");
  const genes = new Map();
  for (const row of ordered) {
    if (!genes.has(row.gene)) genes.set(row.gene, []);
    genes.get(row.gene).push(row);
  }
  const seed = [];
  while (seed.length < 300 && [...genes.values()].some((list) => list.length)) {
    for (const list of genes.values()) if (list.length && seed.length < 300) seed.push(list.shift());
  }
  const index = referenceIndex(records);
  const variantsByGene = new Map();
  for (const row of records) for (const member of row.members) {
    if (!variantsByGene.has(row.gene)) variantsByGene.set(row.gene, new Set());
    variantsByGene.get(row.gene).add(member);
  }
  const therapies = [...new Set(records.map((row) => row.therapy))].sort();
  const cancers = [...new Set(records.map((row) => row.disease))].sort();
  const pools = Object.fromEntries(["direct", "other_variant", "other_therapy", "other_cancer",
    "opposite_effect", "complex_profile"].map((name) => [name, new Map()]));
  const add = (category, q, expected) => {
    if (pools[category].size >= 250) return;
    const reference = sourceReference(q, index);
    if (reference.answerable !== expected) return;
    const id = key(q);
    if (!pools[category].has(id)) pools[category].set(id, { ...q, category, reference });
  };
  // These are perturbations of real source rows. Negatives are checked
  // against the full available source record set, never presumed absent.
  for (const row of seed) {
    const base = { gene: row.gene, variant: row.members[0], disease: row.disease,
      therapy: row.therapy, effect: row.effect };
    add("direct", base, true);
    add("opposite_effect", { ...base, effect: row.effect === "sensitivity" ? "resistance" : "sensitivity" }, false);
    for (const variant of [...(variantsByGene.get(row.gene) || [])].slice(0, 15)) {
      if (normal(variant) !== normal(base.variant)) add("other_variant", { ...base, variant }, false);
    }
    for (const therapy of therapies.slice(0, 20)) {
      if (normal(therapy) !== normal(base.therapy)) add("other_therapy", { ...base, therapy }, false);
    }
    for (const disease of cancers.slice(0, 20)) {
      if (normal(disease) !== normal(base.disease)) add("other_cancer", { ...base, disease }, false);
    }
  }
  for (const row of records.filter((item) => item.members.length > 1)) {
    for (const variant of row.members) {
      add("complex_profile", { gene: row.gene, variant, disease: row.disease,
        therapy: row.therapy, effect: row.effect }, false);
    }
  }
  const quotas = { direct: 25, other_variant: 20, other_therapy: 20,
    other_cancer: 15, opposite_effect: 10, complex_profile: 10 };
  const selected = new Map();
  for (const [category, size] of Object.entries(quotas)) {
    for (const [id, q] of [...pools[category]].slice(0, size)) if (!selected.has(id)) selected.set(id, q);
  }
  // Rare source distributions can lack a category. Fill the remainder
  // deterministically and report actual category counts instead of faking it.
  for (const category of Object.keys(pools)) {
    for (const [id, q] of pools[category]) {
      if (selected.size >= count) break;
      if (!selected.has(id)) selected.set(id, q);
    }
  }
  if (selected.size < count) throw Error(`Only ${selected.size} unique eligible questions; need ${count}`);
  return [...selected.values()].slice(0, count).map((q, i) => ({ id: `claim-${String(i + 1).padStart(3, "0")}`,
    question: `In ${q.disease}, do accepted CIViC records report ${q.effect} for ${q.gene} ${q.variant} with ${q.therapy}?`, ...q }));
}

function metrics(results, strategy) {
  const valid = results.filter((row) => !row.tree_truncated);
  const positive = valid.filter((row) => row.reference.answerable);
  const negative = valid.filter((row) => !row.reference.answerable);
  const saidYes = valid.filter((row) => row.predictions[strategy].answers);
  const trueYes = positive.filter((row) => row.predictions[strategy].answers);
  const falseYes = negative.filter((row) => row.predictions[strategy].answers);
  return { evaluated_count: valid.length, source_answerable_count: positive.length,
    source_unanswerable_count: negative.length, answered_count: saidYes.length,
    answer_coverage: valid.length ? saidYes.length / valid.length : null,
    answer_rate_on_answerable: positive.length ? trueYes.length / positive.length : null,
    false_answer_rate_on_unanswerable: negative.length ? falseYes.length / negative.length : null,
    selective_error_among_answers: saidYes.length ? falseYes.length / saidYes.length : null };
}

function evaluate(entities, relations, count = 100) {
  const { rows: source, byId, inspected } = readSourceRecords(entities, relations);
  if (!source.length) throw Error(`No eligible source records: civic=${inspected.civic_items} accepted=${inspected.accepted_items} predictive=${inspected.predictive_items} effect=${inspected.valid_effect_items} members=${inspected.variant_member_items} clinical=${inspected.clinical_relations}`);
  const questions = makeQuestions(source, count);
  const results = questions.map((q) => {
    const tree = buildEvidenceTree(entities, relations, { gene: q.gene,
      variant: q.variant, disease: q.disease, limit: 200 });
    const claim = evaluateEvidenceClaim(tree, { therapy: q.therapy, effect: q.effect, limit: 200 });
    const blindIds = contextBlindIds(q, relations, byId);
    const scopedIds = tree.evidence.filter((item) => item.therapies.some((drug) =>
      normal(drug.name) === normal(q.therapy))).map((item) => item.evidence_id);
    return { id: q.id, category: q.category, question: q.question,
      query: { gene: q.gene, variant: q.variant, disease: q.disease,
        therapy: q.therapy, effect: q.effect },
      reference: q.reference, tree_truncated: tree.truncated,
      predictions: { context_blind: { answers: blindIds.length > 0, evidence_ids: blindIds },
        variant_only: { answers: scopedIds.length > 0 && !tree.truncated, evidence_ids: scopedIds },
        claim_scoped: { answers: claim.status === "supporting_records", status: claim.status,
          evidence_ids: claim.evidence.supporting.map((item) => item.evidence_id) } } };
  });
  return { methodology: "source-derived controlled perturbation; not independent clinical gold or LLM evaluation",
    question_count: results.length,
    categories: Object.fromEntries(Object.keys({ direct: 1, other_variant: 1, other_therapy: 1,
      other_cancer: 1, opposite_effect: 1, complex_profile: 1 }).map((category) =>
      [category, results.filter((row) => row.category === category).length])),
    truncated_count: results.filter((row) => row.tree_truncated).length,
    metrics: Object.fromEntries(["context_blind", "variant_only", "claim_scoped"].map((strategy) =>
      [strategy, metrics(results, strategy)])), questions: results };
}

if (require.main === module) {
  const args = process.argv.slice(2);
  const value = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
  const dir = value("--snapshot", "web/data");
  const out = value("--out", "claim-benchmark");
  const count = Number(value("--questions", "100"));
  const names = ["search-index.json", "relations.json"];
  const raw = names.map((name) => fs.readFileSync(path.join(dir, name)));
  const report = evaluate(...raw.map((item) => JSON.parse(item.toString("utf8"))), count);
  report.snapshot_sha256 = Object.fromEntries(names.map((name, i) =>
    [name, crypto.createHash("sha256").update(raw[i]).digest("hex")]));
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ question_count: report.question_count,
    categories: report.categories, truncated_count: report.truncated_count,
    metrics: report.metrics, snapshot_sha256: report.snapshot_sha256 }, null, 2) + "\n");
}

module.exports = { evaluate, makeQuestions, readSourceRecords, sourceReference };
