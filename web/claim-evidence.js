// A conservative, deterministic classifier of *retrieved CIViC records*.
// Statuses describe the snapshot only; none are treatment recommendations.
function evaluateEvidenceClaim(tree, { therapy, effect, scope = "variant", limit = 20 }) {
  if (typeof therapy !== "string" || !therapy.trim() || !["sensitivity", "resistance"].includes(effect)
      || !["variant", "profile"].includes(scope)
      || !Number.isInteger(limit) || limit < 1 || limit > 200) throw new Error("Invalid claim query");
  if (!tree || !Array.isArray(tree.evidence) || !tree.query) throw new Error("Invalid evidence tree");
  const normal = (value) => String(value || "").trim().toLowerCase();
  const groups = { supporting: [], opposing: [], disputed: [], context_only: [] };
  const counts = { wrong_therapy: 0, non_predictive: 0, incomplete_profile: 0, unrelated_effect: 0 };
  for (const item of tree.evidence) {
    if (!(item.therapies || []).some((drug) => [drug.id, drug.name].some((name) => normal(name) === normal(therapy)))) {
      counts.wrong_therapy++; continue;
    }
    if (normal(item.evidence_type) !== "predictive") { counts.non_predictive++; continue; }
    const significance = normal(item.significance);
    if (!["sensitivity", "resistance"].includes(significance)) { counts.unrelated_effect++; continue; }
    // An item with incomplete membership or a multi-variant profile cannot
    // prove that this single variant has the reported effect.
    const exactProfile = scope === "profile" && item.profile?.match_type === "profile_only" &&
      normal(item.profile.name) === normal(tree.query.variant);
    if (!exactProfile && (item.profile?.match_type !== "variant_member" || item.profile?.complex_profile)) {
      groups.context_only.push({ ...item, reason: "Variant-specific effect unverified for this molecular profile" });
      counts.incomplete_profile++; continue;
    }
    const direction = normal(item.claim_state);
    if (direction === "supports" && significance === effect) groups.supporting.push(item);
    else if (direction === "supports") groups.opposing.push(item);
    else if (direction === "contradicts" && significance === effect) groups.disputed.push(item);
    else groups.context_only.push({ ...item, reason: "Evidence direction does not establish the requested effect" });
  }
  // Preserve all distinct categories under a bounded display budget. Never
  // silently infer the absence of counterevidence from the displayed subset.
  const totals = Object.fromEntries(Object.entries(groups).map(([key, rows]) => [key, rows.length]));
  const selected = { supporting: [], opposing: [], disputed: [], context_only: [] };
  let remaining = limit;
  for (const key of ["supporting", "opposing", "disputed", "context_only"]) {
    if (remaining && groups[key].length) { selected[key].push(groups[key].shift()); remaining--; }
  }
  for (const key of ["supporting", "opposing", "disputed", "context_only"]) {
    const slice = groups[key].splice(0, remaining);
    selected[key].push(...slice); remaining -= slice.length;
  }
  const incomplete = Boolean(tree.truncated) || Object.entries(totals).some(([key, value]) => selected[key].length < value);
  let status = "not_found_in_snapshot";
  if (incomplete) status = "incomplete_review";
  else if (totals.supporting && (totals.opposing || totals.disputed)) status = "mixed_records";
  else if (totals.supporting) status = "supporting_records";
  else if (totals.opposing || totals.disputed) status = "opposing_or_disputed_records";
  else if (totals.context_only) status = "insufficient_variant_context";
  return { schema_version: "1.0", query: { ...tree.query, therapy: therapy.trim(), effect, scope },
    status, counts: totals, excluded: counts, incomplete,
    evidence: selected, limitations: ["This checks a bounded CIViC snapshot, not treatment efficacy, FDA status or patient suitability.",
      "An opposing report is not necessarily a direct contradiction; study contexts may differ.",
      "No matched record does not establish absence of evidence outside this snapshot."],
  };
}

if (typeof module !== "undefined") module.exports = { evaluateEvidenceClaim };
