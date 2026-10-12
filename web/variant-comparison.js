// Comparison uses only accepted CIViC records already in the published index.
// An evidence item belongs to a molecular profile; the listed variants may
// describe a complex profile, so membership alone is never a treatment claim.
function buildVariantComparisonRows(relations, byId) {
  const items = new Map();
  for (const relation of relations) {
    if (!["clinically_evidenced_for", "has_civic_evidence_for"].includes(relation.predicate)) continue;
    const disease = byId.get(relation.object_id);
    if (!disease || disease.type !== "disease") continue;
    const therapy = relation.predicate === "clinically_evidenced_for"
      ? byId.get(relation.subject_id) : null;
    for (const evidence of relation.evidence || []) {
      const context = evidence.context || {};
      if (evidence.source !== "civic" || context.civic_review_status !== "ACCEPTED"
          || !context.civic_evidence_id || !context.molecular_profile_id
          || !context.gene_name) continue;
      const explicitVariants = Array.isArray(context.profile_variants)
        && context.profile_variants.length > 0;
      const variants = explicitVariants ? context.profile_variants
        : context.molecular_profile ? [`Profile: ${context.molecular_profile}`] : [];
      if (!variants.length) continue;
      const evidenceId = String(context.civic_evidence_id);
      const profileId = String(context.molecular_profile_id);
      const key = [evidenceId, profileId, disease.canonical_id].join("|");
      if (!items.has(key)) items.set(key, {
        id: evidenceId,
        profileId,
        profileName: context.molecular_profile || `CIViC profile ${profileId}`,
        gene: context.gene_name,
        variants,
        hasExplicitVariants: explicitVariants,
        disease,
        type: context.civic_evidence_type,
        significance: context.significance,
        level: context.evidence_level,
        rating: context.evidence_rating,
        claim: evidence.claim_state?.toLowerCase() || "uncertain",
        therapies: new Map(),
      });
      if (therapy?.type === "drug") items.get(key).therapies.set(therapy.canonical_id, therapy);
    }
  }
  const rows = [];
  for (const item of items.values()) {
    const therapies = [...item.therapies.values()];
    for (const drug of therapies.length ? therapies : [null]) rows.push({ ...item, drug });
  }
  return rows;
}

function civicComparisonCategory(row) {
  if (row.claim === "contradicts") return "contradicts";
  if (row.type !== "PREDICTIVE" || row.claim !== "supports") return "other";
  const significance = (row.significance || "").toUpperCase();
  if (significance.includes("RESISTANCE") || significance.includes("REDUCED_SENSITIVITY")) {
    return "resistance";
  }
  if (significance.includes("SENSITIVITY") || significance.includes("RESPONSE")) return "sensitivity";
  return "other";
}

function renderVariantComparison(relations, byId) {
  const section = document.querySelector("#variant-comparison");
  if (!section) return;
  const allRows = buildVariantComparisonRows(relations, byId);
  const heading = document.createElement("h2");
  heading.textContent = "Compare variant evidence";
  const intro = document.createElement("p");
  intro.textContent = "Compare accepted CIViC evidence by gene, molecular profile and cancer type. Updated snapshots also list each profile's variants. Counts are evidence items, not patients or independent studies. No treatment recommendation is calculated.";
  if (!allRows.length) {
    const empty = document.createElement("p");
    empty.textContent = "No comparable CIViC molecular-profile records are present in this published snapshot.";
    section.replaceChildren(heading, intro, empty);
    return;
  }

  const controls = document.createElement("div");
  controls.className = "variant-controls";
  const geneSelect = document.createElement("select");
  const variantSelect = document.createElement("select");
  const diseaseSelect = document.createElement("select");
  const highLabel = document.createElement("label");
  const highOnly = document.createElement("input");
  highOnly.type = "checkbox";
  highLabel.append(highOnly, " Accepted A/B and trust ≥ 4/5 only");
  const summary = document.createElement("p");
  summary.className = "variant-summary";
  const tableHolder = document.createElement("div");
  tableHolder.className = "variant-table-scroll";
  const note = document.createElement("p");
  note.className = "variant-note";
  note.textContent = "Sensitivity and resistance refer to a CIViC evidence item's significance, in its recorded disease and molecular-profile context. Contradicts means the record does not support its stated claim. A complex profile may list more than one variant; its evidence is not assigned to any member alone. In older snapshots, Profile: means variant membership was not exported. Empty results mean no matching row in this bounded snapshot.";

  function labelSelect(label, select) {
    const holder = document.createElement("label");
    holder.append(document.createTextNode(label), select);
    return holder;
  }
  controls.append(labelSelect("Gene", geneSelect), labelSelect("Variant or profile", variantSelect),
    labelSelect("Cancer type", diseaseSelect), highLabel);

  function options(select, values, chosen) {
    select.replaceChildren(...values.map(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      return option;
    }));
    if (values.some(([value]) => value === chosen)) select.value = chosen;
  }

  const genes = [...new Set(allRows.map((row) => row.gene))].sort();
  options(geneSelect, genes.map((name) => [name, name]), genes.includes("EGFR") ? "EGFR" : genes[0]);

  function refreshVariants() {
    const variants = [...new Set(allRows.filter((row) => row.gene === geneSelect.value)
      .flatMap((row) => row.variants))].sort();
    const preferred = geneSelect.value === "EGFR" ? `${geneSelect.value} T790M`
      : geneSelect.value === "BRAF" ? `${geneSelect.value} V600E` : "";
    options(variantSelect, variants.map((value) => [value, value]),
      variants.includes(preferred) ? preferred : variants[0]);
    refreshDiseases();
  }

  function refreshDiseases() {
    const previous = diseaseSelect.value;
    const diseases = new Map(allRows.filter((row) => row.gene === geneSelect.value
      && row.variants.includes(variantSelect.value)).map((row) => [row.disease.canonical_id, row.disease.name]));
    options(diseaseSelect, [["", "All cancer types"], ...[...diseases].sort((a, b) => a[1].localeCompare(b[1]))], previous);
    draw();
  }

  function draw() {
    const rows = allRows.filter((row) => row.gene === geneSelect.value
      && row.variants.includes(variantSelect.value)
      && (!diseaseSelect.value || row.disease.canonical_id === diseaseSelect.value)
      && (!highOnly.checked || (["A", "B"].includes(row.level) && Number(row.rating) >= 4)));
    const groups = new Map();
    for (const row of rows) {
      const key = [row.profileId, row.disease.canonical_id, row.drug?.canonical_id || "none"].join("|");
      if (!groups.has(key)) groups.set(key, { row, categories: new Map() });
      const category = civicComparisonCategory(row);
      if (!groups.get(key).categories.has(category)) groups.get(key).categories.set(category, new Map());
      groups.get(key).categories.get(category).set(row.id, row);
    }
    const sorted = [...groups.values()].sort((a, b) =>
      a.row.disease.name.localeCompare(b.row.disease.name)
      || (a.row.drug?.name || "").localeCompare(b.row.drug?.name || "")
      || a.row.profileName.localeCompare(b.row.profileName));
    summary.textContent = `${new Set(rows.map((row) => row.id)).size} distinct CIViC evidence items across ${groups.size} disease / profile / therapy groups.`;
    if (!groups.size) {
      tableHolder.textContent = "No matching records in this published snapshot.";
      return;
    }
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const label of ["Cancer type / profile", "Therapy", "Sensitivity", "Resistance", "Contradicts", "Other", "Inspect source"]){
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = label;
      headRow.append(cell);
    }
    head.append(headRow);
    const body = document.createElement("tbody");
    for (const group of sorted.slice(0, 50)) {
      const tr = document.createElement("tr");
      const profile = document.createElement("td");
      const name = document.createElement("strong");
      name.textContent = group.row.disease.name;
      const profileInfo = document.createElement("small");
      profileInfo.textContent = `${group.row.profileName} (${!group.row.hasExplicitVariants
        ? "variant members unavailable" : group.row.variants.length === 1
          ? "single listed variant" : "complex profile"})`;
      profile.append(name, profileInfo);
      const therapy = document.createElement("td");
      therapy.textContent = group.row.drug?.name || "No indexed therapy";
      tr.append(profile, therapy);
      for (const category of ["sensitivity", "resistance", "contradicts", "other"]) {
        const cell = document.createElement("td");
        cell.textContent = String(group.categories.get(category)?.size || 0);
        tr.append(cell);
      }
      const citations = document.createElement("td");
      for (const item of [...new Map([...group.categories.values()].flatMap((entries) => [...entries])
        .map(([id, row]) => [id, row])).values()].sort((a, b) => Number(a.id) - Number(b.id))) {
        const link = document.createElement("a");
        link.href = `https://civicdb.org/links/evidence/${encodeURIComponent(item.id)}`;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = `EID${item.id} · ${item.type || "unknown"} · ${item.significance || "unknown"} · ${item.claim} · level ${item.level || "?"} · trust ${item.rating ?? "?"}/5`;
        citations.append(link, document.createElement("br"));
      }
      tr.append(citations);
      body.append(tr);
    }
    table.append(head, body);
    tableHolder.replaceChildren(table);
    if (sorted.length > 50) {
      const truncated = document.createElement("p");
      truncated.textContent = `Showing 50 of ${sorted.length} groups. Select a cancer type to narrow the results.`;
      tableHolder.append(truncated);
    }
  }

  geneSelect.addEventListener("change", refreshVariants);
  variantSelect.addEventListener("change", refreshDiseases);
  diseaseSelect.addEventListener("change", draw);
  highOnly.addEventListener("change", draw);
  section.replaceChildren(heading, intro, controls, summary, tableHolder, note);
  refreshVariants();
}
