const search = document.querySelector("#search");
const status = document.querySelector("#status");
const results = document.querySelector("#results");
const detail = document.querySelector("#detail");
const attribution = document.querySelector("#attribution");

const TRIAL_DISCLAIMER = "Trial registration does not imply efficacy or approval.";

let entities = [];
let entityById = new Map();
let outByPredicate = new Map(); // subjectId -> Map(predicate -> [{objectId, evidence}])
let inByPredicate = new Map(); // objectId -> Map(predicate -> [{subjectId, evidence}])
let entitiesByType = new Map(); // type -> [entity, ...]

const PREDICATE_LABELS = {
  targets: "Targets",
  studied_in: "Clinical trials",
  associated_with: "Associated diseases (computed, unverified)",
  indicated_for: "Indicated for (approved)",
  is_a: "Is a",
};

const TYPE_LABELS = {
  drug: "Drug",
  gene: "Gene",
  target: "Target",
  disease: "Disease",
  trial: "Trial",
  go_term: "GO term",
};

// Recognized "what kind of thing do you want back" words in a search query.
// Deliberately small and literal -- this is rule-based intent detection, not NLP.
const TYPE_KEYWORDS = {
  drug: "drug",
  drugs: "drug",
  medication: "drug",
  medications: "drug",
  trial: "trial",
  trials: "trial",
  study: "trial",
  studies: "trial",
  gene: "gene",
  genes: "gene",
  target: "gene",
  targets: "gene",
};

const TIER_ORDER = ["approved", "clinical_trial", "target_association", "gene_target"];
const TIER_LABELS = {
  approved: "Approved indication",
  clinical_trial: "Clinical trial",
  target_association: "Target-disease association",
  gene_target: "Gene target",
};

const SOURCE_ATTRIBUTIONS = [
  {
    sources: ["gtopdb"],
    text:
      'Approved-drug/target data from the <a href="https://www.guidetopharmacology.org/">IUPHAR/BPS Guide to PHARMACOLOGY (GtoPdb)</a>: database licensed under ODbL, content licensed under CC BY-SA 4.0.',
  },
  {
    sources: ["clinicaltrials_gov"],
    text:
      'Trial registry metadata from <a href="https://clinicaltrials.gov/">ClinicalTrials.gov</a>.',
  },
  {
    sources: ["open_targets", "open_targets_indications"],
    text:
      'Target-disease associations and approved drug indications from the <a href="https://platform.opentargets.org/">Open Targets Platform</a> (CC0).',
  },
];

function predicateLabel(predicate) {
  return PREDICATE_LABELS[predicate] || predicate;
}

function typeLabel(type) {
  return TYPE_LABELS[type] || type;
}

function indexRelations(relations) {
  const out = new Map();
  const inc = new Map();
  for (const relation of relations) {
    if (!out.has(relation.subject_id)) out.set(relation.subject_id, new Map());
    const outPredicates = out.get(relation.subject_id);
    if (!outPredicates.has(relation.predicate)) outPredicates.set(relation.predicate, []);
    outPredicates
      .get(relation.predicate)
      .push({ objectId: relation.object_id, evidence: relation.evidence || [] });

    if (!inc.has(relation.object_id)) inc.set(relation.object_id, new Map());
    const inPredicates = inc.get(relation.object_id);
    if (!inPredicates.has(relation.predicate)) inPredicates.set(relation.predicate, []);
    inPredicates
      .get(relation.predicate)
      .push({ subjectId: relation.subject_id, evidence: relation.evidence || [] });
  }
  return { out, inc };
}

function outgoing(entityId, predicate) {
  return outByPredicate.get(entityId)?.get(predicate) || [];
}

function incoming(entityId, predicate) {
  return inByPredicate.get(entityId)?.get(predicate) || [];
}

function evidenceContextValue(evidence, key) {
  for (const item of evidence) {
    const value = item.context?.[key];
    if (value !== undefined && value !== null) return value;
  }
  return null;
}

function firstSourceUrl(evidence) {
  return evidence.find((item) => item.source_url)?.source_url || null;
}

function sourceBadgeText(evidence) {
  const item = evidence.find((entry) => entry.source);
  if (!item) return null;
  return item.source_id ? `${item.source} · ${item.source_id}` : item.source;
}

// --- Intent parsing -------------------------------------------------------

function parseIntent(rawQuery) {
  const words = rawQuery.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return { resultType: null, remainder: "", entityMatch: null };

  let typeIndex = -1;
  let resultType = null;
  for (let i = words.length - 1; i >= 0; i--) {
    const mapped = TYPE_KEYWORDS[words[i].toLowerCase()];
    if (mapped) {
      typeIndex = i;
      resultType = mapped;
      break;
    }
  }

  if (typeIndex === -1) {
    return { resultType: null, remainder: rawQuery.trim(), entityMatch: null };
  }

  const remainder = words.filter((_, i) => i !== typeIndex).join(" ").trim();
  if (!remainder) {
    return { resultType: null, remainder: rawQuery.trim(), entityMatch: null };
  }

  return { resultType, remainder, entityMatch: resolveEntityMatch(remainder) };
}

function resolveEntityMatch(remainder) {
  const lower = remainder.toLowerCase();
  if (!lower) return null;

  const genes = entitiesByType.get("gene") || [];
  const diseases = entitiesByType.get("disease") || [];
  const drugs = entitiesByType.get("drug") || [];

  const exact = (list) => list.filter((e) => e.name.toLowerCase() === lower);

  let matches = exact(genes);
  if (matches.length) return { kind: "gene", entities: matches };
  matches = exact(diseases);
  if (matches.length) return { kind: "disease", entities: matches };
  matches = exact(drugs);
  if (matches.length) return { kind: "drug", entities: matches };

  if (lower.length >= 4) {
    const contains = (list) => list.filter((e) => e.name.toLowerCase().includes(lower));
    matches = contains(diseases);
    if (matches.length) return { kind: "disease", entities: matches.slice(0, 10) };
    matches = contains(genes);
    if (matches.length) return { kind: "gene", entities: matches.slice(0, 10) };
  }

  return null;
}

// --- Evidence-tier result assembly ----------------------------------------

function addTier(map, drugId, tier, payload) {
  if (!map.has(drugId)) map.set(drugId, {});
  const tiers = map.get(drugId);
  if (!tiers[tier]) tiers[tier] = [];
  tiers[tier].push(payload);
}

function drugsForDisease(diseaseEntities) {
  const drugMap = new Map();
  for (const disease of diseaseEntities) {
    for (const edge of incoming(disease.id, "indicated_for")) {
      addTier(drugMap, edge.subjectId, "approved", { disease, evidence: edge.evidence });
    }
    for (const assoc of incoming(disease.id, "associated_with")) {
      const gene = entityById.get(assoc.subjectId);
      if (!gene) continue;
      for (const targetsEdge of incoming(gene.id, "targets")) {
        addTier(drugMap, targetsEdge.subjectId, "target_association", {
          disease,
          gene,
          score: evidenceContextValue(assoc.evidence, "score"),
          // The evidence for *this* claim (gene-disease association) is the
          // Open Targets association edge, not the GtoPdb drug-target edge.
          evidence: assoc.evidence,
        });
      }
    }
  }
  return drugMap;
}

function drugsStudiedForPhrase(phrase) {
  const drugMap = new Map();
  const lower = phrase.toLowerCase();
  for (const trial of entitiesByType.get("trial") || []) {
    if (!trial.description || !trial.description.toLowerCase().includes(lower)) continue;
    for (const edge of incoming(trial.id, "studied_in")) {
      addTier(drugMap, edge.subjectId, "clinical_trial", { trial, evidence: edge.evidence });
    }
  }
  return drugMap;
}

function mergeDrugMaps(...maps) {
  const merged = new Map();
  for (const map of maps) {
    for (const [drugId, tiers] of map) {
      if (!merged.has(drugId)) merged.set(drugId, {});
      const target = merged.get(drugId);
      for (const tier of Object.keys(tiers)) {
        target[tier] = (target[tier] || []).concat(tiers[tier]);
      }
    }
  }
  return merged;
}

function drugsForGeneTarget(geneEntities) {
  const drugMap = new Map();
  for (const gene of geneEntities) {
    for (const edge of incoming(gene.id, "targets")) {
      addTier(drugMap, edge.subjectId, "gene_target", { gene, evidence: edge.evidence });
    }
  }
  return drugMap;
}

function trialsForPhrase(phrase) {
  const lower = phrase.toLowerCase();
  return (entitiesByType.get("trial") || []).filter(
    (trial) => trial.description && trial.description.toLowerCase().includes(lower),
  );
}

function bestTierRank(tiers) {
  return TIER_ORDER.findIndex((tier) => tiers[tier]);
}

function computeIntentResults(intent) {
  const { resultType, remainder, entityMatch } = intent;

  if (resultType === "drug" && entityMatch?.kind === "disease") {
    const drugMap = mergeDrugMaps(
      drugsForDisease(entityMatch.entities),
      drugsStudiedForPhrase(remainder),
    );
    return {
      kind: "drugs",
      drugs: [...drugMap.entries()]
        .map(([id, tiers]) => ({ entity: entityById.get(id), tiers }))
        .filter((row) => row.entity)
        .sort((a, b) => bestTierRank(a.tiers) - bestTierRank(b.tiers)),
    };
  }

  if (resultType === "drug" && entityMatch?.kind === "gene") {
    const drugMap = drugsForGeneTarget(entityMatch.entities);
    return {
      kind: "drugs",
      drugs: [...drugMap.entries()]
        .map(([id, tiers]) => ({ entity: entityById.get(id), tiers }))
        .filter((row) => row.entity)
        .sort((a, b) => bestTierRank(a.tiers) - bestTierRank(b.tiers)),
    };
  }

  if (resultType === "trial") {
    return { kind: "trials", trials: trialsForPhrase(remainder) };
  }

  return null;
}

// --- Rendering: evidence-tier cards ---------------------------------------

function renderEvidenceItem(tier, item) {
  const li = document.createElement("li");

  const label = document.createElement("span");
  if (tier === "approved") {
    label.textContent = `Indicated for ${item.disease.name}`;
  } else if (tier === "clinical_trial") {
    label.textContent = item.trial.name;
  } else if (tier === "target_association") {
    label.textContent = `via ${item.gene.name} → ${item.disease.name}`;
  } else {
    label.textContent = `Targets ${item.gene.name}`;
  }
  li.append(label);

  if (tier === "approved") {
    const stage = evidenceContextValue(item.evidence, "max_clinical_stage");
    if (stage) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = stage;
      li.append(badge);
    }
  }

  if (tier === "clinical_trial") {
    const status = evidenceContextValue(item.evidence, "overall_status");
    const phases = evidenceContextValue(item.evidence, "phases");
    if (status) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = status;
      li.append(badge);
    }
    if (Array.isArray(phases) && phases.length) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = phases.join(", ");
      li.append(badge);
    }
    const nctBadge = document.createElement("span");
    nctBadge.className = "badge";
    nctBadge.textContent = item.trial.canonical_id || "no NCT ID";
    li.append(nctBadge);
  }

  if (tier === "target_association" && typeof item.score === "number") {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = `score ${item.score.toFixed(2)}`;
    li.append(badge);
  }

  const sourceText = sourceBadgeText(item.evidence);
  if (sourceText) {
    const badge = document.createElement("span");
    badge.className = "badge source";
    badge.textContent = sourceText;
    li.append(badge);
  }

  const sourceUrl = firstSourceUrl(item.evidence);
  if (sourceUrl) {
    const link = document.createElement("a");
    link.href = sourceUrl;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "source ↗";
    li.append(link);
  }

  return li;
}

function renderDrugCard(row) {
  const card = document.createElement("article");
  card.className = "intent-card";
  card.dataset.id = row.entity.id;

  const name = document.createElement("strong");
  name.textContent = row.entity.name;
  const idBadge = document.createElement("span");
  idBadge.className = "badge";
  idBadge.textContent = row.entity.canonical_id || "no canonical ID";
  card.append(name, idBadge);

  for (const tier of TIER_ORDER) {
    const items = row.tiers[tier];
    if (!items || !items.length) continue;

    const section = document.createElement("div");
    section.className = `tier tier-${tier}`;
    const heading = document.createElement("div");
    heading.className = "tier-label";
    heading.textContent = TIER_LABELS[tier];
    section.append(heading);

    const list = document.createElement("ul");
    for (const item of items) list.append(renderEvidenceItem(tier, item));
    section.append(list);

    if (tier === "clinical_trial") {
      const disclaimer = document.createElement("p");
      disclaimer.className = "disclaimer";
      disclaimer.textContent = TRIAL_DISCLAIMER;
      section.append(disclaimer);
    }

    card.append(section);
  }

  return card;
}

function renderTrialCard(trial) {
  const card = document.createElement("article");
  card.className = "intent-card";
  card.dataset.id = trial.id;

  const name = document.createElement("strong");
  name.textContent = trial.name;
  const idBadge = document.createElement("span");
  idBadge.className = "badge";
  idBadge.textContent = trial.canonical_id || "no NCT ID";
  card.append(name, idBadge);

  const studiedEdges = incoming(trial.id, "studied_in");
  const firstEvidence = studiedEdges[0]?.evidence || [];
  const status = evidenceContextValue(firstEvidence, "overall_status");
  const phases = evidenceContextValue(firstEvidence, "phases");
  if (status) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = status;
    card.append(badge);
  }
  if (Array.isArray(phases) && phases.length) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = phases.join(", ");
    card.append(badge);
  }

  if (trial.description) {
    const conditions = document.createElement("div");
    conditions.className = "meta";
    conditions.textContent = trial.description;
    card.append(conditions);
  }

  if (studiedEdges.length) {
    const drugsLine = document.createElement("div");
    drugsLine.className = "meta";
    drugsLine.textContent =
      "Intervention drug(s): " +
      studiedEdges
        .map((edge) => entityById.get(edge.subjectId)?.name)
        .filter(Boolean)
        .join(", ");
    card.append(drugsLine);
  }

  const sourceUrl = firstSourceUrl(studiedEdges[0]?.evidence || []);
  if (sourceUrl) {
    const link = document.createElement("a");
    link.href = sourceUrl;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "source ↗";
    card.append(link);
  }

  const disclaimer = document.createElement("p");
  disclaimer.className = "disclaimer";
  disclaimer.textContent = TRIAL_DISCLAIMER;
  card.append(disclaimer);

  return card;
}

function coverageSummary() {
  const count = (type) => (entitiesByType.get(type) || []).length;
  return (
    `Currently indexed: ${count("drug")} drugs, ${count("gene")} genes/targets, ` +
    `${count("disease")} diseases, ${count("trial")} trials.`
  );
}

function renderIntentHeader(intent) {
  const header = document.createElement("p");
  header.className = "intent-header";
  const kindLabel = intent.entityMatch ? typeLabel(intent.entityMatch.kind) : "term";
  const target = intent.resultType ? typeLabel(intent.resultType) : "entity";
  header.textContent = `Interpreted "${intent.remainder}" as ${kindLabel} → looking for ${target}`;
  return header;
}

function renderIntentEmpty(intent) {
  const container = document.createElement("div");
  container.append(renderIntentHeader(intent));
  const message = document.createElement("p");
  message.className = "empty";
  message.textContent = intent.entityMatch
    ? `No ${typeLabel(intent.resultType)} evidence indexed for this yet.`
    : `Could not match "${intent.remainder}" to a known disease or gene.`;
  container.append(message);
  const coverage = document.createElement("p");
  coverage.className = "empty";
  coverage.textContent = coverageSummary();
  container.append(coverage);
  return container;
}

// --- Existing full-detail view (unchanged behavior for direct entity search) -

function diseasesViaTargets(drugId) {
  const best = new Map();
  for (const target of outgoing(drugId, "targets")) {
    for (const assoc of outgoing(target.objectId, "associated_with")) {
      const score = evidenceContextValue(assoc.evidence, "score") ?? 0;
      const existing = best.get(assoc.objectId);
      if (!existing || score > existing.score) {
        best.set(assoc.objectId, { objectId: assoc.objectId, evidence: assoc.evidence, score });
      }
    }
  }
  return [...best.values()].sort((a, b) => b.score - a.score).slice(0, 20);
}

function renderGroup(predicate, items) {
  const group = document.createElement("div");
  group.className = "group";

  const heading = document.createElement("h3");
  heading.textContent = `${predicateLabel(predicate)} (${items.length})`;
  group.append(heading);

  const list = document.createElement("ul");
  for (const item of items) {
    const target = entityById.get(item.objectId);
    if (!target) continue;

    const li = document.createElement("li");

    const pivot = document.createElement("button");
    pivot.type = "button";
    pivot.className = "pivot";
    pivot.dataset.id = target.id;
    pivot.textContent = target.name;
    li.append(pivot);

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = typeLabel(target.type);
    li.append(badge);

    const score = item.score ?? evidenceContextValue(item.evidence, "score");
    if (typeof score === "number") {
      const scoreBadge = document.createElement("span");
      scoreBadge.className = "badge";
      scoreBadge.textContent = `score ${score.toFixed(2)}`;
      li.append(scoreBadge);
    }

    const stage = evidenceContextValue(item.evidence, "max_clinical_stage");
    if (stage) {
      const stageBadge = document.createElement("span");
      stageBadge.className = "badge";
      stageBadge.textContent = stage;
      li.append(stageBadge);
    }

    const overallStatus = evidenceContextValue(item.evidence, "overall_status");
    if (overallStatus) {
      const statusBadge = document.createElement("span");
      statusBadge.className = "badge";
      statusBadge.textContent = overallStatus;
      li.append(statusBadge);
    }

    const sourceUrl = firstSourceUrl(item.evidence);
    if (sourceUrl) {
      const link = document.createElement("a");
      link.href = sourceUrl;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "source ↗";
      li.append(link);
    }

    list.append(li);
  }
  group.append(list);

  if (predicate === "studied_in") {
    const disclaimer = document.createElement("p");
    disclaimer.className = "disclaimer";
    disclaimer.textContent = TRIAL_DISCLAIMER;
    group.append(disclaimer);
  }

  return group;
}

function closeDetail() {
  detail.hidden = true;
  detail.replaceChildren();
  results.hidden = false;
  status.hidden = false;
}

function renderDetail(entityId) {
  const entity = entityById.get(entityId);
  if (!entity) return;

  results.hidden = true;
  status.hidden = true;
  detail.hidden = false;

  const back = document.createElement("button");
  back.type = "button";
  back.className = "back";
  back.textContent = "← Back to search";
  back.addEventListener("click", closeDetail);

  const header = document.createElement("div");
  const name = document.createElement("h2");
  name.textContent = entity.name;
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = `${typeLabel(entity.type)} · ${entity.canonical_id || "no canonical ID"}`;
  header.append(name, meta);
  if (entity.description) {
    const description = document.createElement("p");
    description.className = "meta";
    description.textContent = entity.description;
    header.append(description);
  }

  const sections = [];
  const predicates = outByPredicate.get(entity.id) || new Map();
  for (const [predicate, items] of predicates) {
    sections.push(renderGroup(predicate, items));
  }

  if (entity.type === "drug") {
    const diseases = diseasesViaTargets(entity.id);
    if (diseases.length) {
      const group = renderGroup("associated_with", diseases);
      group.querySelector("h3").textContent = `Possible disease associations via target, unverified (${diseases.length})`;
      sections.push(group);
    }
  }

  if (!sections.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No relations indexed for this entity yet.";
    sections.push(empty);
  }

  detail.replaceChildren(back, header, ...sections);
}

detail.addEventListener("click", (event) => {
  const pivot = event.target.closest(".pivot");
  if (pivot) renderDetail(pivot.dataset.id);
});

results.addEventListener("click", (event) => {
  const card = event.target.closest("article[data-id]");
  if (card && !event.target.closest("a")) renderDetail(card.dataset.id);
});

// --- Top-level search dispatch ---------------------------------------------

function renderPlainSearch(query) {
  const matches = query
    ? entities.filter((entity) =>
        [entity.name, entity.type, entity.canonical_id]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query.toLowerCase()),
      )
    : [];

  results.replaceChildren(
    ...matches.slice(0, 50).map((entity) => {
      const card = document.createElement("article");
      card.dataset.id = entity.id;
      const name = document.createElement("strong");
      const metadata = document.createElement("div");
      name.textContent = entity.name;
      metadata.textContent = `${typeLabel(entity.type)} · ${entity.canonical_id || "no canonical ID"}`;
      card.append(name, metadata);
      return card;
    }),
  );
  status.textContent = query ? `${matches.length} matches` : `${entities.length} indexed entities`;
}

function render() {
  const query = search.value.trim();
  if (!query) {
    renderPlainSearch(query);
    return;
  }

  const intent = parseIntent(query);
  if (!intent.resultType) {
    renderPlainSearch(query);
    return;
  }

  const computed = computeIntentResults(intent);
  if (!computed || (!computed.drugs?.length && !computed.trials?.length)) {
    status.textContent = `Interpreted intent: ${typeLabel(intent.resultType)}`;
    results.replaceChildren(renderIntentEmpty(intent));
    return;
  }

  const container = document.createDocumentFragment();
  container.append(renderIntentHeader(intent));
  if (computed.kind === "drugs") {
    for (const row of computed.drugs) container.append(renderDrugCard(row));
    status.textContent = `${computed.drugs.length} drugs`;
  } else {
    for (const trial of computed.trials) container.append(renderTrialCard(trial));
    status.textContent = `${computed.trials.length} trials`;
  }
  results.replaceChildren(container);
}

function renderAttribution() {
  const presentSources = new Set();
  for (const predicates of outByPredicate.values()) {
    for (const items of predicates.values()) {
      for (const item of items) {
        for (const evidence of item.evidence) {
          if (evidence.source) presentSources.add(evidence.source);
        }
      }
    }
  }
  const lines = SOURCE_ATTRIBUTIONS.filter((rule) =>
    rule.sources.some((source) => presentSources.has(source)),
  ).map((rule) => rule.text);
  attribution.innerHTML = lines.join(" ");
}

Promise.all([
  fetch("data/search-index.json").then((response) => response.json()),
  fetch("data/relations.json")
    .then((response) => response.json())
    .catch(() => []),
])
  .then(([entityRows, relationRows]) => {
    // The DB's entity.type column stores the enum member name (e.g. "DRUG"),
    // not its lowercase value; normalize once so lookups/comparisons match
    // the lowercase keys used throughout this file.
    entityRows.forEach((entity) => {
      entity.type = entity.type.toLowerCase();
    });
    entities = entityRows;
    entityById = new Map(entities.map((entity) => [entity.id, entity]));
    entitiesByType = new Map();
    for (const entity of entities) {
      if (!entitiesByType.has(entity.type)) entitiesByType.set(entity.type, []);
      entitiesByType.get(entity.type).push(entity);
    }
    const indexed = indexRelations(relationRows);
    outByPredicate = indexed.out;
    inByPredicate = indexed.inc;
    renderAttribution();
    render();
  })
  .catch(() => {
    status.textContent = "Search index unavailable";
  });

search.addEventListener("input", render);
