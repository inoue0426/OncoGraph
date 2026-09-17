const search = document.querySelector("#search");
const status = document.querySelector("#status");
const results = document.querySelector("#results");
const detail = document.querySelector("#detail");

let entities = [];
let entityById = new Map();
let outgoingByPredicate = new Map(); // subjectId -> Map(predicate -> [{objectId, evidence}])

const PREDICATE_LABELS = {
  targets: "Targets",
  studied_in: "Clinical trials",
  associated_with: "Associated diseases",
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

function predicateLabel(predicate) {
  return PREDICATE_LABELS[predicate] || predicate;
}

function typeLabel(type) {
  return TYPE_LABELS[type] || type;
}

function indexRelations(relations) {
  const byPredicate = new Map();
  for (const relation of relations) {
    if (!byPredicate.has(relation.subject_id)) {
      byPredicate.set(relation.subject_id, new Map());
    }
    const predicates = byPredicate.get(relation.subject_id);
    if (!predicates.has(relation.predicate)) {
      predicates.set(relation.predicate, []);
    }
    predicates.get(relation.predicate).push({
      objectId: relation.object_id,
      evidence: relation.evidence || [],
    });
  }
  return byPredicate;
}

function outgoing(entityId, predicate) {
  return outgoingByPredicate.get(entityId)?.get(predicate) || [];
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

function renderGroup(label, items) {
  const group = document.createElement("div");
  group.className = "group";

  const heading = document.createElement("h3");
  heading.textContent = `${label} (${items.length})`;
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

  const sections = [];
  const predicates = outgoingByPredicate.get(entity.id) || new Map();
  for (const [predicate, items] of predicates) {
    sections.push(renderGroup(predicateLabel(predicate), items));
  }

  if (entity.type === "drug") {
    const diseases = diseasesViaTargets(entity.id);
    if (diseases.length) {
      sections.push(renderGroup("Associated diseases (via target)", diseases));
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

function render() {
  const query = search.value.trim().toLowerCase();
  const matches = query
    ? entities.filter((entity) =>
        [entity.name, entity.type, entity.canonical_id]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query),
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

results.addEventListener("click", (event) => {
  const card = event.target.closest("article[data-id]");
  if (card) renderDetail(card.dataset.id);
});

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
    outgoingByPredicate = indexRelations(relationRows);
    render();
  })
  .catch(() => {
    status.textContent = "Search index unavailable";
  });

search.addEventListener("input", render);
