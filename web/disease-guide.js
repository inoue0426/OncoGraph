// Name-based navigation over disease entities present in this snapshot.
// Group labels are browsing aids, not an ontology or clinical classification.
const DISEASE_GROUPS = [
  ["Lung", /\blung\b|pulmonary/i],
  ["Breast", /\bbreast\b|mammary/i],
  ["Colorectal", /\bcolon\b|colorectal|\brectal\b/i],
  ["Melanoma", /melanoma/i],
  ["Leukemia", /leuk(a)?emia/i],
  ["Brain", /\bbrain\b|glioblastoma|\bglioma\b/i],
  ["Ovarian", /ovar(y|ian)/i],
  ["Prostate", /prostat/i],
];
const CANCER_WORDS = /cancer|carcinoma|neoplasm|tumou?r|melanoma|leuk(a)?emia|glioma|glioblastoma|adenocarcinoma|sarcoma/i;

function renderDiseaseGuide() {
  const holder = document.querySelector("#disease-guide");
  if (!holder) return;
  const diseases = entitiesByType.get("disease") || [];
  const groups = DISEASE_GROUPS.map(([label, pattern]) => [
    label,
    diseases.filter((disease) => pattern.test(disease.name) && CANCER_WORDS.test(disease.name)),
  ]).filter(([, matches]) => matches.length);
  if (!groups.length) {
    holder.hidden = true;
    return;
  }

  const heading = document.createElement("h2");
  heading.textContent = "Explore by cancer name";
  const intro = document.createElement("p");
  intro.textContent = "Select a group, then open a disease to inspect its recorded relations.";
  const tabs = document.createElement("div");
  tabs.className = "disease-guide-tabs";
  const list = document.createElement("div");
  list.className = "disease-guide-list";
  const note = document.createElement("p");
  note.className = "trail-caveat";
  note.textContent = "Groups use disease-name matching in this published index. They are not a complete cancer classification; related subtypes may appear in more than one group.";
  let selected = groups[0][0];

  function draw() {
    tabs.replaceChildren();
    list.replaceChildren();
    for (const [label, matches] of groups) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "disease-guide-tab";
      button.textContent = `${label} (${matches.length})`;
      button.setAttribute("aria-pressed", String(label === selected));
      button.addEventListener("click", () => { selected = label; draw(); });
      tabs.append(button);
    }
    const matches = groups.find(([label]) => label === selected)[1];
    for (const disease of matches.slice(0, 12)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "disease-guide-item";
      button.textContent = disease.name;
      button.addEventListener("click", () => {
        renderDetail(disease.id);
        detail.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      list.append(button);
    }
    if (matches.length > 12) {
      const count = document.createElement("p");
      count.className = "trail-count";
      count.textContent = `Showing 12 of ${matches.length} matching names. Search above for another subtype.`;
      list.append(count);
    }
  }
  holder.replaceChildren(heading, intro, tabs, list, note);
  holder.hidden = false;
  draw();
}
