# Follow-up to the repository audit

This records the implementation follow-up to
[the November 18 audit](REPOSITORY_AUDIT_2026_11_18.md). The original report is a
historical baseline, not the current completion status.

## Completed engineering work

- CIViC now follows all gene, variant, molecular-profile, and evidence cursors.
  Missing pagination metadata, repeated cursors, overlapping page identities,
  missing requested genes, and GraphQL errors fail before writing output.
- Full molecular-profile membership comes from CIViC's `variants` field rather
  than the subset of variants encountered under the nine requested genes.
  Features outside that set remain in the evidence context, so a compound
  profile is not misrepresented as a single-variant claim.
- The live fetch returned 1,576 source rows, 1,409 distinct accepted evidence
  IDs, 490 selected variants, and 477 molecular profiles. All occurrences of
  each profile agreed on full membership. Ninety-six rows include a member
  outside the requested gene set. Counts are snapshot-specific.
- The upstream `EvidenceItem.variantHgvs` null error still occurs. The narrow
  optional-field retry is retained; HGVS is unset and the manifest records
  the omission. No variant notation is invented from a name.
- `oncograph import-source ... --atomic` validates complete Lewis inputs before
  writing and uses a single transaction for entity and edge ingestion. Reported
  conflicts or unresolved edges roll back source writes, including updates to
  existing entities, new identifiers, evidence, and resolution-issue rows.
  Exceptions also roll back. Regression tests reopen a file-backed SQLite
  database to verify persistence, rollback, and successful rerun idempotency.
- Default imports keep their documented partial-persistence behavior for
  compatibility. PostgreSQL execution was not tested: no local PostgreSQL server
  or running Docker daemon was available. Production database migration was not
  needed or performed.
- The regular working directory is on current `main`. Earlier uncommitted
  Lewis changes and its untracked lockfile were preserved in a named Git stash:
  `Preserve pre-main Lewis work before audit follow-up synchronization`.
  Other active worktrees were left untouched.
- Identifier lookups now have a nonunique `(namespace, value)` index, also
  added idempotently to existing databases. SQLite previously selected the
  namespace-only index and scanned many unrelated identifiers on each lookup.
  The regression test verifies the query plan, an existing-database upgrade,
  repeated initialization, and preservation of ambiguous claims. A local
  45,000-row/400-lookup diagnostic took 0.859 seconds before and 0.000606 seconds
  after the index; this is a synthetic lookup measurement, not a full refresh
  timing claim. This additive fix is in `637c4fd`; the already-running refresh
  at `2698415` does not benefit from it.
- ChEMBL now flushes progress every 25 processed names, including skipped names,
  rather than buffering output until exit or skipping progress on no-match rows.
- The concurrently merged SIGMA, LINCS, and Pages changes were integrated before validation.
  The complete Python suite, with `dev`, `lewis`, and `signed` extras, passed
  **477 tests**. JavaScript passed **20 tests**. Ruff and whitespace checks pass.

## Public refresh verification

The refresh triggered for commit `2698415` is
[run 44384958293](https://github.com/inoue0426/OncoGraph/actions/runs/44384958293).
At the user's request, monitoring stopped at 2026-11-18T21:44:52Z. The run
remained in progress and was not cancelled or restarted. The local background
`gh run watch` process was stopped. Publication verification is **pending**, not
successful or failed; no new snapshot has been verified by this investigation.

The one-time inspection recorded 32.02 minutes for the drug-association fetch,
60.22 minutes for ChEMBL, and 18.92 minutes elapsed in HGNC ingestion. Download
steps were complete; later imports and artifact generation had not started.
`gh run view --log` refused access while the run was in progress. Step metadata
proves advancement into HGNC but does not prove ongoing row-level progress.
There is insufficient evidence to classify the current importer as either
healthy or stalled.

The HGNC adapter reads a local TSV without network calls. A local 45,395-row
snapshot parsed in 0.269 seconds; this is not a measurement on the runner.
The importer performs repeated SQL lookups and per-record flushes, committing
at the end of the entity phase. The reproduced namespace-only query plan makes
DB lookup/write work the leading bottleneck, rather than downloading, TSV
parsing, index construction, or artifact generation. The composite-index fix
above removes the demonstrated scan, but has not been timed in a full hosted
refresh. Row-level importer progress reporting is still absent.

## Recommended resumable refresh design (not yet implemented)

- Separate downloading from ingestion. Persist permitted raw inputs and manifests
  as immutable artifacts after each source fetch, before any database import.
  A retry should accept a verified download-artifact run ID instead of repeating
  the external requests. The present job uploads only final JSON/manifests at
  the end; it does not preserve raw inputs or the SQLite database externally.
- Cache successful API responses with DiskCache, keyed by endpoint, parameters,
  and source version/freshness policy. Persist the cache between runners; do not
  cache transient failures as valid empty results. The current ChEMBL target
  cache exists only in process memory.
- Add a source-completion ledger keyed by raw-input hashes, adapter/schema
  versions, and mapping-dependency hashes. Save a consistent SQLite backup after
  a successfully committed source. Resume from that backup, replaying an
  interrupted source; update the ledger in the same transaction as source data.
  Record processed rows and elapsed time periodically with flushed output.
- For unchanged inputs and dependencies, skip completed sources. Changed-source
  updates need reconciliation: current imports are duplicate-resistant but still
  scan every input; existing evidence is returned unchanged and removed upstream
  records are not deleted. Merely reusing the old DB would retain stale evidence.
  Source-owned evidence replacement and orphan cleanup need explicit tests before
  true incremental publication is enabled.
- Keep the running job intact. If it fails, the current workflow has no durable
  raw-data/DB checkpoint to guarantee recovery. Do not claim that a restart will
  reuse this run's downloaded files. No cancellation or restart is authorized
  by this investigation; resumability should be implemented for future runs.

## Source-review boundaries

No reviewed input authorizes public redistribution of the Lewis compendium.
Its local-only status is unchanged. No unknown-license source was added to the
public refresh, and no name-match suggestion was promoted to a canonical
mapping automatically.

Review diagnostics are available for all 14 registered Lewis profiles. They
retain source/HGNC hashes, skipped rows, candidate counts, and ambiguity status.
Among the 1,156 unresolved occurrences, 635 have one HGNC name candidate, 54
have multiple candidates, 27 have no HGNC match, and 440 have HMDB-shaped
identifiers requiring metabolite mapping. These are review leads, not approved
identities. Jin and Zhao remain quarantined. The other unsupported source
formats and complex labels retain their documented exclusions.

Closing those exclusions requires source-specific biological verification and
reuse evidence, not a software change or the user granting access to this
repository. The available local graph databases contain no historical imported
records, so no legacy evidence migration or deletion was justified.
