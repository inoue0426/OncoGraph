// Keep CIViC's molecular profile and its evidence type visible. These records
// may report resistance or contradict a claim; they are not approval labels.
function renderCivicEvidence(entity) {
  const records = [];
  const seen = new Set();
  for (const neighbor of allNeighbors(entity.id)) {
    const other = entityById.get(neighbor.id);
    if (!other) continue;
    for (const evidence of neighbor.evidence || []) {
      if (evidence.source !== "civic") continue;
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

  for (const { other, predicate, evidence } of records.slice(0, 12)) {
    const card = document.createElement("div");
    card.className = "civic-record";
    const title = document.createElement("strong");
    title.textContent = `${other.name} · ${predicate.replaceAll("_", " ")}`;
    const context = evidence.context || {};
    const profile = document.createElement("p");
    profile.textContent = `Molecular profile: ${context.molecular_profile || "not specified"} · ${context.gene_name || "gene unknown"}`;
    const specifics = document.createElement("p");
    specifics.textContent = [context.civic_evidence_type, context.evidence_level && `level ${context.evidence_level}`, context.significance, evidence.claim_state, context.civic_review_status || "ACCEPTED"]
      .filter(Boolean).join(" · ");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "evidence-link";
    button.textContent = `Inspect CIViC record ${context.civic_evidence_id || evidence.source_id || ""}`;
    button.addEventListener("click", () => showEvidencePanel({ entity: other, predicate, evidence: [evidence] }));
    card.append(title, profile, specifics, button);
    section.append(card);
  }
  if (records.length > 12) {
    const more = document.createElement("p");
    more.className = "trail-count";
    more.textContent = `Showing 12 of ${records.length} CIViC records. All relations appear below.`;
    section.append(more);
  }
  return section;
}
