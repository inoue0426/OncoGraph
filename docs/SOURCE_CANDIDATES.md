# Source candidates

This document is a staging list, not permission to redistribute a dataset. Before an adapter is enabled, record the source's current official terms in the source catalog and run the import checklist.

## Interaction / association layers

- STRING: useful for protein association edges. Current official licensing states that its data and download files are available under CC BY 4.0; preserve attribution and release/version metadata.
- NCI GDC: useful for cancer expression-derived layers. Keep open and controlled access classes separate; only inputs the operator is authorized to use should be processed.

## Coexpression

Coexpression should be computed from an explicitly identified expression snapshot rather than copied as an unexplained edge. Recommended edge metadata: cohort, tissue/disease, method, sample count, threshold/top-k rule, source version, and derivation version.

Potential expression sources should be reviewed individually for current access and redistribution terms before enabling automated acquisition.

## Chemical/drug sources

The source-adapter framework can represent chemical/drug identifiers and provenance, but source-specific acquisition must follow the upstream terms. Restricted datasets should remain external/user-provided and must not be committed to the public repository.
