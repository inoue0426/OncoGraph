# OncoGraph

**An evidence-first, provenance-aware knowledge graph for oncology research**

[**Explore OncoGraph**](https://inoue0426.github.io/OncoGraph/) · [**Data sources**](#data-sources-and-refresh) · [**Quick start**](#quick-start) · [**Documentation**](#documentation) · [**Benchmarks**](#retrieval-and-benchmarks)

OncoGraph connects drugs, targets, diseases, publications, and clinical trials to the evidence supporting their relationships. Its central principle is **provenance first**: an edge is more than a link between entities. Each relationship can retain its source, original identifier, biological or clinical context, extraction method, confidence, and verification state.

The project includes a public, searchable explorer, a Python API and graph-query layer, source adapters, and a Model Context Protocol (MCP) interface for research agents.

> **Research use only.** OncoGraph is not intended for diagnosis, treatment selection, or other clinical decision-making.

## Explore the graph

**Live explorer:** https://inoue0426.github.io/OncoGraph/

The GitHub Pages explorer searches a generated public entity index. Selecting a drug displays known targets, related trials, and diseases associated with those targets.

### How to interpret results

- **Search is deterministic.** The explorer matches entity names, canonical identifiers, and registered aliases. A query such as `<disease name> drugs` follows stored `Disease ← Gene ← Drug` relationships from the matched disease. It does not infer missing paths or synonyms.
- **Every result needs a reason.** Result cards explain why an item is shown. Detail views expose the underlying relationships and evidence, including available source names, source IDs, URLs, retrieval dates or releases, and evidence types.
- **Evidence types are distinct.** `approved_indication`, `clinical_trial_enrollment`, and `target_disease_association` must not be conflated. A trial registry entry demonstrates that a study was registered; it does **not** establish efficacy or regulatory approval.
- **Disagreements stay visible.** Evidence from multiple sources remains separate rather than being merged into artificially stronger support. If supporting and contradicting evidence coexist, the explorer flags the conflict. Missing evidence is not filled in by inference.

The public explorer covers only relationships present in its published index; absence from results does not mean that a biological association does not exist.

The public refresh requests up to **60 trial records per approved drug** (then keeps only intervention-name matches) and the **top 20 target–disease associations per target** with score ≥ 0.4. Both are bounded snapshots, not exhaustive catalogs; these limits apply to newly generated indexes after a data refresh.

### Follow an evidence path

In the explorer, choose a suggested drug, press **Surprise me**, or search for one, then open **Trace an evidence path**. Filter connected diseases by name and connection type, and inspect direct drug–disease relations separately from recorded drug → gene → disease paths. Each step opens its own provenance records. The path count is not a measure of evidence strength, and a target–disease link does not demonstrate an approved indication or clinical benefit.

### Browse cancer names and molecular evidence

**Compare variant evidence** on the homepage groups CIViC records by gene, molecular profile, cancer type and indexed therapy. It shows separate counts and source links for sensitivity, resistance, contradictions and other evidence, with an optional accepted level A/B and trust ≥4/5 filter. New snapshots also show listed variants; complex profiles are marked explicitly, and their evidence cannot be assigned to one member variant. Older snapshots display profile names with an explicit "variant members unavailable" label.

A [20-question review queue](data/benchmarks/variant_review_queue.json) and [independent evaluation protocol](docs/VARIANT_COMPARISON_EVALUATION.md) accompany the feature. These questions have **no gold answers yet**: source verification and independent domain review must occur before they can be scored or used to claim biomedical accuracy.

**Explore by cancer name** groups disease entities currently in the public index using explicit matches on their names. Open a subtype to inspect its direct relations and, when available, accepted CIViC molecular-profile evidence. The groups are a browsing shortcut, not a complete ontology or a claim that all matching diseases are equivalent.

CIViC records retain their molecular profile, named variants, HGVS expression when available, evidence type, level, trust rating, significance, review status, source record, and support/contradiction direction. A profile can contain multiple variants; its clinical evidence does not necessarily apply to each member. Filter to accepted level A/B records rated at least 4/5 by CIViC to focus on stronger study-level evidence; this does not guarantee a positive result or clinical actionability. OncoKB and COSMIC are outbound lookups only; their content is not imported or graded here, and COSMIC may require login.

Reactome human pathway memberships for the same nine genes are browsable from those gene and pathway entries. Membership is pathway context, not proof of drug efficacy or a causal gene–disease relationship.

### Disease evidence overview and shareable views

Open a disease to see separate sections for Open Targets approved-stage drug indications, CIViC molecular profiles, related genes, and two-step drug–gene–disease paths. Use **Show evidence type** to focus one section. The approval-stage data is not a jurisdiction-specific prescribing label; a two-step path is a research lead, not an indication. The full relation inventory is available under **All recorded relations and evidence**.

**Copy link to this view** saves the entity's external canonical ID and, for diseases, the selected evidence section in the URL. Search queries can also be linked. Browser back/forward restores these views after the index loads. A previously shared entity may disappear from a later snapshot; in that case the explorer reports that it is missing and offers search. No account or server-side storage is involved.

## How OncoGraph works

```text
Public / permitted upstream sources
               |
        Source adapters
               |
    Normalization + validation
               |
         Entity / Relation
               |
             Evidence
               |
      Graph queries / MCP API
               |
     Explorer and research tools
```

### Data model

```text
Entity ──< Relation >── Entity
              │
              └──< Evidence
```

The core entity types include `Drug`, `Target`, `Disease`, `Paper`, and `Trial`. Directed relations link entities, while evidence records preserve traceability. Stable external identifiers are preferred over name-only matching.

The source-adapter layer (`oncograph.sources`) emits normalized candidates without directly changing the database. `oncograph.importing` validates records before persistence, and `oncograph.normalization` standardizes external identifier namespaces.

## Quick start

From the repository root:

```bash
git clone https://github.com/inoue0426/OncoGraph.git
cd OncoGraph
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
oncograph seed
uvicorn oncograph.main:app --reload
```

Open **http://127.0.0.1:8000/docs** for the interactive API documentation.

The seed command sets up a local starting graph; it is not the same as rebuilding the full public index from upstream sources.

### MCP server for research agents

```bash
pip install -e '.[mcp]'
oncograph-mcp
```

This serves graph tools via the [Model Context Protocol](https://modelcontextprotocol.io) using stdio. See [docs/MCP.md](docs/MCP.md) for tool definitions, retrieval strategies, and provenance semantics.

## Data sources and refresh

**The public explorer uses a generated snapshot, not live database connections.** The scheduled/manual [`refresh-data.yml`](.github/workflows/refresh-data.yml) workflow imports the following eleven scoped inputs into temporary SQLite, exports the site index, and uploads it as a build artifact. [`pages.yml`](.github/workflows/pages.yml) publishes the latest successful artifact. The site shows the snapshot generation time and counts evidence rows by source under **Data sources**; those counts are neither unique upstream record counts nor the size of the original databases. Raw downloads and SQLite are not committed to Git. See [hosting documentation](docs/HOSTING.md).

| Input in public refresh | What is actually included |
| --- | --- |
| [HGNC](https://www.genenames.org/) | Human gene names and identifiers; gene entities, not gene–disease evidence |
| [Gene Ontology](https://geneontology.org/) | GO terms and their ontology hierarchy; no gene-to-GO annotation dataset |
| [GtoPdb](https://www.guidetopharmacology.org/) | Its approved-drug/primary-target subset and target-to-HGNC mapping; not all ligands |
| [ClinicalTrials.gov](https://clinicaltrials.gov/) | Registry metadata for GtoPdb drug-name matches, up to 60 returned studies per drug before intervention-name filtering; registration does not establish efficacy |
| [Open Targets Platform](https://platform.opentargets.org/) | Top 20 target–disease associations per selected target (score ≥ 0.4) and APPROVAL-stage indications for matched drugs; not a full platform export or jurisdiction-specific label |
| [DrugMechDB](https://sulab.github.io/DrugMechDB/) | Curated drug–mechanism–disease paths, with a limited graph representation of each path |
| [TRRUST](https://www.grnpedia.org/trrust/) | Human transcription-factor/target regulation resolved to HGNC identifiers |
| [GTEx](https://gtexportal.org/) | Open aggregate median expression in normal tissues; no individual-level data |
| [ChEMBL](https://www.ebi.ac.uk/chembl/) | Mechanism-of-action data looked up for the GtoPdb approved-drug name set |
| [CIViC](https://civicdb.org/) | Accepted molecular evidence returned for nine selected cancer genes; not the full database |
| [Reactome](https://reactome.org/) | Human pathway memberships for those nine genes, matched by exact NCBI Gene ID from HGNC; not all Reactome mappings |

**External references only:** [OncoKB](https://www.oncokb.org/) and [COSMIC](https://cancer.sanger.ac.uk/cosmic/) have outbound gene or variant lookup links. Neither dataset is imported into the snapshot nor used to grade evidence. OncoKB API access requires a token/license; COSMIC downloads require registration and are subject to its reuse terms. No restricted datasets or credentials are shipped.

**Not in this public refresh:** DGIdb, Europe PMC, openFDA, a standalone MONDO/EFO ontology import, and full Reactome/Open Targets/CIViC exports. Some of these have adapters or documentation in the repository, but their presence in the code does not mean their data appear on the public site. AACT and DrugComb/NCI ALMANAC/DREAM/AstraZeneca–Sanger remain scaffolds rather than active refresh inputs.

### Attribution and licensing

The repository does not bundle restricted upstream datasets, private credentials, or copied source text. Source-specific conditions continue to apply:

- **GtoPdb:** database under ODbL; content under CC BY-SA 4.0.
- **Open Targets Platform:** CC0.
- **DrugMechDB:** CC0.
- **ChEMBL:** CC BY-SA 3.0.
- **CIViC:** CC0.
- **Reactome:** CC0 database content; selected NCBI Gene-to-pathway mappings only.
- **TRRUST:** CC BY-SA 4.0.
- **GTEx:** open-access aggregate median-expression summaries only.
- **ClinicalTrials.gov:** trial registry metadata; registration is not evidence of clinical efficacy.

DrugBank is treated as restricted, and CTD reuse remains subject to verification of applicable terms. Consult [docs/SOURCES.md](docs/SOURCES.md) and [docs/MECHANISTIC_SOURCES.md](docs/MECHANISTIC_SOURCES.md) before ingesting or redistributing data.

## Retrieval and benchmarks

OncoGraph exposes provenance-aware graph traversal through `/query/traverse` and related query helpers. [docs/QUERY_API.md](docs/QUERY_API.md) describes the API.

The benchmark reports compare graph retrieval strategies on frozen, real-data snapshots, including an evidence-blind ablation and progressively more selective retrieval methods:

| Report | Focus |
| --- | --- |
| [Benchmark v2](docs/BENCHMARK_RUN_v2.md) | GraphRetriever versus an evidence-blind ablation |
| [Benchmark v3](docs/BENCHMARK_RUN_v3.md) | Combination-treatment queries and a fix motivated by a citation-precision failure mode |
| [Ranked retrieval](docs/BENCHMARK_RUN_v3_ranked.md) | Query-conditioned relation/path ranking, dev-only calibration, and degree-stratified analysis |
| [Hybrid retrieval](docs/BENCHMARK_RUN_v3_hybrid.md) | Local TF-IDF plus structural signals; the full hybrid does **not** outperform the simpler lexical-only approach |

See [benchmark methodology](docs/BENCHMARKING.md) for item schemas and metric definitions. Reported outcomes should be interpreted within the documented snapshots and evaluation protocols.

## Documentation

| Guide | Topic |
| --- | --- |
| [Sources](docs/SOURCES.md) | Source catalog, provenance, and usage policy |
| [Evidence](docs/EVIDENCE.md) | Edge-level evidence fields and adapter contract |
| [Publications](docs/PUBLICATIONS.md) | Publication entities and literature evidence |
| [Biological sources](docs/BIOLOGICAL_SOURCES.md) | Pathway and clinical-evidence source assessment |
| [Mechanistic sources](docs/MECHANISTIC_SOURCES.md) | Drug mechanism and functional-evidence sources |
| [Drug response](docs/DRUG_RESPONSE.md) | Drug-response and experimental-model schemas |
| [Treatment-response context](docs/TREATMENT_RESPONSE_CONTEXT.md) | Context-conditioned response and trial interpretation |
| [Query API](docs/QUERY_API.md) | Evidence-aware traversal and query helpers |
| [MCP](docs/MCP.md) | Agent-facing tools and retrieval strategies |
| [Benchmarking](docs/BENCHMARKING.md) | Evaluation schemas and metrics |
| [Statistics](docs/STATS.md) | Public explorer coverage and path-count definitions |
| [Hosting](docs/HOSTING.md) | Index refresh and GitHub Pages deployment |

Additional design investigations are available in [`docs/`](docs/). Documentation of a source or feature does not imply that it is part of the current public release.

## Repository structure

```text
src/oncograph/      Python package, API, graph and retrieval logic
web/                Public explorer
scripts/            Data preparation and supporting scripts
data/               Repository data assets
docs/               Source policies, interfaces, and evaluations
tests/              Automated tests
.github/workflows/  CI, data refresh, and deployment
```

## Development

```bash
pytest
ruff check .
```

## Roadmap

Ongoing directions include broader source adapters with licensing checks, stable external-ID resolution, conflict tracking, evidence verification, reproducible snapshots, and improvements to graph exploration and retrieval. Items described in the documentation may be exploratory rather than implemented.

## License

OncoGraph code is released under the [MIT License](LICENSE). Individual upstream datasets retain their own licenses and terms; downstream use must preserve required attribution and provenance.
