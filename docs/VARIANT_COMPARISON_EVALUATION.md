# Variant comparison: independent evaluation protocol

The public comparison table groups accepted CIViC evidence by molecular profile,
disease and indexed therapy. Its categories reflect the evidence item's recorded
significance and direction. They are **not** patient recommendations, approvals,
independent clinical guidelines or counts of people/studies.

## Review queue and separation from benchmarks

`data/benchmarks/variant_review_queue.json` contains 20 **unanswered candidate
questions**. They are a review queue, not gold labels or a scored evaluation.
Questions were drafted independently of the displayed comparison results; no
clinical answer or "no evidence" conclusion has been asserted for them.

To turn a candidate into a scored item:

1. Freeze the evaluated CIViC snapshot and save its generation date, source
   release, and hash of the exact exported index. Keep the review questions
   separate from the implementation and from any development/tuning set.
2. Have a domain reviewer check the primary publication and the original
   CIViC evidence item(s), including cancer type, molecular profile (possibly
   several variants), therapy, evidence direction, significance, level, rating,
   and publication overlap. Record the CIViC evidence ID and primary PMID/DOI.
3. Label supported sensitivity, supported resistance, contradictory evidence,
   another evidence type, or absence **from the frozen snapshot**. Never treat
   a missing row as proof that evidence does not exist elsewhere. Mark
   unresolvable cases as `cannot_determine`.
4. For a disputed question, record two independent reviews and adjudication.
   Keep disagreement visible. Only reviewed, adjudicated items may enter a
   held-out gold file, with source references and a date.
5. Evaluate answer accuracy, citation precision/recall and incorrect clinical
   inference separately. Stratify by variant type, complex profile, cancer
   context, high vs low evidence level, negative evidence and absent rows.

Do not reuse the graph's existing edges as independent gold: that would test
whether the display can repeat its input rather than validate biomedical
interpretation. Recheck labels after source updates. The queue is deliberately
unscored until independent review is available.
