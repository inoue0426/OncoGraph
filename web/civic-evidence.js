// Keep CIViC's molecular profile and its evidence type visible. These records
// may report resistance or contradict a claim; they are not approval labels.
function renderCivicEvidence(entity) {
  const records = [];
  const seen = new Set();
  for (const neighbor of allNeighbors(entity.id)) {
    const other = entityById.get(neighbor.id);
    if (!other) continue;
    for (const evidence of neighbor.evidence || []) {
      if (evidence.source !== "civic" || !evidence.context?.civic_evidence_id) continue;
      const key = `${neighbor.id}:${evidence.source_id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      records.push({ other, predicate: neighbor.predicate, evidence });
    }
  }
  if (!records.length) return null;

  const section = document.createElement("section");
  section.className = "civic-records";
  const heading = document.createElement("h3");
  heading.textContent = `CIViC molecular evidence (${records.length})`;
  const intro = document.createElement("p");
  intro.textContent = "Accepted curated records with their molecular profile and evidence direction. A record is not a treatment recommendation or approval.";
  section.append(heading, intro);

  const filterLabel = document.createElement("label");
  const filter = document.createElement("input");
  filter.type = "checkbox";
  filterLabel.append(filter, " Show only accepted A/B evidence with trust rating ≥ 4/5");
  section.append(filterLabel);

  const list = document.createElement("div");
  section.append(list);

  function draw() {
  list.replaceChildren();
  const selected = filter.checked
    ? records.filter(({ evidence }) => {
        const context = evidence.context || {};
        return ["A", "B"].includes(context.evidence_level)
          && Number(context.evidence_rating) >= 4
          && context.civic_review_status === "ACCEPTED";
      })
    : records;
  if (!selected.length) {
    const empty = document.createElement("p");
    empty.textContent = "No evidence in this snapshot meets this filter.";
    list.append(empty);
  }

  for (const { other, predicate, evidence } of selected.slice(0, 12)) {
    const card = document.createElement("div");
    card.className = "civic-record";
    const title = document.createElement("strong");
    title.textContent = `${other.name} · ${predicate.replaceAll("_", " ")}`;
    const context = evidence.context || {};
    const profile = document.createElement("p");
    const variants = context.profile_variants || (context.variant_name
      ? [`${context.gene_name || ""} ${context.variant_name}`.trim()] : []);
    profile.textContent = `Molecular profile: ${context.molecular_profile || "not specified"} · Listed variants: ${variants.length ? variants.join(", ") : "not specified"}${context.variant_hgvs ? ` · HGVS: ${context.variant_hgvs}` : ""}`;
    const specifics = document.createElement("p");
    specifics.textContent = [context.civic_evidence_type, context.evidence_level && `level ${context.evidence_level}`, context.evidence_rating && `trust ${context.evidence_rating}/5`, context.significance, evidence.claim_state, context.civic_review_status || "ACCEPTED"]
      .filter(Boolean).join(" · ");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "evidence-link";
    button.textContent = `Inspect CIViC record ${context.civic_evidence_id || evidence.source_id || ""}`;
    button.addEventListener("click", () => showEvidencePanel({ entity: other, predicate, evidence: [evidence] }));
    card.append(title, profile, specifics, button);
    if (context.gene_name && /^[A-Za-z0-9-]+$/.test(context.gene_name)) {
      const external = document.createElement("p");
      const oncokb = document.createElement("a");
      oncokb.href = `https://www.oncokb.org/gene/${encodeURIComponent(context.gene_name)}`;
      oncokb.textContent = "OncoKB gene (external)";
      const cosmic = document.createElement("a");
      cosmic.href = `https://cancer.sanger.ac.uk/cosmic/search?q=${encodeURIComponent(variants.length === 1 ? variants[0] : context.gene_name)}`;
      cosmic.textContent = "COSMIC search (external; login may be required)";
      for (const link of [oncokb, cosmic]) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      external.append(oncokb, " · ", cosmic);
      card.append(external);
    }
    list.append(card);
  }
  if (selected.length > 12) {
    const more = document.createElement("p");
    more.className = "trail-count";
    more.textContent = `Showing 12 of ${selected.length} CIViC records. All relations appear below.`;
    list.append(more);
  }
  }
  filter.addEventListener("change", draw);
  draw();
  return section;
}
