const state = { entities: [], filtered: [] };
const searchInput = document.querySelector("#search");
const typeFilter = document.querySelector("#type-filter");
const results = document.querySelector("#results");
const resultCount = document.querySelector("#result-count");
const snapshotStatus = document.querySelector("#snapshot-status");
const emptyState = document.querySelector("#empty-state");

function text(value) {
  return value === null || value === undefined ? "" : String(value);
}

function render() {
  const query = searchInput.value.trim().toLocaleLowerCase();
  const selectedType = typeFilter.value;
  state.filtered = state.entities.filter((entity) => {
    const haystack = [entity.name, entity.canonical_id, entity.type, entity.description]
      .map(text)
      .join(" ")
      .toLocaleLowerCase();
    return (!query || haystack.includes(query)) && (!selectedType || entity.type === selectedType);
  });

  results.replaceChildren(
    ...state.filtered.slice(0, 100).map((entity) => {
      const card = document.createElement("article");
      card.className = "entity-card";

      const type = document.createElement("div");
      type.className = "entity-type";
      type.textContent = text(entity.type).replaceAll("_", " ");

      const heading = document.createElement("h3");
      heading.textContent = entity.name;

      const canonicalId = document.createElement("div");
      canonicalId.className = "canonical-id";
      canonicalId.textContent = entity.canonical_id || "No canonical identifier";

      const description = document.createElement("p");
      description.className = "description";
      description.textContent = entity.description || "No public description available.";

      const metrics = document.createElement("div");
      metrics.className = "metrics";
      metrics.textContent = `${entity.relation_count} relations · ${entity.evidence_count} evidence records`;

      card.append(type, heading, canonicalId, description, metrics);
      return card;
    }),
  );

  const displayed = Math.min(state.filtered.length, 100);
  resultCount.textContent = `${state.filtered.length.toLocaleString()} matches`;
  if (state.filtered.length > 100) {
    resultCount.textContent += ` · showing first ${displayed}`;
  }
  emptyState.hidden = state.filtered.length > 0;
  emptyState.textContent = state.entities.length
    ? "No entities match these filters."
    : "No public snapshot has been published yet. The explorer is ready for a curated index.";
}

async function loadIndex() {
  try {
    const response = await fetch("data/entities.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const index = await response.json();
    state.entities = Array.isArray(index.entities) ? index.entities : [];

    const types = [...new Set(state.entities.map((entity) => entity.type))].sort();
    for (const entityType of types) {
      const option = document.createElement("option");
      option.value = entityType;
      option.textContent = entityType.replaceAll("_", " ");
      typeFilter.append(option);
    }

    const generated = new Date(index.generated_at);
    snapshotStatus.textContent = Number.isNaN(generated.valueOf())
      ? "Snapshot metadata unavailable"
      : `Snapshot generated ${generated.toLocaleString()}`;
    render();
  } catch (error) {
    resultCount.textContent = "Public index unavailable";
    snapshotStatus.textContent = "The index could not be loaded.";
    emptyState.hidden = false;
    emptyState.textContent = "Try again later or inspect the deployment workflow on GitHub.";
    console.error(error);
  }
}

searchInput.addEventListener("input", render);
typeFilter.addEventListener("change", render);
loadIndex();
