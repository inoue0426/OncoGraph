# Import readiness checklist

Use this before enabling any upstream dataset.

## Source policy

1. Record the official source URL and exact release/version.
2. Record license/terms URL and redistribution/access classification.
3. Decide whether OncoGraph may redistribute records, derived records only, identifiers/provenance only, or no data.
4. Record required attribution/citation text.
5. Keep credentials, access tokens, controlled data, and restricted source files out of git.

## Identifier policy

1. Prefer stable IDs over names.
2. Normalize namespaces before entity resolution.
3. Never merge solely on a matching display name.
4. Route conflicting stable identifiers to the conflict table.
5. Make repeated imports idempotent.

## Derived-data policy

For correlations, scores, embeddings, or other derived values, persist enough metadata to reproduce the derivation: source snapshot, cohort/context, method, sample count, thresholds/top-k rules, and software version when relevant.

## Scale policy

For large releases, prefer bulk files over per-record HTTP requests. Stage raw/permitted inputs outside git, validate them, transform to normalized records, and bulk-load in transactions. Maintain counts and checksums per import run.
