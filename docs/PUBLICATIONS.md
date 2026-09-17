# Publications & literature evidence

Publications are first-class graph entities (`Entity.type == "paper"`), so a relation's
evidence can point at the paper that supports it, just like it points at a database record or
a clinical trial.

## Identity

A Publication's canonical ID is the first available of, in order: PMID, DOI, PMCID (see
`oncograph.sources.europe_pmc._primary_identifier`). Re-importing the same PMID/DOI never
creates a duplicate entity. DOIs are lowercased and PMCIDs uppercased during normalization
(`oncograph.normalization`) so casing differences don't create false duplicates either.

Only bibliographic metadata is stored on a Publication entity (in `Entity.entity_metadata`):
journal, year, authors, publication type(s), DOI, PMCID. **No abstract or full text is ever
fetched or stored** -- see `docs/SOURCES.md` for why (Europe PMC's redistribution terms vary
per article; only the bibliographic record itself is uniformly reusable).

## Linking a publication to a relation

There is no separate "relation cites publication" table. Instead, `Evidence.publication_id`
(added in Phase 2) points at the Publication entity, alongside the normal `source`/`source_id`
provenance fields. Since a `Relation` can already carry many `Evidence` rows, this is also how
"multiple publications support one relation" works: one `Evidence` row per citing publication,
each with a different `publication_id`. No junction table or graph reification needed. See
`docs/EVIDENCE.md` for the full field contract.

## The curated citations file

**OncoGraph does not do literature mining.** Nothing here decides, from a paper's text or
metadata, which relation it supports -- that judgment call is external and, for now,
human-curated. `data/curated/publication_citations.json` is that curation: a small, committed
JSON list of

```json
{
  "pmid": "42691523",
  "subject_namespace": "gtopdb",
  "subject_id": "4941",
  "predicate": "targets",
  "object_namespace": "hgnc",
  "object_id": "HGNC:3236",
  "evidence_type": "target_interaction",
  "extraction_method": "curated"
}
```

rows, each saying "this PMID supports this (subject, predicate, object) triple". It's original
curation, not copied upstream content, so it's committed to the repository like a fixture --
unlike everything under `data/raw/`.

`evidence_type` and `extraction_method` are per-row so a future, non-curated source of
citations (a rule-based matcher, or eventually an LLM-assisted one -- neither exists yet) can
set `extraction_method` to something other than `"curated"` (e.g. `"rule_derived"`,
`"llm_extracted"`) without a schema change, and so curated evidence stays distinguishable from
database-derived, computed, and (later) rule-/LLM-derived evidence via that one field.

## Fetching publication metadata

`scripts/fetch_publications.py` reads the curated citations file, collects the unique PMIDs it
references, and fetches each one's bibliographic metadata from the
[Europe PMC REST API](https://europepmc.org/) into `data/raw/publications.json` (gitignored,
like other fetched data). `oncograph.sources.europe_pmc.EuropePmcAdapter` then takes both files
and emits Publication entities plus literature-evidence edges.

```bash
python scripts/fetch_publications.py
oncograph import-source europe_pmc data/curated/publication_citations.json \
  --publication-metadata data/raw/publications.json --release "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

A citation whose subject/object entities aren't already imported is skipped (not guessed at),
same as every other adapter; a citation whose PMID has no fetched metadata is skipped too.

This adapter is not currently wired into `refresh-data.yml` -- it's independent, low-volume
(scales with the curated file, not with bulk upstream data), and adding it to the scheduled
pipeline is a deliberate follow-up decision, not an automatic consequence of it existing.
