// Interactive paths use only relations present in the deployed export. A
// drug -> gene -> disease path is a research lead, not a treatment indication.
function findEvidenceTrails(drug) {
  const diseases = new Map();
  const add = (disease) => {
    if (!diseases.has(disease.id)) diseases.set(disease.id, { disease, direct: [], via: [] });
    return diseases.get(disease.id);
  };

  for (const relation of allNeighbors(drug.id)) {
    const disease = entityById.get(relation.id);
    if (disease?.type === "disease") {
      add(disease).direct.push({ predicate: relation.predicate, evidence: relation.evidence, direction: relation.direction });
    }
  }

  for (const drugEdge of [...outgoing(drug.id, "targets"), ...outgoing(drug.id, "interacts_with")]) {
    const gene = entityById.get(drugEdge.objectId);
    if (gene?.type !== "gene") continue;
    for (const diseaseEdge of outgoing(gene.id, "associated_with")) {
      const disease = entityById.get(diseaseEdge.objectId);
      if (disease?.type !== "disease") continue;
      add(disease).via.push({ gene, drugEdge, diseaseEdge });
    }
  }

  return [...diseases.values()].sort((a, b) => a.disease.name.localeCompare(b.disease.name));
}

function trailText(tag, value, className) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  el.textContent = value;
  return el;
}

function trailStep(from, predicate, to, evidence, entity) {
  const step = trailText("div", "", "trail-step");
  step.append(trailText("span", `${from} —${predicate}→ ${to}`, "trail-step-title"));
  const source = sourceBadgeText(evidence);
  step.append(trailText("span", source || "No source record in this export", "trail-step-source"));
  const states = new Set(evidence.map((item) => item.claim_state).filter(Boolean));
  if (states.has("contradicts")) step.append(badge("contradicting record", "conflict"));
  if (states.has("context_dependent")) step.append(badge("context-dependent", "context"));
  if (evidence.length) {
    const button = trailText("button", `View ${evidence.length} record${evidence.length === 1 ? "" : "s"}`, "evidence-link");
    button.type = "button";
    button.addEventListener("click", () => showEvidencePanel({ entity, predicate, evidence }));
    step.append(button);
  }
  return step;
}

function renderEvidenceTrail(drug) {
  const choices = findEvidenceTrails(drug);
  if (!choices.length) return null;

  const section = document.createElement("section");
  section.className = "trail-explorer";
  const heading = trailText("h3", "Trace an evidence path");
  const intro = trailText("p", `Choose a disease connected to ${drug.name}. Follow each recorded relation and open its original source record.`, "trail-intro");
  const label = trailText("label", "Filter connected diseases", "trail-filter-label");
  const filter = document.createElement("input");
  filter.type = "search";
  filter.placeholder = "Type a disease name";
  label.append(filter);
  const modeLabel = trailText("label", "Connection type", "trail-filter-label");
  const mode = document.createElement("select");
  for (const [value, title] of [
    ["all", "All connected diseases"],
    ["direct", "Direct recorded relation"],
    ["via", "Via target gene"],
    ["both", "Direct and via target"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = title;
    mode.append(option);
  }
  modeLabel.append(mode);
  const list = trailText("div", "", "trail-choices");
  const summary = trailText("p", "", "trail-count");
  const selected = trailText("div", "", "trail-selected");
  const caveat = trailText("p", "A target path indicates connected records, not that the drug treats the disease. A clinical trial registration does not establish efficacy or approval. Direct relations and two-step paths are displayed separately; the number of paths is not a strength score.", "trail-caveat");
  let current = choices.find((item) => item.direct.length && item.via.length) || choices.find((item) => item.direct.length) || choices[0];

  function drawSelection() {
    const title = trailText("h4", current.disease.name);
    const directTitle = trailText("h5", `Direct recorded relations (${current.direct.length})`);
    const direct = document.createElement("div");
    if (!current.direct.length) direct.append(trailText("p", "None in the published index.", "empty"));
    for (const relation of current.direct.slice(0, 6)) {
      const from = relation.direction === "in" ? current.disease.name : drug.name;
      const to = relation.direction === "in" ? drug.name : current.disease.name;
      direct.append(trailStep(from, relation.predicate, to, relation.evidence, relation.direction === "in" ? drug : current.disease));
    }
    if (current.direct.length > 6) direct.append(trailText("p", `Showing 6 of ${current.direct.length} direct relations.`, "trail-count"));

    const pathTitle = trailText("h5", `Via target genes (${current.via.length})`);
    const paths = document.createElement("div");
    if (!current.via.length) paths.append(trailText("p", "No matching drug → gene → disease path in the published index.", "empty"));
    for (const path of current.via.slice(0, 6)) {
      const card = trailText("div", "", "trail-card");
      card.append(trailStep(drug.name, path.drugEdge.predicate, path.gene.name, path.drugEdge.evidence, path.gene));
      card.append(trailStep(path.gene.name, path.diseaseEdge.predicate, current.disease.name, path.diseaseEdge.evidence, current.disease));
      paths.append(card);
    }
    if (current.via.length > 6) paths.append(trailText("p", `Showing 6 of ${current.via.length} target paths.`, "trail-count"));
    selected.replaceChildren(title, directTitle, direct, pathTitle, paths);
  }

  function drawChoices() {
    const query = filter.value.trim().toLowerCase();
    const matches = choices.filter(({ disease, direct, via }) =>
      disease.name.toLowerCase().includes(query) &&
      (mode.value === "all" || mode.value === "direct" && direct.length ||
        mode.value === "via" && via.length || mode.value === "both" && direct.length && via.length));
    selected.hidden = !matches.length;
    if (matches.length && !matches.some((choice) => choice.disease.id === current.disease.id)) {
      current = matches[0];
      drawSelection();
    }
    list.replaceChildren();
    for (const choice of matches.slice(0, 12)) {
      const label = `${choice.disease.name} · ${choice.direct.length ? "direct" : ""}${choice.direct.length && choice.via.length ? " + " : ""}${choice.via.length ? "via target" : ""}`;
      const button = trailText("button", label, "trail-choice");
      button.type = "button";
      button.setAttribute("aria-pressed", String(choice.disease.id === current.disease.id));
      button.addEventListener("click", () => {
        current = choice;
        drawChoices();
        drawSelection();
      });
      list.append(button);
    }
    summary.textContent = `${choices.length} connected diseases in the index · ${matches.length} match${matches.length === 1 ? "" : "es"}${matches.length > 12 ? " · showing first 12 (refine the filter)" : ""}.`;
    if (!matches.length) list.append(trailText("p", "No connected disease matches this filter.", "empty"));
  }

  filter.addEventListener("input", drawChoices);
  mode.addEventListener("change", drawChoices);
  section.append(heading, intro, label, modeLabel, list, summary, selected, caveat);
  drawChoices();
  drawSelection();
  return section;
}

function renderTrailHighlights() {
  const holder = document.querySelector("#trail-highlights");
  if (!holder) return;
  const preferred = ["osimertinib", "gefitinib", "erlotinib", "imatinib", "vemurafenib"];
  const drugs = entitiesByType.get("drug") || [];
  const featured = preferred.map((name) => drugs.find((entity) => entity.name.toLowerCase() === name))
    .filter((entity) => entity && findEvidenceTrails(entity).length).slice(0, 3);
  const discoverable = drugs.filter((drug) => findEvidenceTrails(drug).length);
  if (!discoverable.length) {
    holder.hidden = true;
    return;
  }
  const buttons = featured.map((drug) => {
    const button = trailText("button", `Trace ${drug.name} →`, "trail-highlight");
    button.type = "button";
    button.addEventListener("click", () => {
      renderDetail(drug.id);
      detail.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return button;
  });
  const surprise = trailText("button", "Surprise me →", "trail-highlight");
  surprise.type = "button";
  surprise.addEventListener("click", () => {
    const drug = discoverable[Math.floor(Math.random() * discoverable.length)];
    renderDetail(drug.id);
    detail.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  holder.replaceChildren(trailText("h2", "Follow the evidence"), trailText("p", "Pick a drug at random or open an example, then follow its recorded links to diseases, one source at a time."), surprise, ...buttons);
  holder.hidden = false;
}
