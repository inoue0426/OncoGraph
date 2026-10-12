# Variant claim check (research use)

This deterministic rule set classifies **existing CIViC Evidence Items** from
the same bounded Evidence Tree. It does not infer clinical efficacy, approval,
or patient suitability. It does not yet verify free-text LLM answers.

## Example

Open **More tools → Review variant evidence → Check a variant claim** and enter
an exact gene, variant, disease, therapy, and whether to check a report of
`sensitivity` or `resistance`. Download the structured JSON and follow the
CIViC source URLs to verify the records. Therapy may be an exact name or NCIt
ID **as stored in this snapshot**. No cross-source alias mapping is performed.

Against a locally imported database, the same algorithm is exposed through:

```text
GET /claim-evidence?gene=EGFR&variant=T790M&disease=<exact name or DOID>&therapy=<exact name or NCIt ID>&effect=resistance
MCP check_variant_claim(gene, variant, disease, therapy, effect, limit=20)
```

The browser reads GitHub Pages JSON. The Python API and local MCP read their
own SQLite database: their data and refresh dates can differ from Pages.

## Eligibility and classification

First use `buildEvidenceTree` / `get_evidence_tree` with a 200-Evidence-Item
cap. This already requires the exact gene and disease, a matching variant
member (or flagged legacy profile-name match), accepted CIViC status, and
preserves the original evidence ID and claim direction. Then require a therapy
matched by exact stored name or ID and `PREDICTIVE` evidence. Other relation
types, including drug `targets` gene, trial registrations, pathway membership,
and target–disease associations, **cannot** support a variant–therapy effect.

| Bucket | Rule | Interpretation |
| --- | --- | --- |
| `supporting` | Single-member variant profile; `SUPPORTS` reported significance matching the requested effect | A matching curated report, not proof of efficacy |
| `opposing` | Same conditions, `SUPPORTS` the other effect | A differently directed report; its study context may differ |
| `disputed` | Same conditions, `DOES_NOT_SUPPORT` the requested significance | Curated record disputes that significance |
| `context_only` | Complex profile, profile-name-only match, or uncertain/opposite evidence direction | Cannot assign a conclusion to the single variant |

Non-predictive records and other therapies are counted separately rather than
upgraded into therapeutic claims. Results preserve Evidence IDs and source
links. Buckets are presented separately; no numerical combination of CIViC
levels or ratings is interpreted as clinical confidence. Supporting and
opposing records together produce `mixed_records`, not a winner. The display
preserves at least one item from each populated bucket when its limit allows.
If the 200-item source cap or display cap omits any candidate, status becomes
`incomplete_review`; absence of a displayed counterexample then means nothing.
`not_found_in_snapshot` means no eligible record here, **not** absence from
the upstream literature. Legacy snapshots without exported variant members
produce `context_only` for profile-name matches.

## Evaluation before publication claims

This is a **rule-based baseline**, not a demonstrated improvement or a
validated algorithm. The current [variant retrieval experiment](VARIANT_RETRIEVAL_EXPERIMENT.md)
evaluates Evidence Item retrieval, not this claim classifier or LLM responses.
To test the proposal, freeze the same snapshot and independently adjudicate
question–record–claim tuples, including mismatched diseases, therapies, other
variants, complex profiles, resistance, contradictory directions, and
unanswerable cases. Compare with unchanged current retrieval and a CIViC MCP
baseline on the same test set. Measure claim-level false support, missed
counterevidence, citation correctness, and appropriate abstention, reporting
all cases excluded by coverage/truncation. Keep development and held-out
questions separate. A model-written answer requires **additional independent
claim/citation verification**; this classifier cannot establish that every
sentence in that answer is supported.
