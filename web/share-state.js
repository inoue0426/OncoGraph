// Canonical external IDs survive snapshot rebuilds; internal UUIDs do not.
const SHARE_FILTERS = new Set(["all", "approved", "civic", "genes", "paths"]);

function updateShareUrl({ entity = null, filter = "all", query = "" } = {}, mode = "push") {
  const url = new URL(window.location.href);
  url.searchParams.delete("entity");
  url.searchParams.delete("filter");
  url.searchParams.delete("q");
  if (entity?.canonical_id) url.searchParams.set("entity", entity.canonical_id);
  if (entity?.type === "disease" && filter !== "all" && SHARE_FILTERS.has(filter)) {
    url.searchParams.set("filter", filter);
  }
  if (!entity && query) url.searchParams.set("q", query);
  if (url.href === window.location.href || mode === "none") return;
  window.history[mode === "replace" ? "replaceState" : "pushState"](null, "", url);
}

function currentShareFilter() {
  const filter = new URL(window.location.href).searchParams.get("filter");
  return SHARE_FILTERS.has(filter) ? filter : "all";
}

function restoreShareUrl() {
  const params = new URL(window.location.href).searchParams;
  const canonicalId = params.get("entity");
  const found = canonicalId && entities.find((item) => item.canonical_id === canonicalId);
  if (found) {
    search.value = "";
    render();
    renderDetail(found.id, { historyMode: "none", filter: currentShareFilter() });
    return;
  }
  if (canonicalId) {
    status.textContent = `Entity ${canonicalId} is not in this snapshot. Search by name below.`;
  }
  closeDetail({ historyMode: "none" });
  search.value = params.get("q") || "";
  render();
  if (canonicalId) status.textContent = `Entity ${canonicalId} is not in this snapshot. Search by name below.`;
}

function renderShareControl(entity) {
  if (!entity.canonical_id) return null;
  const holder = document.createElement("div");
  holder.className = "share-control";
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Copy link to this view";
  const message = document.createElement("span");
  message.setAttribute("role", "status");
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      message.textContent = "Link copied.";
    } catch {
      message.textContent = "Copy the address from your browser's address bar.";
    }
  });
  holder.append(button, message);
  return holder;
}
