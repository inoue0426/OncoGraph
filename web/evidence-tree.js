// Same v1 response contract as the local Python API, projected from Pages JSON.
function buildEvidenceTree(entities, relations, { gene, variant, disease, jurisdiction = "US", limit = 50 }) {
  if (jurisdiction !== "US" || ![gene, variant, disease].every((value) => typeof value === "string" && value.trim())
      || !Number.isInteger(limit) || limit < 1 || limit > 200) throw new Error("Invalid evidence tree query");
  const byId = new Map(entities.map((item) => [String(item.id), item]));
  const grouped = new Map();
  const normal = (value) => String(value || "").trim().toLowerCase();
  for (const relation of relations) {
    if (!["has_civic_evidence_for", "clinically_evidenced_for"].includes(relation.predicate)) continue;
    const cancer = byId.get(String(relation.object_id));
    if (normal(cancer?.type) !== "disease" || ![normal(cancer.canonical_id), normal(cancer.name)].includes(normal(disease))) continue;
    const therapy = relation.predicate === "clinically_evidenced_for" ? byId.get(String(relation.subject_id)) : null;
    for (const evidence of relation.evidence || []) {
      let ctx = evidence.context || {};
      if (typeof ctx === "string") { try { ctx = JSON.parse(ctx); } catch { continue; } }
      if (evidence.source !== "civic" || ctx.civic_review_status !== "ACCEPTED" || !ctx.civic_evidence_id
          || !ctx.molecular_profile_id || normal(ctx.gene_name) !== normal(gene)) continue;
      const members = Array.isArray(ctx.profile_variants) ? ctx.profile_variants : [];
      const names = members.map(normal);
      const profileName = normal(ctx.molecular_profile);
      const match = names.length && (names.includes(normal(variant)) || names.includes(`${normal(gene)} ${normal(variant)}`))
        ? "variant_member" : !names.length && [profileName,
          profileName.startsWith(`${normal(gene)} `) ? profileName.slice(normal(gene).length + 1) : profileName].includes(normal(variant))
          ? "profile_only" : null;
      if (!match) continue;
      const evidenceId = String(ctx.civic_evidence_id);
      const profileId = String(ctx.molecular_profile_id);
      const key = [evidenceId, profileId, normal(cancer.canonical_id)].join("|");
      if (!grouped.has(key)) grouped.set(key, {
        evidence_id: evidenceId,
        profile: { id: profileId, name: ctx.molecular_profile || null, variants: members,
          match_type: match, complex_profile: members.length > 1 },
        disease: { id: cancer.canonical_id || null, name: cancer.name },
        evidence_type: ctx.civic_evidence_type || null, level: ctx.evidence_level || null,
        rating: ctx.evidence_rating ?? null, significance: ctx.significance || null,
        claim_state: normal(evidence.claim_state || "uncertain"), source: "civic",
        source_id: evidence.source_id || null, source_url: evidence.source_url || null,
        citation_url: ctx.citation_url || null, retrieved_at: evidence.retrieved_at || null, therapies: [],
      });
      if (normal(therapy?.type) === "drug") {
        const drug = { id: therapy.canonical_id || null, name: therapy.name };
        const therapies = grouped.get(key).therapies;
        if (!therapies.some((item) => item.id === drug.id && item.name === drug.name)) therapies.push(drug);
      }
    }
  }
  const records = [...grouped.values()].sort((a, b) => a.evidence_id.localeCompare(b.evidence_id, "en", { numeric: false })
    || a.profile.id.localeCompare(b.profile.id));
  return { schema_version: "1.0", query: { gene: gene.trim(), variant: variant.trim(), disease: disease.trim(), jurisdiction },
    status: records.length ? "matched" : "not_found_in_snapshot", total_evidence_items: records.length,
    truncated: records.length > limit, evidence: records.slice(0, limit),
    us_regulatory_label: { status: "not_integrated", source: null },
    civic_assertions: { status: "not_integrated", source: null },
    limitations: ["Accepted CIViC evidence items are literature records, not FDA approvals or treatment recommendations.",
      "Variant membership in a complex profile does not attribute evidence to that variant alone.",
      "Absence from this bounded snapshot does not establish absence of evidence."],
  };
}

function renderEvidenceTree(entities, relations) {
  const section = document.querySelector("#evidence-tree");
  if (!section) return;
  const form = document.createElement("form");
  const inputs = ["gene", "variant", "disease"].map((name) => {
    const label = document.createElement("label");
    const field = document.createElement("input");
    field.required = true;
    field.name = name;
    field.placeholder = { gene: "EGFR", variant: "T790M", disease: "Exact cancer name or DOID" }[name];
    label.append(document.createTextNode(`${name[0].toUpperCase()}${name.slice(1)} `), field);
    form.append(label);
    return field;
  });
  const therapyLabel = document.createElement("label");
  const therapy = document.createElement("input");
  therapy.name = "therapy"; therapy.placeholder = "e.g. osimertinib (optional)";
  therapyLabel.append("Therapy ", therapy);
  form.append(therapyLabel);
  const scopeLabel = document.createElement("label");
  const scope = document.createElement("select");
  for (const [value, label] of [["variant", "Single variant (verified membership)"],
    ["profile", "Exact complete CIViC molecular profile name"]]) {
    const option = document.createElement("option"); option.value = value; option.textContent = label;
    scope.append(option);
  }
  scopeLabel.append("Interpret input as ", scope);
  form.append(scopeLabel);
  const effectLabel = document.createElement("label");
  const effect = document.createElement("select");
  for (const value of ["sensitivity", "resistance"]) {
    const option = document.createElement("option"); option.value = value;
    option.textContent = value === "sensitivity" ? "Sensitivity" : "Resistance";
    effect.append(option);
  }
  effectLabel.append("Check report of ", effect);
  form.append(effectLabel);
  const button = document.createElement("button");
  button.textContent = "Find evidence";
  form.append(button);
  const result = document.createElement("div");
  function show() {
    const tree = buildEvidenceTree(entities, relations,
      { gene: inputs[0].value, variant: inputs[1].value, disease: inputs[2].value,
        limit: therapy.value.trim() ? 200 : 50 });
    result.replaceChildren();
    const claim = therapy.value.trim() ? evaluateEvidenceClaim(tree,
      { therapy: therapy.value, effect: effect.value, scope: scope.value }) : null;
    const summary = document.createElement("p");
    summary.textContent = claim
      ? `Snapshot check (${claim.query.scope === "profile" ? "whole molecular profile" : "single variant"}): ${claim.status.replaceAll("_", " ")}. ${claim.counts.supporting} supporting; ${claim.counts.opposing} opposing reports; ${claim.counts.disputed} disputing the stated effect; ${claim.counts.context_only} context only. ${claim.incomplete ? "Results are incomplete. " : ""}This is not a treatment recommendation. Exact therapy name or ID required.`
      : `${tree.total_evidence_items} accepted CIViC evidence item(s) in this snapshot. FDA labels and CIViC assertions: not integrated. No match does not mean no evidence exists.`;
    result.append(summary);
    const rows = claim ? Object.entries(claim.evidence).flatMap(([group, items]) => items.map((item) => ({ group, item })))
      : tree.evidence.map((item) => ({ group: "", item }));
    for (const { group, item } of rows) {
      const card = document.createElement("article");
      const title = document.createElement("h3");
      title.textContent = `${group ? `${group.replaceAll("_", " ")} · ` : ""}${item.profile.name || item.profile.id} → ${item.disease.name} · CIViC EID ${item.evidence_id}`;
      const detail = document.createElement("p");
      detail.textContent = `${item.profile.match_type === "profile_only" ? "Profile name match; variant membership unverified" : "Variant belongs to this profile"}${item.profile.complex_profile ? " (complex profile; not attributable to one variant)" : ""} · ${item.claim_state} · ${item.evidence_type || "type unreported"} · ${item.significance || "significance unreported"} · level ${item.level || "unreported"} · rating ${item.rating ?? "unreported"}. Therapies: ${item.therapies.map((drug) => drug.name).join(", ") || "none recorded"}.`;
      card.append(title, detail);
      if (item.reason) {
        const reason = document.createElement("p"); reason.textContent = item.reason;
        card.append(reason);
      }
      for (const [label, href] of [["CIViC record", item.source_url], ["Cited source", item.citation_url]]) {
        if (!href || !/^https:\/\//i.test(href)) continue;
        const a = document.createElement("a");
        a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = label;
        card.append(a, document.createTextNode(" "));
      }
      result.append(card);
    }
    const exportButton = document.createElement("button");
    exportButton.type = "button"; exportButton.textContent = "Download JSON";
    exportButton.addEventListener("click", () => {
      const href = URL.createObjectURL(new Blob([JSON.stringify(claim || tree, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = href; link.download = "evidence-tree.json"; link.click();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    });
    result.append(exportButton);
  }
  form.addEventListener("submit", (event) => { event.preventDefault(); show(); });
  section.replaceChildren(form, result);
}

if (typeof module !== "undefined") module.exports = { buildEvidenceTree };
