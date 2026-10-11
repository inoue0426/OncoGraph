// The workflow imports these eleven bounded sources into a static snapshot.
// Evidence counts are read from the deployed relations, not hard-coded.
const PUBLIC_SOURCES = [
  { name: "HGNC", url: "https://www.genenames.org/", keys: [], scope: "Human gene names and identifiers; entity input only." },
  { name: "Gene Ontology", url: "https://geneontology.org/", keys: ["gene_ontology"], scope: "GO terms and their hierarchy; no gene-to-GO annotation import." },
  { name: "GtoPdb", url: "https://www.guidetopharmacology.org/", keys: ["gtopdb"], scope: "Approved-drug list and primary target interactions." },
  { name: "ClinicalTrials.gov", url: "https://clinicaltrials.gov/", keys: ["clinicaltrials_gov"], scope: "Registry metadata for name-matched drugs; up to 60 returned studies per drug before matching." },
  { name: "Open Targets Platform", url: "https://platform.opentargets.org/", keys: ["open_targets", "open_targets_indications"], scope: "Top-scoring target–disease associations and APPROVAL-stage drug indications for the selected targets/drugs." },
  { name: "DrugMechDB", url: "https://sulab.github.io/DrugMechDB/", keys: ["drugmechdb"], scope: "Curated drug–mechanism–disease path records; limited graph representation." },
  { name: "TRRUST", url: "https://www.grnpedia.org/trrust/", keys: ["trrust"], scope: "Human transcription-factor regulation resolved to HGNC genes." },
  { name: "GTEx", url: "https://gtexportal.org/", keys: ["gtex"], scope: "Aggregate median expression in normal tissues; no individual-level data." },
  { name: "ChEMBL", url: "https://www.ebi.ac.uk/chembl/", keys: ["chembl"], scope: "Mechanism of action records for drugs resolved from the GtoPdb drug-name set." },
  { name: "CIViC", url: "https://civicdb.org/", keys: ["civic"], scope: "Accepted molecular evidence returned for nine selected cancer genes; not the full CIViC database." },
  { name: "Reactome", url: "https://reactome.org/", keys: ["reactome"], scope: "Human pathway memberships for nine selected cancer genes, mapped by exact NCBI Gene IDs in HGNC; not the entire pathway catalog." },
];

function renderDataSources(statsData) {
  const holder = document.querySelector("#source-inventory");
  if (!holder) return;
  const counts = new Map();
  for (const relation of allRelations) {
    for (const ev of relation.evidence || []) {
      if (ev.source) counts.set(ev.source, (counts.get(ev.source) || 0) + 1);
    }
  }

  const date = document.createElement("p");
  date.className = "source-note";
  const generated = statsData?.generated_at;
  date.textContent = generated
    ? `Published index generated: ${generated.replace("T", " ").replace("Z", " UTC")}. Data are refreshed by GitHub Actions; this page does not query the upstream databases live.`
    : "This page uses a periodically generated index, not live upstream queries. Snapshot date is unavailable.";

  const scroll = document.createElement("div");
  scroll.className = "source-table-scroll";
  const table = document.createElement("table");
  const caption = document.createElement("caption");
  caption.textContent = "Sources configured in the public refresh workflow";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["Source", "What is included", "Evidence rows in this snapshot"]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = label;
    headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const source of PUBLIC_SOURCES) {
    const row = document.createElement("tr");
    const name = document.createElement("th");
    name.scope = "row";
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = source.name;
    name.append(link);
    const scope = document.createElement("td");
    scope.textContent = source.scope;
    const evidence = document.createElement("td");
    evidence.textContent = source.keys.length
      ? [...source.keys].reduce((sum, key) => sum + (counts.get(key) || 0), 0).toLocaleString()
      : "— (entity input)";
    row.append(name, scope, evidence);
    body.append(row);
  }
  table.append(caption, head, body);
  scroll.append(table);

  const caveat = document.createElement("p");
  caveat.className = "source-note";
  caveat.textContent = "Evidence rows count links stored in this index, not the number of unique upstream records or the size of each database. Zero means no edge evidence from that source in this snapshot; HGNC contributes gene entities, so an edge count does not apply. Trial registration does not show efficacy or approval.";
  const excluded = document.createElement("p");
  excluded.className = "source-note";
  excluded.textContent = "External references only: OncoKB and COSMIC link to their own sites; their annotations are not imported, counted or labeled as OncoGraph evidence. COSMIC may require login. Not in this public refresh: DGIdb, Europe PMC, openFDA, and the full Reactome, Open Targets or CIViC datasets.";
  holder.replaceChildren(date, scroll, caveat, excluded);
}
