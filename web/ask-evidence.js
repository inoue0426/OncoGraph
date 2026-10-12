// Browser-only retrieval. Returned records are graph facts, not an LLM answer.
function findQuestionEvidence(question, entities, relations, maxRecords = 12) {
  if (typeof question !== "string" || question.trim().length < 3 || question.length > 500) {
    throw new Error("Enter a question between 3 and 500 characters.");
  }
  const query = question.toLocaleLowerCase();
  const boundary = (char) => !char || !/[\p{L}\p{N}]/u.test(char);
  const matches = entities.filter((entity) => {
    const names = [entity.name, entity.canonical_id,
      ...(Array.isArray(entity.metadata?.aliases) ? entity.metadata.aliases : [])];
    return names.some((name) => {
      if (typeof name !== "string" || name.length < 3) return false;
      const candidate = name.toLocaleLowerCase();
      const index = query.indexOf(candidate);
      return index !== -1 && boundary(query[index - 1]) && boundary(query[index + candidate.length]);
    });
  }).sort((a, b) => b.name.length - a.name.length).slice(0, 8);
  const ids = new Set(matches.map((entity) => String(entity.id)));
  const byId = new Map(entities.map((entity) => [String(entity.id), entity]));
  const candidates = relations.filter((relation) => ids.has(String(relation.subject_id)) || ids.has(String(relation.object_id)))
    .filter((relation) => (relation.evidence || []).some((item) => item.source))
    .sort((a, b) => {
      const score = (row) => Number(ids.has(String(row.subject_id))) + Number(ids.has(String(row.object_id)));
      return score(b) - score(a);
    });
  const records = candidates.slice(0, maxRecords).map((relation, index) => ({
    id: `R${index + 1}`,
    subject: byId.get(String(relation.subject_id))?.name || "Unresolved entity",
    predicate: relation.predicate,
    object: byId.get(String(relation.object_id))?.name || "Unresolved entity",
    sources: (relation.evidence || []).filter((item) => item.source).slice(0, 3).map((item) => ({
      source: item.source, source_id: item.source_id || null,
      source_url: item.source_url || null,
      evidence_type: item.evidence_type || null,
      claim_state: item.claim_state?.toLowerCase() || "uncertain",
      significance: typeof item.context === "object" ? item.context?.significance || null : null,
      molecular_profile: typeof item.context === "object" ? item.context?.molecular_profile || null : null,
    })),
  }));
  return { question: question.trim(), matches: matches.map((e) => ({ name: e.name, type: e.type })),
    records, omitted: candidates.length > maxRecords, scope: "Published snapshot; literal entity-name matching" };
}

function renderAskEvidence(entities, relations) {
  const holder = document.querySelector("#ask-evidence");
  if (!holder) return;
  const form = document.createElement("form");
  const label = document.createElement("label"); label.htmlFor = "ask-question"; label.textContent = "Question";
  const input = document.createElement("input"); input.id = "ask-question";
  input.type = "search"; input.required = true; input.maxLength = 500;
  input.placeholder = "e.g. What evidence mentions EGFR?";
  const submit = document.createElement("button"); submit.type = "submit"; submit.textContent = "Find source records";
  form.append(label, input, submit);
  const status = document.createElement("p"); status.setAttribute("role", "status");
  const output = document.createElement("div");
  holder.replaceChildren(form, status, output);

  form.addEventListener("submit", (event) => {
    event.preventDefault(); output.replaceChildren();
    let bundle;
    try { bundle = findQuestionEvidence(input.value, entities, relations); }
    catch (error) { status.textContent = error.message; return; }
    status.textContent = bundle.records.length
      ? `Showing ${bundle.records.length}${bundle.omitted ? " of more" : ""} source-backed relationship(s) for ${bundle.matches.map((m) => m.name).join(", ")}. Literal name matching; these records do not answer every part of the question.`
      : "No source-backed relationships found by literal name matching in this snapshot. Try an exact entity name in graph search.";
    for (const record of bundle.records) {
      const card = document.createElement("article"); card.className = "ask-record";
      const heading = document.createElement("h3");
      heading.textContent = `[${record.id}] ${record.subject} —${record.predicate}→ ${record.object}`;
      card.append(heading);
      for (const source of record.sources) {
        const line = document.createElement("p");
        line.textContent = `${source.source}${source.source_id ? ` · ${source.source_id}` : ""} · ${source.evidence_type || "type unreported"} · ${source.claim_state}${source.significance ? ` · ${source.significance}` : ""}${source.molecular_profile ? ` · profile: ${source.molecular_profile}` : ""}`;
        if (source.source_url && /^https:\/\//i.test(source.source_url)) {
          const link = document.createElement("a"); link.href = source.source_url;
          link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "Original source";
          line.append(" · ", link);
        }
        card.append(line);
      }
      output.append(card);
    }
    if (!bundle.records.length) return;
    const copy = document.createElement("button"); copy.type = "button";
    copy.textContent = "Copy grounded prompt";
    copy.addEventListener("click", async () => {
      const prompt = `Research question: ${bundle.question}\nUse only these OncoGraph records; say when evidence is missing or contradictory. Cite record IDs [R1], [R2], etc. No treatment advice or FDA claims.\n${JSON.stringify(bundle.records, null, 2)}`;
      try { await navigator.clipboard.writeText(prompt); copy.textContent = "Copied"; }
      catch { status.textContent = "Clipboard access unavailable in this browser."; }
    });
    output.append(copy);
    if (!["localhost", "127.0.0.1"].includes(location.hostname)) return;
    const explain = document.createElement("button"); explain.type = "button";
    explain.textContent = "Explain with local Ollama";
    const llmResult = document.createElement("p"); llmResult.className = "ask-generated";
    explain.addEventListener("click", async () => {
      explain.disabled = true; llmResult.textContent = "Waiting for your local model…";
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 120000);
        let response;
        try { response = await fetch("/api/local-answer", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: bundle.question, records: bundle.records }), signal: controller.signal }); }
        finally { clearTimeout(timer); }
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Local model unavailable");
        llmResult.textContent = `Model-generated explanation (verify against the records above): ${data.answer}`;
      } catch (error) { llmResult.textContent = `Local model unavailable: ${error.message}. See the local setup instructions.`; }
      finally { explain.disabled = false; }
    });
    output.append(explain, llmResult);
  });
}

if (typeof module !== "undefined") module.exports = { findQuestionEvidence };
