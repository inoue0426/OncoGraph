const search = document.querySelector("#search");
const status = document.querySelector("#status");
const results = document.querySelector("#results");
let entities = [];

function render() {
  const query = search.value.trim().toLowerCase();
  const matches = query
    ? entities.filter((entity) =>
        [entity.name, entity.type, entity.canonical_id, entity.description]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query),
      )
    : [];

  results.replaceChildren(
    ...matches.slice(0, 50).map((entity) => {
      const card = document.createElement("article");
      const name = document.createElement("strong");
      const metadata = document.createElement("div");
      name.textContent = entity.name;
      metadata.textContent = `${entity.type} · ${entity.canonical_id || "no canonical ID"}`;
      card.append(name, metadata);
      return card;
    }),
  );
  status.textContent = query ? `${matches.length} matches` : `${entities.length} indexed entities`;
}

fetch("data/search-index.json")
  .then((response) => response.json())
  .then((data) => {
    entities = data;
    render();
  })
  .catch(() => {
    status.textContent = "Search index unavailable";
  });

search.addEventListener("input", render);
