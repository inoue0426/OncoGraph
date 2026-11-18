# Signed molecular observations from SIGMA-KG source datasets

## Status and scope

This integration imports available **original-source exports used by SIGMA-KG**.
The typed contract is documented separately in [SIGNED_MOLECULAR.md](SIGNED_MOLECULAR.md).
It does **not** import the complete, harmonized or structurally pruned SIGMA-KG,
reconstruct its missing edges, implement FLASH, or publish a new Pages snapshot.
All three source adapters write to an explicit local SQLite database through the
existing Entity, EntityIdentifier, Relation and Evidence tables. No migration is
needed. The local command is intentionally separate from the source registry and
public refresh.

The reference is Mottaqi et al., *A Scalable Sign-Aware Multi-Omics Knowledge Graph
Foundation Model for Mechanistic Drug Action and Clinical Response Predictions*,
[doi:10.64898/2026.04.29.721775](https://doi.org/10.64898/2026.04.29.721775),
provided May 11, 2026 v2 PDF including supplementary methods/tables.

## Availability investigation (2026-11-18)

The [official author repository](https://github.com/mmottaqii/FLASH-foundation-model)
was inspected at commit `a426e056312b5f71e5298e26d95b1ff3b35e8faa`.
Its README explicitly excludes the KG, node mapping, chemical-protein and
chemical-disease tables and describes a future CodeOcean capsule. It supplies no
capsule DOI/link at that commit. The two included DDI label files are unrelated
to the requested molecular layers; they were not ingested. The repository MIT
license covers code, not blanket rights to underlying biomedical datasets.
The paper's CC BY-NC license likewise does not establish a license for its KG.

| Paper layer / reported edges | Available input investigated | Implementation and redistribution status |
| --- | --- | --- |
| Compound-Gene / 1,322,830 | [Harmonizome LINCS consensus](https://maayanlab.cloud/Harmonizome/dataset/LINCS+L1000+CMAP+Chemical+Perturbation+Consensus+Signatures), edge export and processing notebook | Local importer implemented; downloaded export contains 5,086,167 rows, not the paper's postprocessing count. [Terms](https://maayanlab.cloud/Harmonizome/terms) link to CC BY-NC-SA 4.0; academic non-profit use, attribution and share-alike conditions apply. Not enabled for public redistribution. |
| Gene-Disease / 1,489,308 | [Hetionet v1.0 JSON](https://github.com/hetio/hetionet/tree/main/hetnet/json), STARGEO expression subset | Implemented; all 15,354 selected edges explicitly carry CC0 1.0. Disease node names carry CC BY 3.0. Original per-edge and per-node licensing is retained. |
| Gene-Disease, other inputs | AMP-AD [syn21241740](https://www.synapse.org/Synapse:syn21241740), [DiSignAtlas](http://www.inbirg.com/disignatlas/), GEO signatures | No import. AMP-AD needs dataset-specific access/terms review; DiSignAtlas access failed during investigation; exact SIGMA gene-disease harmonization, contrasts and pruning inputs are not released in the inspected repo. No unlicensed or patient-level download attempted. |
| Compound-Protein / 13,711 | [GtoPdb interaction and ligand crosswalk exports](https://www.guidetopharmacology.org/download.jsp) | Implemented from source release 2026.3.1, published 2026-10-12; differs from the paper's 2025.3. [License](https://www.guidetopharmacology.org/about.jsp#license): ODbL database, CC BY-SA 4.0 content. Attribution/share-alike required. Kept local in this change. |
| Compound-Protein, other input | [STITCH](http://stitch.embl.de/) | Not imported. Access/terms and action-level evidence not verified during this investigation; a combined association score cannot establish activation/inhibition. |
| Gene-Protein / 19,337 | HGNC cross-references / UniProt | HGNC mapping reused; UniProt products are kept separate from gene identity. Product cross-references are retained as metadata, not imported as an `encodes` evidence layer. |
| Protein-Protein / 251,762 | STRING | Not imported; generic interaction is not positive regulation. |

The LINCS dataset page and bundled processing notebook both give a last-updated
date of 2023-10-27; the edge download itself has no export-specific version.
Checksums and the downloaded snapshot label identify the actual imported bytes.

Source counts are not expected to reproduce SIGMA-KG's summary counts. In
particular, the paper harmonizes identifiers, thresholds scores, removes
conflicting edges, and prunes unbalanced cycles. None of that pruning is applied
here. Opposite directions remain visible.

## Biological contract

| Predicate | Required direction/types | Effect sign | Evidence family |
| --- | --- | --- | --- |
| `upregulates` / `downregulates` | Drug -> Gene | +1 / -1 | `drug_induced_transcription` |
| `activates` / `inhibits` | Drug -> Protein | +1 / -1 | `protein_functional_modulation` |
| `upregulated_in` / `downregulated_in` | Gene -> Disease | +1 / -1 | `disease_expression_association` |

These constraints apply to this importer, without changing unrelated existing
uses of predicates elsewhere in OncoGraph. A sign is not therapeutic benefit,
causal certainty, binding affinity or generic association strength.

* **LINCS:** upstream processing performs gene-wise standardization of consensus
  coefficients and selects absolute z-scores >=3. The importer preserves the
  published threshold sign and score, not a newly computed fold change. A positive
  standardized score must not be interpreted as an unstandardized treatment vs
  control log-fold change. The source serialization describes Gene as regulated
  by Chemical; we normalize to Chemical -> Gene and retain the original wording
  and orientation. Consensus aggregation, L1000 measured/inferred gene status,
  dose, cell line and time are not resolved by this export. No such details are
  invented. Evidence is `transformed`, never direct binding or a model prediction.
* **GtoPdb:** retain explicit Activation, Agonist, Full agonist, Inhibition,
  Antagonist, Inverse agonist and Irreversible inhibition annotations on human,
  single-UniProt targets of small molecules. Binding-only, partial/biased/mixed,
  allosteric, complex-target and unspecified/non-human records are excluded.
  Antagonism is retained as source functional inhibition, not necessarily reduced
  basal activity. All original action, assay, affinity units/values and reference
  fields remain in `original_row`; an affinity is not repurposed as confidence.
* **Hetionet/STARGEO:** select only Disease-upregulates/downregulates-Gene edges
  whose source and per-edge license match the reviewed subset. Normalize to
  Gene-upregulated_in/downregulated_in-Disease. Preserve the original undirected
  graph encoding, source direction, log2 fold change and attributes. These are
  meta-analysis expression associations, not causal gene-disease mechanisms.

## Identity and provenance

The strict resolver indexes the existing canonical IDs **and** EntityIdentifier
claims. It rejects multiple owners, conflicting types and unknown/conflicting
species for genes and proteins, including legacy UniProt aliases attached to genes.
Canonical matches do not override disputed aliases. Names are never compared
against OncoGraph display names. Existing entities are not overwritten or merged.

* Human genes use the existing HGNC adapter with approved records only; HGNC,
  NCBI Gene and Ensembl remain gene IDs. UniProt references are retained under
  `protein_products` metadata, never registered as gene aliases by this command.
* LINCS chemical keys are resolved by **exact source-local** `pert_id` or
  `pert_iname` against official GSE92742 `trt_cp` perturbagen metadata. This is a
  documented source metadata join, not global name matching. A token mapping to
  several PubChem CIDs is rejected. Missing `-666` CIDs are not identifiers.
  Case folding, synonym guessing, fuzzy matching and parent/salt merging are not
  performed. GSE92742 is older than the consensus export, limiting coverage.
* GtoPdb's official ligand crosswalk supplies PubChem, ChEMBL and DrugBank IDs.
  Competing identity claims and multi-valued chemical IDs are reported, not
  arbitrarily resolved. Proteins use explicit human UniProt accessions; their
  encoding Ensembl genes are metadata and remain separate nodes.
* Hetionet disease nodes retain exact DOID identifiers. No HPO/similarity-based
  merging or inferred ontology equivalence is performed.

Every evidence row retains source dataset, predicate, sign, biological family,
release/snapshot, input SHA-256, observation status, original score/context where
supplied, license and source URL. LINCS keeps its original row index together
with the source file fingerprint. GtoPdb/Hetionet do not ship native edge record
IDs in these exports: a clearly labeled SHA-256 content surrogate is used and the
entire original row is retained. No native ID is fabricated.

Deduplication keys include relation, source, original record key and the complete
provenance/context fingerprint. Different contexts/releases coexist even with a
shared upstream record ID. Opposite signs are different relations. Identical
source records do not inflate evidence counts. Two databases sharing underlying
experiments are not automatically independent experimental replications.

## Reproduce locally

Install the optional streaming JSON parser and test dependencies:

```bash
uv sync --extra dev --extra lewis --extra signed
uv run python scripts/import_sigma_sources.py \
  --download \
  --raw-dir /absolute/path/outside/repo/sigma-inputs \
  --database /absolute/path/outside/repo/signed.sqlite \
  --report /absolute/path/outside/repo/import-report.json \
  --snapshot 'downloaded YYYY-MM-DD; LINCS upstream export version not supplied' \
  --gene-ids 1956,673,3845,4893,7157,5290,207,238,2064
```

The validation scope is EGFR, BRAF, KRAS, NRAS, TP53, PIK3CA, AKT1, ALK and
ERBB2. The filter applies to LINCS only. All input rows are still parsed/counted;
out-of-scope rows are explicitly reported. Omit `--gene-ids` to attempt all LINCS
genes. `--sources lincs`, `--sources gtopdb`, or `--sources hetionet` selects an
adapter. Each import requires the HGNC mapping; download currently fetches all
reviewed inputs. Preserve the original downloads and manifest: URLs can change.

Repeat the command without `--download`, using the same database, input files,
snapshot label and scope, and a new report path to verify idempotency. The report
contains per-source input/parsed/scoped/mapped counts, created relations/evidence,
duplicates, exact skip reasons, unique identifier statuses and source-local
chemical mapping candidates. `mapped_records` counts observations with both
endpoints resolved, including duplicates; it is not unique entity coverage.
`identifier_coverage` counts unique endpoint/type/taxon lookup keys. Registration
conflicts and source-token mapping failures are reported separately.

Raw files, databases and detailed reports must be outside the checkout. The
public Pages refresh is unchanged. Do not feed this mixed-license local database
into a public export without a separate source/license review. The script has no
publication or remote deployment command.

## Query observations

```python
from sqlmodel import Session, create_engine
from oncograph.sources.base import ExternalIdentifier
from oncograph.signed_molecular import TypedCrosswalk, signed_effects

with Session(create_engine('sqlite:////absolute/path/signed.sqlite')) as session:
    drug_id, status = TypedCrosswalk(session).resolve(
        ExternalIdentifier('pubchem', 'YOUR_CID'), 'drug', None
    )
    if status == 'matched':
        observations = signed_effects(session, drug_id)
```

Each result includes the direction, gene UUID, source, original context, URL and
license. `opposite_direction_observed` flags the presence of both directions for
a drug-gene pair, across all included sources/contexts. It is not a declaration
of contradictory experiments: conditions and underlying studies need inspection.
Only explicitly source-backed transcriptional evidence is returned; model
predictions and protein functional modulation are excluded.

Existing OncoGraph queries can inspect these relations/evidence directly. No new
path-composition rule, downstream causality, pathway enrichment, API endpoint or
browser UI is added. Protein-to-gene context is metadata, not a fabricated causal
edge.

## Validation

See `SIGMA_KG_VALIDATION.json` for committed aggregate counts, input checksums,
source versions and exact command scope from the local validation run. Detailed
identifier diagnostics and data remain local. The run is an integration check,
not a benchmark of biological truth or complete SIGMA-KG coverage.

Tests cover all six relation contracts, direction and polarity, exact identifier
resolution, ambiguous/canonical collisions, unknown/wrong species, gene/protein
separation, source-specific parsing, context-specific and opposing observations,
licenses, source scores, surrogate IDs, duplicates, JSON audit reports and
idempotent CLI imports. Run Python, JavaScript and lint checks with:

```bash
uv run pytest -q
uv run ruff check .
for test_file in tests/*.cjs; do node "$test_file" || exit 1; done
```

## Attribution

* Mottaqi et al. (2026), SIGMA-KG/FLASH, DOI above.
* Diamant et al., Harmonizome 3.0, Nucleic Acids Research 2025;
  Rouillard et al., Harmonizome, Database 2016; Evangelista et al., SigCom LINCS,
  Nucleic Acids Research 2022, doi:10.1093/nar/gkac328; Broad LINCS GSE92742.
* IUPHAR/BPS Guide to PHARMACOLOGY; original publications are retained in the
  interaction export's PubMed/reference fields.
* Himmelstein et al., Hetionet / Project Rephetio, eLife 2017,
  doi:10.7554/eLife.26726; STARGEO differential-expression meta-analysis;
  Disease Ontology; HGNC (CC0).
