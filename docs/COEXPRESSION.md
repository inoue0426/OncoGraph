# Coexpression layer

OncoGraph treats coexpression as a **derived, context-specific association**, not a universal biological fact.

## Record contract

Every coexpression edge must retain:

- two stable gene identifiers and their namespaces;
- correlation coefficient and method;
- sample count;
- cohort/dataset;
- tissue and disease context when available;
- upstream source key and version/snapshot;
- access/licensing class for the input dataset.

This lets the graph distinguish, for example, a pan-cancer correlation from a disease-specific or tissue-specific correlation.

## Local/permitted matrix importer

`oncograph.sources.coexpression` accepts a gene-by-sample TSV supplied by the user or obtained under appropriate access terms. The repository does not bundle human participant-level expression matrices.

Expected format:

```text
gene_id\tsample_1\tsample_2\tsample_3
GENE_A\t1.0\t2.0\t3.0
GENE_B\t2.0\t3.0\t5.0
```

The included implementation is intentionally a small reference implementation. Large matrices should use blocked/vectorized correlation and stream only retained edges into persistent storage.

## Recommended production representation

Do not store a dense all-by-all matrix in the primary graph database. Persist sparse associations after a declared threshold/top-k policy, with the derivation parameters attached to the snapshot. Keep raw matrices outside the graph and reference their source/snapshot.

## Human genomic data

Access class is part of provenance. Open and controlled datasets must remain distinguishable. Controlled data should never be committed to this public repository or a public OncoGraph snapshot.
