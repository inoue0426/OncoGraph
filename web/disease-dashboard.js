// A disease dashboard keeps direct indications, CIViC records, and gene paths
// separate. Counts describe records in the deployed snapshot, not efficacy.
const DISEASE_VIEWS = [
  ["all", "Overview"],
  ["approved", "Approved-stage indications"],
  ["civic", "CIViC profiles"],
  ["genes", "Related genes"],
  ["paths", "Drugs via genes"],
];

function renderDiseaseDashboard(disease, initialView = "all") {
  const section = document.createElement("section");
  section.className = "disease-dashboard";
  const heading = document.createElement("h3");
  heading.textContent = "Evidence overview";
  const intro = document.createElement("p");
  intro.textContent = "Browse distinct kinds of recorded evidence. Counts show entries in this published snapshot, not treatment strength.";

  const directDrugs = neighborsOfType(disease.id, "drug");
  const approved = directDrugs.filter((row) => row.evidence.some((ev) => ev.evidence_type === "approved_indication"));
  const profiles = neighborsOfType(disease.id, "biomarker").filter((row) => row.evidence.some((ev) => ev.source === "civic"));
  const genes = neighborsOfType(disease.id, "gene");
  const paths = diseaseRelatedDrugs(disease);
  const groups = { approved, civic: profiles, genes, paths };
  const descriptions = {
    approved: "Open Targets records with maximum clinical stage APPROVAL. Check each source; this is not a jurisdiction-specific prescribing label.",
    civic: "Profiles with accepted CIViC evidence. Review the individual records below for significance and direction, including resistance or contradiction.",
    genes: "Recorded gene–disease relations. Association does not establish a treatment.",
    paths: "Two-step links through related genes; these are research leads, not indications.",
  };

  const countBar = document.createElement("div");
  countBar.className = "dashboard-counts";
  for (const [key, label] of DISEASE_VIEWS.slice(1)) {
    const count = document.createElement("div");
    count.className = "dashboard-count";
    const value = document.createElement("strong");
    value.textContent = String(groups[key].length);
    const caption = document.createElement("span");
    caption.textContent = label;
    count.append(value, caption);
    countBar.append(count);
  }

  const viewLabel = document.createElement("label");
  viewLabel.className = "dashboard-filter";
  viewLabel.textContent = "Show evidence type";
  const view = document.createElement("select");
  for (const [key, label] of DISEASE_VIEWS) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = label;
    view.append(option);
  }
  view.value = DISEASE_VIEWS.some(([key]) => key === initialView) ? initialView : "all";
  viewLabel.append(view);
  const content = document.createElement("div");

  function drawGroup(key, preview) {
    const items = groups[key];
    const wrapper = document.createElement("section");
    wrapper.className = "dashboard-group";
    const title = document.createElement("h4");
    title.textContent = `${DISEASE_VIEWS.find(([id]) => id === key)[1]} (${items.length})`;
    const explanation = document.createElement("p");
    explanation.textContent = descriptions[key];
    wrapper.append(title, explanation);
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No matching records in this snapshot.";
      wrapper.append(empty);
    } else {
      const list = document.createElement("ul");
      list.className = "dashboard-items";
      for (const item of items.slice(0, preview ? 6 : 50)) list.append(renderNeighborItem(item));
      wrapper.append(list);
      if (items.length > (preview ? 6 : 50)) {
        const more = document.createElement("p");
        more.className = "dashboard-more";
        more.textContent = preview ? `Showing 6 of ${items.length}. Choose this type above to see more.` : `Showing 50 of ${items.length}; the full relation list is below.`;
        wrapper.append(more);
      }
    }
    return wrapper;
  }

  function draw() {
    const selected = view.value;
    const keys = selected === "all" ? DISEASE_VIEWS.slice(1).map(([key]) => key) : [selected];
    content.replaceChildren(...keys.map((key) => drawGroup(key, selected === "all")));
    if (selected === "civic") {
      const records = renderCivicEvidence(disease);
      if (records) content.append(records);
    }
  }
  view.addEventListener("change", () => {
    draw();
    updateShareUrl({ entity: disease, filter: view.value });
  });
  section.append(heading, intro, countBar, viewLabel, content);
  draw();
  return section;
}
