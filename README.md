# OncoGraph

**An evidence-first, provenance-aware knowledge graph for oncology research**

[**Explore OncoGraph**](https://inoue0426.github.io/OncoGraph/) · [**Quick start**](#quick-start) · [**Documentation**](#documentation) · [**Benchmarks**](#retrieval-and-benchmarks)

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

The public index is built from open or otherwise permitted data, including:

| Source | Information used in the public refresh |
| --- | --- |
| HGNC | Gene identifiers and nomenclature |
| Gene Ontology | Functional ontology information |
| IUPHAR/BPS Guide to PHARMACOLOGY (GtoPdb) | Approved drugs and primary targets |
| ClinicalTrials.gov | Trial registry metadata, including combination treatments and termination-reason processing |
| Open Targets Platform | Target–disease associations |
| DrugMechDB | Curated drug-mechanism paths |
| ChEMBL | Mechanisms of action |
| TRRUST | Transcription-factor–target regulation |
| GTEx | Open-access aggregate tissue-expression summaries |

The scheduled/manual [`refresh-data.yml`](.github/workflows/refresh-data.yml) workflow imports these sources into a temporary SQLite database and publishes a generated index as a build artifact. Raw upstream downloads and the database are not committed to Git. [`pages.yml`](.github/workflows/pages.yml) deploys the latest artifact with the explorer on pushes to `main`, without fetching upstream data again. See [hosting documentation](docs/HOSTING.md).

**Scope matters:** integration ideas documented elsewhere are not necessarily enabled in the published refresh. In particular, standalone MONDO/EFO ontology ingestion, CIViC, openFDA, and the full scope of Open Targets are not included in the current public refresh. AACT and DrugComb/NCI ALMANAC/DREAM/AstraZeneca–Sanger integrations remain scaffolds rather than active refresh inputs.

### Attribution and licensing

The repository does not bundle restricted upstream datasets, private credentials, or copied source text. Source-specific conditions continue to apply:

- **GtoPdb:** database under ODbL; content under CC BY-SA 4.0.
- **Open Targets Platform:** CC0.
- **DrugMechDB:** CC0.
- **ChEMBL:** CC BY-SA 3.0.
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
