# Multi-scale cancer response graph

OncoGraph is designed around the question: **what happens when X is perturbed in cancer context Y?**

## Layers

1. Molecular knowledge: gene, protein, GO term, pathway, disease.
2. Molecular interactions: regulation, protein interactions, coexpression.
3. Drug mechanism: drug-target relationships with evidence and assay context.
4. Perturbations: intervention + dose + time + biological context.
5. Cell state: cell type/state and treatment-associated state changes.
6. Cell-cell communication: sender cell -> ligand -> receptor -> receiver cell.
7. Model systems: cell line, organoid, PDX and cohorts.
8. Phenotype and response: viability, growth, molecular phenotype and response observations.
9. Resistance: observed or proposed resistance mechanisms with provenance.
10. Clinical evidence: trials and literature connected through the same canonical entities.

## Design rule

Do not collapse observations into context-free binary facts. An observation should retain the dataset/source, biological context, model system, cohort, assay, treatment condition, method, sample size and relevant quantitative score whenever those fields are available.

## Core paths

- Drug -> targets -> Gene/Protein -> participates_in -> Pathway
- Gene -> annotated_to -> GO term
- Gene -> coexpressed_with -> Gene
- Cell type -> expresses -> Ligand
- Ligand -> binds -> Receptor
- Receptor -> expressed_by -> Cell type
- Perturbation -> changes -> Cell state
- Perturbation -> produces -> Phenotype/Response
- Drug -> associated_with -> Resistance mechanism
- Trial/Paper -> supports -> relation (through Evidence)

## Cell-cell communication

Represent communication using explicit ligand/receptor entities rather than a single opaque cell-cell edge. Context should include tissue/disease, dataset, treatment, sender/receiver labels, inference method and score when available.

## Drug response

Response must remain contextual. Preserve model system, disease, dose, time, assay, endpoint and quantitative values when available. Avoid treating a response measured in a cell line as a universal drug-disease fact.

## Perturbations

Perturbation is a first-class entity. It identifies an intervention under a specific experimental condition. This permits treatment-conditioned expression, pathway, cell-state, communication and phenotype observations to share one graph representation.

## Research direction

A long-term query target is a provenance-bearing evidence chain such as:

Drug -> Target -> Pathway -> Perturbation -> Cell-state change -> Cell-cell communication change -> Response -> Clinical evidence

This should support both human exploration and machine/agent queries while exposing conflicting, missing and context-dependent evidence rather than hiding it.
