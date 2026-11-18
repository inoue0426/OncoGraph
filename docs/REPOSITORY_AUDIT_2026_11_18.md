# Repository inspection, 2026-11-18

Baseline: `origin/main` at `0d70baf`. Inspection and fixes are on
`audit/repository-health`, in the separate `oncograph-lewis-followup` worktree.
This report distinguishes completed checks from remaining implementation work.

## Findings requiring follow-up

1. **The public data refresh is not healthy.** The three most recent scheduled
   refreshes failed. The latest inspected failure,
   [run 43824450599](https://github.com/inoue0426/OncoGraph/actions/runs/43824450599),
   stopped on `Cannot return null for non-nullable field EvidenceItem.variantHgvs`.
   This was reproduced against the live API. Omitting that optional field allows
   the query to return, but does not by itself restore a complete refresh.
2. **CIViC pagination was silently incomplete.** A live `pageInfo` query showed
   more variant pages for BRAF, EGFR, ERBB2, PIK3CA, and TP53, plus another evidence
   page for molecular profile 12. The first-page fetch returned 1,094 rows
   representing 985 distinct evidence IDs across nine requested genes. Those
   rows are diagnostic output only, not a replacement public snapshot. Full
   cursor traversal at every connection, and complete profile membership beyond
   the selected gene set, need implementation before publication is resumed.
3. **Imports are not atomic.** Entity and edge import functions commit separately.
   Existing CLI regression tests confirm that accepted Lewis rows remain after
   an incomplete import returns status 1. This is documented behavior, not fixed
   by this inspection. An opt-in transaction mode remains useful future work.
4. **The normal working directory is stale and dirty.** It is still on
   `feat/lewis-ci-xlsx-coverage` at `64193be`, with uncommitted Lewis changes.
   Other worktrees also contain independent uncommitted Sigma and web changes.
   None were overwritten, reset, merged, or deleted. A binary diff backup of the
   original working directory was saved outside the repository. Bringing it up
   to date requires deliberate reconciliation; blindly replaying its older
   provenance labels would undo later corrections.
5. **Biological mapping and redistribution remain incomplete.** Current Lewis
   profiles still skip unresolved/unsupported rows, and Jin and Zhao remain
   quarantined. Source-specific mapping review and reuse clearance are not
   established by passing software tests.

## Corrections made during inspection

- Reject duplicate identifier-map headers, extra/missing delimited fields, and
  malformed CSV quoting instead of dropping data or changing an endpoint
  silently. Explicit empty optional cells and UTF-8 BOM maps remain supported.
  Identifier audit reports now handle CSV parser failures.
- Retry the full CIViC query without `variantHgvs` only for the exact observed
  HGVS-null failure. Other GraphQL errors still fail. If a complete result can
  be fetched, omitted fields and their reason are recorded in its manifest.
- Check pagination metadata on every returned CIViC connection and refuse to
  overwrite a snapshot when any page is incomplete or unverified. The current
  live response is therefore still blocked, explicitly, pending cursor support.
- Require a unique exact preferred-name match for ChEMBL molecules. Previously
  an unmatched name could inherit the first fuzzy search result's mechanisms.
- Skip ChEMBL targets with multiple components rather than presenting their
  first component as the entire target. Complex target modeling remains future
  work; this change intentionally reduces eligible coverage.

## Completed software and deployment checks

- Python suite: **422 passed** after fixes, including API, identifier resolution,
  source imports, CLI, and new malformed-input/refresh regression cases.
- JavaScript suite: **20 passed** on the baseline; no JavaScript was modified.
- Ruff passes; `uv pip check` found no dependency conflicts. This is a dependency
  compatibility check, not a vulnerability advisory scan.
- Wheel and source distribution build successfully; CLI help loads.
- Remote [CI 44380438716](https://github.com/inoue0426/OncoGraph/actions/runs/44380438716)
  and [Pages 44380439752](https://github.com/inoue0426/OncoGraph/actions/runs/44380439752)
  succeeded for the baseline. These do not cover the unmerged inspection fixes.
- The last successful refresh listed by GitHub was
  [38171664886](https://github.com/inoue0426/OncoGraph/actions/runs/38171664886),
  on October 11. Pages success should not be interpreted as data freshness.

## Existing database and published snapshot

Both discovered `oncograph.db` files were opened read-only. SQLite quick-check
reported `ok`, foreign-key checks were empty, and graph tables contained zero
records. Thus no historical imported Lewis database was available to inspect
for old unversioned evidence IDs, missing citations, or migration effects.

The deployed JSON snapshot was downloaded to a temporary directory without
changing repository data or deploying anything:

| Check | Result |
| --- | ---: |
| Entities | 113,630 |
| Relations | 130,900 |
| Evidence records | 133,962 |
| Duplicate entity IDs | 0 |
| Duplicate relation endpoint/predicate tuples | 0 |
| Duplicate source/source-ID evidence keys within relations | 0 |
| Relations with missing endpoints | 0 |
| Relations without evidence | 0 |
| Lewis evidence records | 0 |

Published counts agree with `stats.json`. Its `generated_at` is
`2026-10-11T21:44:41Z`; the graph version is `2026-10-11T21:26:47Z`.
These structural checks do not establish biological correctness of all records.

## Real-source Lewis diagnostics

Inputs were the existing local compendium at
`c0ce8167c20c2f5d1a3d309e04514da9a178c41c` and the HGNC snapshot already documented
in [the parser policy](LEWIS_LR_PARSERS.md). No source datasets were added to Git.

- Inventory: 32 files, 40 tables, no inventory errors.
- All 14 registered profiles were inspected: 12 produced partial validation
  reports; Jin and Zhao rejected their quarantined inputs. Strict field-count
  checks did not change accepted coverage for these actual inputs.
- The 12 reports total 33,108 candidate interactions, 1,248 skipped rows, and
  1,156 unresolved identifier occurrences. These are not unique interaction or
  molecule counts. All source reports remain invalid for complete ingestion.
- Unresolved review counts: 635 occurrences with one HGNC candidate, 54 with
  multiple candidates, 27 with no name match, and 440 HMDB-shaped identifiers
  requiring metabolite mapping. No review candidate was automatically accepted.
- A disposable in-memory SQLite graph imported the 11 sources with resolved
  gene candidates, including Kirouac. It contained **2,562 entities, 16,415
  relations, and 35,672 evidence records** with zero ingestion errors for the
  accepted subset. Reimport added zero entities, relations, or evidence.
- A fresh graph imported the same sources in reverse order. Canonical entity
  identity/type tuples, relation endpoint/predicate tuples, and evidence tuples
  including serialized context and evidence type matched exactly. Display
  labels and timestamps were excluded from the comparison. No database was
  persisted and no partial source was reclassified as fully valid.
- The separate BaderLab diagnostic remains review-only; see its recorded
  taxonomy and interaction-type counts in the parser policy.

Full refresh execution, PostgreSQL behavior, destructive migration, source
permission approval, and expert biological review were not performed. The next
highest-priority engineering task is complete CIViC pagination, followed by a
staged refresh and review of its source/coverage differences before publication.
