// --- DOM refs ---------------------------------------------------------------

const search = document.querySelector("#search");
const status = document.querySelector("#status");
const results = document.querySelector("#results");
const detail = document.querySelector("#detail");
const attribution = document.querySelector("#attribution");
const examples = document.querySelector("#examples");
const evidencePanel = document.querySelector("#evidence-panel");

const TRIAL_DISCLAIMER = "Trial registration does not imply efficacy or approval.";

// --- In-memory index ----------------------------------------------------------

let entities = [];
let entityById = new Map();
let outByPredicate = new Map(); // subjectId -> Map(predicate -> [{objectId, evidence}])
let inByPredicate = new Map(); // objectId -> Map(predicate -> [{subjectId, evidence}])
let entitiesByType = new Map(); // type -> [entity, ...]

const TYPE_LABELS = {
  drug: "Drug",
  gene: "Gene",
  target: "Target",
  disease: "Disease",
  trial: "Trial",
  go_term: "GO term",
  pathway: "Pathway",
  paper: "Publication",
  biomarker: "Biomarker",
  cell_line: "Cell line",
  pdx: "PDX",
  organoid: "Organoid",
  cohort: "Cohort",
};

// "What do you want back" words -> a facet. Deliberately small and literal --
// rule-based intent detection, not NLP. A bare name with none of these present
// falls back to plain entity search (see render()).
const FACET_KEYWORDS = {
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
  disease: "disease",
  diseases: "disease",
  pathway: "pathway",
  pathways: "pathway",
  publication: "publication",
  publications: "publication",
  paper: "publication",
  papers: "publication",
};

const FACET_ENTITY_TYPE = {
  drug: "drug",
  trial: "trial",
  gene: "gene",
  disease: "disease",
  pathway: "pathway",
  publication: "paper",
};

// Evidence.source_type -> a display tier. This is data-driven (reuses the
// source_type every adapter already sets, see docs/EVIDENCE.md) rather than
// a per-facet hard-coded predicate list, so it scales to new sources for free.
const TIER_ORDER = ["approved", "curated_database", "registry", "computed", "publication", "unknown"];
const TIER_LABELS = {
  approved: "Approved indication",
  curated_database: "Curated database evidence",
  registry: "Clinical trial registry",
  computed: "Computed association (unverified)",
  publication: "Literature",
  unknown: "Other evidence",
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
  {
    sources: ["reactome"],
    text: 'Pathway membership from <a href="https://reactome.org/">Reactome</a> (CC0).',
  },
  {
    sources: ["civic"],
    text: 'Clinical evidence from <a href="https://civicdb.org/">CIViC</a> (CC0).',
  },
  {
    sources: ["dgidb"],
    text:
      'Aggregated drug-gene interactions from <a href="https://dgidb.org/">DGIdb</a> (redistribution unconfirmed; see project docs).',
  },
  {
    sources: ["europe_pmc"],
    text: 'Publication metadata from <a href="https://europepmc.org/">Europe PMC</a>.',
  },
];

const EXAMPLE_QUERIES = [
  "gefitinib",
  "EGFR",
  "ovarian cancer drugs",
  "osimertinib trials",
  "osimertinib targets",
  "osimertinib diseases",
  "EGFR drugs",
  "glioblastoma trials",
];

function typeLabel(type) {
  return TYPE_LABELS[type] || type;
}

function tierKeyForItem(item) {
  const primary = item.evidence[0];
  if (!primary) return "unknown";
  if (primary.evidence_type === "approved_indication") return "approved";
  return primary.source_type || "unknown";
}

function tierRank(key) {
  const index = TIER_ORDER.indexOf(key);
  return index === -1 ? TIER_ORDER.length : index;
}

// --- Data loading & indexing --------------------------------------------------

function indexRelations(relations) {
  const out = new Map();
  const inc = new Map();
  for (const relation of relations) {
    // The DB stores claim_state/verification_status as the enum member NAME
    // (e.g. "SUPPORTS"), not its lowercase value -- same quirk as entity.type.
    for (const ev of relation.evidence || []) {
      if (ev.claim_state) ev.claim_state = ev.claim_state.toLowerCase();
      if (ev.verification_status) ev.verification_status = ev.verification_status.toLowerCase();
    }

    if (!out.has(relation.subject_id)) out.set(relation.subject_id, new Map());
    const outPredicates = out.get(relation.subject_id);
    if (!outPredicates.has(relation.predicate)) outPredicates.set(relation.predicate, []);
    outPredicates
      .get(relation.predicate)
      .push({ objectId: relation.object_id, evidence: relation.evidence || [], predicate: relation.predicate });

    if (!inc.has(relation.object_id)) inc.set(relation.object_id, new Map());
    const inPredicates = inc.get(relation.object_id);
    if (!inPredicates.has(relation.predicate)) inPredicates.set(relation.predicate, []);
    inPredicates
      .get(relation.predicate)
      .push({ subjectId: relation.subject_id, evidence: relation.evidence || [], predicate: relation.predicate });
  }
  return { out, inc };
}

function outgoing(entityId, predicate) {
  return outByPredicate.get(entityId)?.get(predicate) || [];
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

function publicationRef(entity) {
  // A publication's canonical_id is "pubmed:<pmid>" / "doi:<doi>" / "pmcid:<id>".
  if (!entity || entity.type !== "paper" || !entity.canonical_id) return null;
  const [namespace, value] = entity.canonical_id.split(/:(.+)/).filter(Boolean);
  if (namespace === "pubmed") return { label: "PMID", value };
  if (namespace === "doi") return { label: "DOI", value };
  if (namespace === "pmcid") return { label: "PMCID", value };
  return null;
}

// --- Generic neighbor / facet computation -------------------------------------

function neighborsOfType(entityId, targetType) {
  const found = [];
  const outMap = outByPredicate.get(entityId);
  if (outMap) {
    for (const items of outMap.values()) {
      for (const item of items) {
        const other = entityById.get(item.objectId);
        if (other && other.type === targetType) found.push({ entity: other, evidence: item.evidence, predicate: item.predicate });
      }
    }
  }
  const inMap = inByPredicate.get(entityId);
  if (inMap) {
    for (const items of inMap.values()) {
      for (const item of items) {
        const other = entityById.get(item.subjectId);
        if (other && other.type === targetType) found.push({ entity: other, evidence: item.evidence, predicate: item.predicate });
      }
    }
  }
  return found;
}

// Drug (or any entity) -> targets -> Gene -> predicate -> objectType, e.g.
// Drug -> Gene -> associated_with -> Disease, or Drug -> Gene -> part_of_pathway -> Pathway.
function viaGeneTargets(entityId, objectType, predicate) {
  const best = new Map();
  for (const t of [...outgoing(entityId, "targets"), ...outgoing(entityId, "interacts_with")]) {
    const gene = entityById.get(t.objectId);
    if (!gene) continue;
    for (const edge of outgoing(gene.id, predicate)) {
      const obj = entityById.get(edge.objectId);
      if (!obj || obj.type !== objectType) continue;
      if (!best.has(obj.id)) best.set(obj.id, { entity: obj, via: gene, evidence: edge.evidence });
    }
  }
  return [...best.values()];
}

function publicationsFor(entityId) {
  const seen = new Map();
  const collect = (map) => {
    if (!map) return;
    for (const items of map.values()) {
      for (const item of items) {
        for (const ev of item.evidence) {
          if (!ev.publication_id) continue;
          const pub = entityById.get(ev.publication_id);
          if (pub && !seen.has(pub.id)) seen.set(pub.id, { entity: pub, evidence: [ev] });
        }
      }
    }
  };
  collect(outByPredicate.get(entityId));
  collect(inByPredicate.get(entityId));
  return [...seen.values()];
}

function groupByTier(items) {
  const groups = new Map();
  for (const item of items) {
    const key = tierKeyForItem(item);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  return [...groups.entries()].sort((a, b) => tierRank(a[0]) - tierRank(b[0]));
}

function computeFacetGroups(center, facet) {
  if (facet === "publication") {
    const items = publicationsFor(center.id);
    return items.length ? [["publication", items]] : [];
  }

  if (facet === "disease") {
    const direct = neighborsOfType(center.id, "disease");
    const groups = groupByTier(direct);
    if (center.type === "drug") {
      const viaTarget = viaGeneTargets(center.id, "disease", "associated_with").map((i) => ({
        ...i,
        evidence: i.evidence,
      }));
      if (viaTarget.length) groups.push(["computed", viaTarget]);
    }
    return groups;
  }

  if (facet === "pathway") {
    const direct = neighborsOfType(center.id, "pathway");
    const viaTarget = center.type === "drug" ? viaGeneTargets(center.id, "pathway", "part_of_pathway") : [];
    return groupByTier([...direct, ...viaTarget]);
  }

  if (facet === "trial") {
    const direct = neighborsOfType(center.id, "trial");
    if (direct.length) return groupByTier(direct);
    if (center.type === "disease") {
      // No direct Disease<->Trial edge exists yet (trial conditions are free
      // text, not linked entities -- see docs/PUBLICATIONS.md-style caveats).
      // Fall back to matching the disease's own name against trial text.
      const lower = center.name.toLowerCase();
      const matches = (entitiesByType.get("trial") || [])
        .filter((t) => t.description && t.description.toLowerCase().includes(lower))
        .map((t) => ({ entity: t, evidence: outgoing(t.id, "studied_in").length ? [] : [] }));
      // Attach evidence from the matched trial's own studied_in edges, if any.
      const withEvidence = matches.map((m) => {
        const incomingStudied = (inByPredicate.get(m.entity.id)?.get("studied_in") || [])[0];
        return { entity: m.entity, evidence: incomingStudied?.evidence || [] };
      });
      return withEvidence.length ? [["registry", withEvidence]] : [];
    }
    return [];
  }

  // facet === "gene" or "drug": plain neighbor lookup, tiered generically.
  const targetType = FACET_ENTITY_TYPE[facet];
  return groupByTier(neighborsOfType(center.id, targetType));
}

// --- Ranked entity search (bare-name mode) ------------------------------------

function matchRank(entity, lower) {
  const name = entity.name.toLowerCase();
  const canonical = (entity.canonical_id || "").toLowerCase();
  const aliases = (entity.metadata?.aliases || []).map((a) => a.toLowerCase());
  if (name === lower) return 0;
  if (aliases.includes(lower)) return 1;
  if (canonical === lower) return 2;
  if (name.startsWith(lower) || aliases.some((a) => a.startsWith(lower))) return 3;
  if (name.includes(lower) || canonical.includes(lower) || aliases.some((a) => a.includes(lower))) return 4;
  if (entity.type.includes(lower)) return 5;
  return null;
}

function rankedEntitySearch(query) {
  const lower = query.trim().toLowerCase();
  if (!lower) return [];
  const scored = [];
  for (const entity of entities) {
    const rank = matchRank(entity, lower);
    if (rank !== null) scored.push({ entity, rank });
  }
  scored.sort((a, b) => a.rank - b.rank || a.entity.name.localeCompare(b.entity.name));
  return scored;
}

// --- Intent parsing ------------------------------------------------------------

function parseIntent(rawQuery) {
  const words = rawQuery.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return { facet: null, remainder: "", center: null };

  let facetIndex = -1;
  let facet = null;
  for (let i = words.length - 1; i >= 0; i--) {
    const mapped = FACET_KEYWORDS[words[i].toLowerCase()];
    if (mapped) {
      facetIndex = i;
      facet = mapped;
      break;
    }
  }

  if (facetIndex === -1) return { facet: null, remainder: rawQuery.trim(), center: null };

  const remainder = words
    .filter((_, i) => i !== facetIndex)
    .join(" ")
    .trim();
  if (!remainder) return { facet: null, remainder: rawQuery.trim(), center: null };

  const ranked = rankedEntitySearch(remainder);
  const center = ranked.length && ranked[0].rank <= 2 ? ranked[0].entity : ranked[0]?.entity || null;
  return { facet, remainder, center, allMatches: ranked.map((r) => r.entity) };
}

// --- Evidence panel ------------------------------------------------------------

function showEvidencePanel(item) {
  const rows = item.evidence.map((ev) => {
    const pub = ev.publication_id ? entityById.get(ev.publication_id) : null;
    const pubRef = pub ? publicationRef(pub) : null;
    const parts = [
      ["Source", ev.source],
      ["Source record", ev.source_id],
      pubRef ? [pubRef.label, pubRef.value] : null,
      pub ? ["Publication title", pub.name] : null,
      ["Evidence type", ev.evidence_type],
      ["Claim state", ev.claim_state],
      ["Confidence", typeof ev.confidence === "number" ? ev.confidence.toFixed(2) : null],
      ["Verification state", ev.verification_status],
      ["License", ev.license],
      ["Retrieved", ev.retrieved_at ? ev.retrieved_at.slice(0, 10) : null],
      ["Context", ev.context ? JSON.stringify(ev.context) : null],
    ].filter((p) => p && p[1] !== null && p[1] !== undefined);

    const dl = document.createElement("dl");
    dl.className = "evidence-detail";
    for (const [key, value] of parts) {
      const dt = document.createElement("dt");
      dt.textContent = key;
      const dd = document.createElement("dd");
      dd.textContent = String(value);
      dl.append(dt, dd);
    }
    if (ev.source_url) {
      const link = document.createElement("a");
      link.href = ev.source_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Open source ↗";
      dl.append(link);
    }
    return dl;
  });

  const heading = document.createElement("div");
  heading.className = "evidence-panel-heading";
  heading.textContent = `${item.predicate || "relation"} → ${item.entity.name}: ${item.evidence.length} evidence record(s)`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "back";
  close.textContent = "Close";
  close.addEventListener("click", () => {
    evidencePanel.hidden = true;
    evidencePanel.replaceChildren();
  });

  evidencePanel.replaceChildren(close, heading, ...rows);
  evidencePanel.hidden = false;
  evidencePanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// --- Rendering: generic tiered/neighbor lists ---------------------------------

function badge(text, extraClass) {
  const span = document.createElement("span");
  span.className = extraClass ? `badge ${extraClass}` : "badge";
  span.textContent = text;
  return span;
}

function renderNeighborItem(item) {
  const li = document.createElement("li");

  const pivot = document.createElement("button");
  pivot.type = "button";
  pivot.className = "pivot";
  pivot.dataset.id = item.entity.id;
  pivot.textContent = item.entity.name;
  li.append(pivot, badge(typeLabel(item.entity.type)));

  const score = evidenceContextValue(item.evidence, "score");
  if (typeof score === "number") li.append(badge(`score ${score.toFixed(2)}`));
  const stage = evidenceContextValue(item.evidence, "max_clinical_stage");
  if (stage) li.append(badge(stage));
  const status = evidenceContextValue(item.evidence, "overall_status");
  if (status) li.append(badge(status));
  const phases = evidenceContextValue(item.evidence, "phases");
  if (Array.isArray(phases) && phases.length) li.append(badge(phases.join(", ")));

  const claimStates = new Set(item.evidence.map((e) => e.claim_state).filter(Boolean));
  if (claimStates.has("contradicts") && claimStates.has("supports")) {
    li.append(badge("⚠ conflicting evidence", "conflict"));
  } else if (claimStates.has("contradicts")) {
    li.append(badge("contradicts", "conflict"));
  }
  if (claimStates.has("context_dependent")) li.append(badge("context-dependent", "context"));

  const sourceText = sourceBadgeText(item.evidence);
  if (sourceText) li.append(badge(sourceText, "source"));

  if (item.evidence.length) {
    const evidenceButton = document.createElement("button");
    evidenceButton.type = "button";
    evidenceButton.className = "evidence-link";
    evidenceButton.textContent = `evidence (${item.evidence.length})`;
    evidenceButton.addEventListener("click", (event) => {
      event.stopPropagation();
      showEvidencePanel(item);
    });
    li.append(evidenceButton);
  }

  return li;
}

function renderTierGroup(tierKey, items, options = {}) {
  const group = document.createElement("div");
  group.className = `tier tier-${tierKey}`;
  const heading = document.createElement("div");
  heading.className = "tier-label";
  heading.textContent = `${options.label || TIER_LABELS[tierKey] || tierKey} (${items.length})`;
  group.append(heading);

  const list = document.createElement("ul");
  for (const item of items) list.append(renderNeighborItem(item));
  group.append(list);

  if (tierKey === "registry" || options.disclaimer) {
    const disclaimer = document.createElement("p");
    disclaimer.className = "disclaimer";
    disclaimer.textContent = TRIAL_DISCLAIMER;
    group.append(disclaimer);
  }
  return group;
}

// --- Facet ("intent") result rendering ------------------------------------------

function renderIntentHeader(intent) {
  const header = document.createElement("p");
  header.className = "intent-header";
  header.textContent = intent.center
    ? `"${intent.remainder}" → ${intent.center.name} (${typeLabel(intent.center.type)}) → ${typeLabel(FACET_ENTITY_TYPE[intent.facet])}`
    : `Looking for ${typeLabel(FACET_ENTITY_TYPE[intent.facet])} related to "${intent.remainder}"`;
  return header;
}

function coverageSummary() {
  const count = (type) => (entitiesByType.get(type) || []).length;
  return (
    `Currently indexed: ${count("drug")} drugs, ${count("gene")} genes, ${count("disease")} diseases, ` +
    `${count("trial")} trials, ${count("pathway")} pathways, ${count("paper")} publications.`
  );
}

function renderIntentEmpty(intent) {
  const container = document.createDocumentFragment();
  container.append(renderIntentHeader(intent));
  const message = document.createElement("p");
  message.className = "empty";
  message.textContent = intent.center
    ? `No ${typeLabel(FACET_ENTITY_TYPE[intent.facet])} evidence indexed for this yet.`
    : `Could not match "${intent.remainder}" to a known entity.`;
  container.append(message);
  const coverage = document.createElement("p");
  coverage.className = "empty";
  coverage.textContent = coverageSummary();
  container.append(coverage);
  return container;
}

// --- Entity detail view --------------------------------------------------------

function closeDetail() {
  detail.hidden = true;
  detail.replaceChildren();
  evidencePanel.hidden = true;
  evidencePanel.replaceChildren();
  results.hidden = false;
  status.hidden = false;
}

function renderEntityHeader(entity) {
  const header = document.createElement("div");
  const name = document.createElement("h2");
  name.textContent = entity.name;
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = `${typeLabel(entity.type)} · ${entity.canonical_id || "no canonical ID"}`;
  header.append(name, meta);
  const aliases = entity.metadata?.aliases;
  if (Array.isArray(aliases) && aliases.length) {
    const aliasLine = document.createElement("div");
    aliasLine.className = "meta";
    aliasLine.textContent = `Also known as: ${aliases.join(", ")}`;
    header.append(aliasLine);
  }
  if (entity.description) {
    const description = document.createElement("p");
    description.className = "meta";
    description.textContent = entity.description;
    header.append(description);
  }
  return header;
}

// Drug detail: fixed, named summary sections rather than raw predicate groups,
// so Clinical trials is one section among several, not the dominant view.
function renderDrugDetail(entity) {
  const sections = [];

  const targets = neighborsOfType(entity.id, "gene").filter((i) => i.predicate === "targets" || i.predicate === "interacts_with");
  if (targets.length) sections.push(renderTierGroup("curated_database", targets, { label: "Targets" }));

  const diseaseGroups = computeFacetGroups(entity, "disease");
  const approved = diseaseGroups.find(([k]) => k === "approved");
  if (approved) sections.push(renderTierGroup("approved", approved[1], { label: "Approved indications" }));
  const otherDisease = diseaseGroups.filter(([k]) => k !== "approved");
  for (const [key, items] of otherDisease) {
    sections.push(renderTierGroup(key, items, { label: `Associated diseases — ${TIER_LABELS[key] || key}` }));
  }

  const pathwayGroups = computeFacetGroups(entity, "pathway").flatMap(([, items]) => items);
  const filteredPathways = filterLowInformationTerms(pathwayGroups);
  if (filteredPathways.length) sections.push(renderTierGroup("curated_database", filteredPathways, { label: "Pathways / GO" }));

  const biomarkers = neighborsOfType(entity.id, "biomarker");
  if (biomarkers.length) sections.push(renderTierGroup("curated_database", biomarkers, { label: "Biomarkers" }));

  const publications = publicationsFor(entity.id);
  if (publications.length) sections.push(renderTierGroup("publication", publications, { label: "Publications" }));

  const trials = neighborsOfType(entity.id, "trial");
  if (trials.length) sections.push(renderTierGroup("registry", trials, { label: "Clinical trials", disclaimer: true }));

  return sections;
}

// Every non-root entity type type of GO term is filtered when it's a root
// term (e.g. "biological_process") or has an unusually large child_count --
// issue #5/#8's "low-information term" concern.
function filterLowInformationTerms(items) {
  return items.filter((item) => {
    if (item.entity.type !== "go_term") return true;
    const meta = item.entity.metadata;
    if (!meta) return true;
    if (meta.is_root) return false;
    if (typeof meta.child_count === "number" && meta.child_count > 50) return false;
    return true;
  });
}

function renderGenericDetail(entity) {
  const sections = [];
  const predicates = outByPredicate.get(entity.id) || new Map();
  for (const [predicate, items] of predicates) {
    const wrapped = items.map((i) => ({ entity: entityById.get(i.objectId), evidence: i.evidence, predicate }));
    const filtered = filterLowInformationTerms(wrapped.filter((i) => i.entity));
    if (filtered.length) sections.push(renderTierGroup(tierKeyForItem(filtered[0]), filtered, { label: predicate }));
  }
  const incomingPredicates = inByPredicate.get(entity.id) || new Map();
  for (const [predicate, items] of incomingPredicates) {
    const wrapped = items.map((i) => ({ entity: entityById.get(i.subjectId), evidence: i.evidence, predicate }));
    const filtered = filterLowInformationTerms(wrapped.filter((i) => i.entity));
    if (filtered.length) sections.push(renderTierGroup(tierKeyForItem(filtered[0]), filtered, { label: `← ${predicate}` }));
  }
  const publications = publicationsFor(entity.id);
  if (publications.length) sections.push(renderTierGroup("publication", publications, { label: "Publications" }));
  return sections;
}

function renderDetail(entityId) {
  const entity = entityById.get(entityId);
  if (!entity) return;

  results.hidden = true;
  status.hidden = true;
  detail.hidden = false;
  evidencePanel.hidden = true;
  evidencePanel.replaceChildren();

  const back = document.createElement("button");
  back.type = "button";
  back.className = "back";
  back.textContent = "← Back to search";
  back.addEventListener("click", closeDetail);

  const header = renderEntityHeader(entity);
  const sections = entity.type === "drug" ? renderDrugDetail(entity) : renderGenericDetail(entity);
  const graph = renderLocalGraph(entity);

  if (!sections.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No relations indexed for this entity yet.";
    sections.push(empty);
  }

  detail.replaceChildren(back, header, graph, ...sections);
}

// --- Local graph visualization (1-2 hop, SVG) ----------------------------------

const TYPE_COLORS = {
  drug: "#3fb950",
  gene: "#58a6ff",
  disease: "#f78166",
  trial: "#d29922",
  pathway: "#bc8cff",
  paper: "#8b949e",
  biomarker: "#39c5cf",
};

function typeColor(type) {
  return TYPE_COLORS[type] || "#8b949e";
}

function allNeighbors(entityId) {
  const found = [];
  const outMap = outByPredicate.get(entityId);
  if (outMap) for (const items of outMap.values()) for (const i of items) found.push({ id: i.objectId, evidence: i.evidence, predicate: i.predicate });
  const inMap = inByPredicate.get(entityId);
  if (inMap) for (const items of inMap.values()) for (const i of items) found.push({ id: i.subjectId, evidence: i.evidence, predicate: i.predicate });
  return found;
}

function renderLocalGraph(centerEntity) {
  const container = document.createElement("div");
  container.className = "graph-container";

  const controls = document.createElement("div");
  controls.className = "graph-controls";
  const hopSelect = document.createElement("select");
  hopSelect.innerHTML = '<option value="1">1 hop</option><option value="2">2 hops</option>';
  const typeSelect = document.createElement("select");
  typeSelect.innerHTML =
    '<option value="">All node types</option>' +
    Object.keys(TYPE_LABELS)
      .map((t) => `<option value="${t}">${typeLabel(t)}</option>`)
      .join("");
  controls.append(labelWrap("Depth", hopSelect), labelWrap("Node type", typeSelect));
  container.append(controls);

  const svgWrapper = document.createElement("div");
  svgWrapper.className = "graph-svg-wrapper";
  container.append(svgWrapper);

  function draw() {
    const hops = Number(hopSelect.value);
    const typeFilter = typeSelect.value;
    svgWrapper.replaceChildren(buildGraphSvg(centerEntity, hops, typeFilter));
  }

  hopSelect.addEventListener("change", draw);
  typeSelect.addEventListener("change", draw);
  draw();
  return container;
}

function labelWrap(text, el) {
  const label = document.createElement("label");
  label.className = "graph-control";
  const span = document.createElement("span");
  span.textContent = text;
  label.append(span, el);
  return label;
}

function buildGraphSvg(centerEntity, hops, typeFilter) {
  const NS = "http://www.w3.org/2000/svg";
  const width = 640;
  const height = 420;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "graph-svg");

  const centerX = width / 2;
  const centerY = height / 2;
  const nodes = new Map([[centerEntity.id, { x: centerX, y: centerY, entity: centerEntity }]]);
  const edges = [];

  let ring1 = allNeighbors(centerEntity.id)
    .map((n) => ({ ...n, neighbor: entityById.get(n.id) }))
    .filter((n) => n.neighbor && (!typeFilter || n.neighbor.type === typeFilter))
    .filter((n) => filterLowInformationTerms([{ entity: n.neighbor }]).length > 0);
  // De-duplicate by neighbor id, cap for legibility.
  const seen1 = new Map();
  for (const n of ring1) if (!seen1.has(n.id)) seen1.set(n.id, n);
  ring1 = [...seen1.values()].slice(0, 14);

  const r1 = Math.min(width, height) / 2 - 90;
  ring1.forEach((n, i) => {
    const angle = (i / Math.max(ring1.length, 1)) * 2 * Math.PI;
    const x = centerX + r1 * Math.cos(angle);
    const y = centerY + r1 * Math.sin(angle);
    nodes.set(n.id, { x, y, entity: n.neighbor });
    edges.push({ from: centerEntity.id, to: n.id, evidence: n.evidence, predicate: n.predicate });
  });

  if (hops >= 2) {
    const r2 = r1 + 90;
    ring1.slice(0, 6).forEach((n1, i) => {
      let ring2 = allNeighbors(n1.id)
        .map((n) => ({ ...n, neighbor: entityById.get(n.id) }))
        .filter((n) => n.neighbor && n.id !== centerEntity.id && !nodes.has(n.id) && (!typeFilter || n.neighbor.type === typeFilter))
        .slice(0, 3);
      const baseAngle = (i / Math.max(ring1.length, 1)) * 2 * Math.PI;
      ring2.forEach((n2, j) => {
        const angle = baseAngle + (j - (ring2.length - 1) / 2) * 0.35;
        const x = centerX + r2 * Math.cos(angle);
        const y = centerY + r2 * Math.sin(angle);
        if (!nodes.has(n2.id)) nodes.set(n2.id, { x, y, entity: n2.neighbor });
        edges.push({ from: n1.id, to: n2.id, evidence: n2.evidence, predicate: n2.predicate });
      });
    });
  }

  for (const edge of edges) {
    const a = nodes.get(edge.from);
    const b = nodes.get(edge.to);
    if (!a || !b) continue;
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", a.x);
    line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x);
    line.setAttribute("y2", b.y);
    const claimStates = new Set((edge.evidence || []).map((e) => e.claim_state).filter(Boolean));
    line.setAttribute("class", claimStates.has("contradicts") ? "graph-edge graph-edge-conflict" : "graph-edge");
    line.addEventListener("click", () => {
      const otherEntity = nodes.get(edge.to)?.entity;
      if (otherEntity) showEvidencePanel({ entity: otherEntity, evidence: edge.evidence || [], predicate: edge.predicate });
    });
    svg.append(line);
  }

  for (const [id, node] of nodes) {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "graph-node");
    const circle = document.createElementNS(NS, "circle");
    circle.setAttribute("cx", node.x);
    circle.setAttribute("cy", node.y);
    circle.setAttribute("r", id === centerEntity.id ? 14 : 9);
    circle.setAttribute("fill", typeColor(node.entity.type));
    g.append(circle);

    const text = document.createElementNS(NS, "text");
    text.setAttribute("x", node.x);
    text.setAttribute("y", node.y + (id === centerEntity.id ? 26 : 20));
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("class", "graph-label");
    text.textContent = node.entity.name.length > 18 ? `${node.entity.name.slice(0, 17)}…` : node.entity.name;
    g.append(text);

    if (id !== centerEntity.id) {
      g.style.cursor = "pointer";
      g.addEventListener("click", () => renderDetail(id));
    }
    svg.append(g);
  }

  return svg;
}

// --- Top-level search dispatch ---------------------------------------------

function renderSearchResultCard(entity) {
  const card = document.createElement("article");
  card.dataset.id = entity.id;

  const name = document.createElement("strong");
  name.textContent = entity.name;
  const metadata = document.createElement("div");
  metadata.className = "meta";
  metadata.textContent = `${typeLabel(entity.type)} · ${entity.canonical_id || "no canonical ID"}`;
  card.append(name, metadata);

  const aliases = entity.metadata?.aliases;
  if (Array.isArray(aliases) && aliases.length) {
    const aliasLine = document.createElement("div");
    aliasLine.className = "meta";
    aliasLine.textContent = `aka ${aliases.slice(0, 3).join(", ")}`;
    card.append(aliasLine);
  }

  const relationCount = allNeighbors(entity.id).length;
  const sourceCount = new Set(allNeighbors(entity.id).flatMap((n) => n.evidence.map((e) => e.source))).size;
  if (relationCount) {
    const counts = document.createElement("div");
    counts.className = "meta";
    counts.textContent = `${relationCount} relation(s) · ${sourceCount} source(s)`;
    card.append(counts);
  }

  return card;
}

function renderPlainSearch(query) {
  const ranked = query ? rankedEntitySearch(query) : [];
  results.replaceChildren(...ranked.slice(0, 50).map((r) => renderSearchResultCard(r.entity)));
  status.textContent = query ? `${ranked.length} matches` : `${entities.length} indexed entities`;
}

function render() {
  const query = search.value.trim();
  if (!query) {
    renderPlainSearch(query);
    return;
  }

  const intent = parseIntent(query);
  if (!intent.facet) {
    renderPlainSearch(query);
    return;
  }

  if (!intent.center) {
    status.textContent = `Interpreted intent: ${typeLabel(FACET_ENTITY_TYPE[intent.facet])}`;
    results.replaceChildren(renderIntentEmpty(intent));
    return;
  }

  const groups = computeFacetGroups(intent.center, intent.facet).map(([key, items]) => [
    key,
    filterLowInformationTerms(items),
  ]);
  const total = groups.reduce((sum, [, items]) => sum + items.length, 0);
  if (!total) {
    status.textContent = `Interpreted intent: ${typeLabel(FACET_ENTITY_TYPE[intent.facet])}`;
    results.replaceChildren(renderIntentEmpty(intent));
    return;
  }

  const container = document.createDocumentFragment();
  container.append(renderIntentHeader(intent));
  for (const [key, items] of groups) container.append(renderTierGroup(key, items));
  status.textContent = `${total} ${typeLabel(FACET_ENTITY_TYPE[intent.facet])}(s)`;
  results.replaceChildren(container);
}

let searchDebounce = null;
function debouncedRender() {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(render, 120);
}

function renderExamples() {
  if (!examples) return;
  examples.replaceChildren(
    ...EXAMPLE_QUERIES.map((q) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "example-query";
      button.textContent = q;
      button.addEventListener("click", () => {
        search.value = q;
        render();
        search.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      return button;
    }),
  );
}

detail.addEventListener("click", (event) => {
  const pivot = event.target.closest(".pivot");
  if (pivot) renderDetail(pivot.dataset.id);
});

results.addEventListener("click", (event) => {
  const card = event.target.closest("article[data-id]");
  if (card && !event.target.closest("a, button")) renderDetail(card.dataset.id);
});

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
  const lines = SOURCE_ATTRIBUTIONS.filter((rule) => rule.sources.some((source) => presentSources.has(source))).map(
    (rule) => rule.text,
  );
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
    renderExamples();
    render();
  })
  .catch(() => {
    status.textContent = "Search index unavailable";
  });

search.addEventListener("input", debouncedRender);
