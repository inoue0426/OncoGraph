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

`GtoPdbAdapter` (`oncograph.sources.gtopdb`) is implemented and uses only the official
"approved drugs with primary targets" interaction file and the official target-to-HGNC mapping
file, both open (ODbL / CC BY-SA 4.0). It imports approved drugs as `Drug` entities and resolves
each drug's primary target to an existing `Gene` entity strictly by HGNC ID; targets absent from
the official mapping are skipped rather than matched by name. It does not fetch the full
ligand/interaction dump or the Postgres export.
