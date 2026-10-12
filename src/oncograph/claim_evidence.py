"""Conservative classification of a CIViC Evidence Tree, for research only."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from .evidence_tree import get_evidence_tree


def evaluate_evidence_claim(tree: dict[str, Any], *, therapy: str, effect: str,
                            scope: str = "variant", limit: int = 20) -> dict[str, Any]:
    """Classify accepted records without promoting graph paths to clinical claims.

    Only predictive evidence with an exact named therapy and a single-variant
    molecular profile is eligible for variant-specific support/opposition.
    An opposing significance is context, not necessarily a logical negation.
    """
    if (not isinstance(therapy, str) or not therapy.strip()
            or effect not in {"sensitivity", "resistance"} or scope not in {"variant", "profile"}
            or type(limit) is not int or not 1 <= limit <= 200):
        raise ValueError("Invalid claim query")
    if not isinstance(tree, dict) or not isinstance(tree.get("evidence"), list) or "query" not in tree:
        raise ValueError("Invalid evidence tree")

    def normal(value: Any) -> str:
        return str(value or "").strip().casefold()

    groups: dict[str, list[dict[str, Any]]] = {key: [] for key in
                                               ("supporting", "opposing", "disputed", "context_only")}
    excluded = {key: 0 for key in
                ("wrong_therapy", "non_predictive", "incomplete_profile", "unrelated_effect")}
    for item in tree["evidence"]:
        if not any(normal(drug.get(field)) == normal(therapy)
                   for drug in (item.get("therapies") or []) for field in ("id", "name")):
            excluded["wrong_therapy"] += 1
            continue
        if normal(item.get("evidence_type")) != "predictive":
            excluded["non_predictive"] += 1
            continue
        significance = normal(item.get("significance"))
        if significance not in {"sensitivity", "resistance"}:
            excluded["unrelated_effect"] += 1
            continue
        profile = item.get("profile") or {}
        exact_profile = (scope == "profile" and profile.get("match_type") == "profile_only"
                         and normal(profile.get("name")) == normal(tree["query"].get("variant")))
        if not exact_profile and (profile.get("match_type") != "variant_member" or profile.get("complex_profile")):
            groups["context_only"].append({**item, "reason":
                "Variant-specific effect unverified for this molecular profile"})
            excluded["incomplete_profile"] += 1
            continue
        direction = normal(item.get("claim_state"))
        if direction == "supports" and significance == effect:
            groups["supporting"].append(item)
        elif direction == "supports":
            groups["opposing"].append(item)
        elif direction == "contradicts" and significance == effect:
            groups["disputed"].append(item)
        else:
            groups["context_only"].append({**item, "reason":
                "Evidence direction does not establish the requested effect"})

    totals = {key: len(rows) for key, rows in groups.items()}
    selected: dict[str, list[dict[str, Any]]] = {key: [] for key in groups}
    remaining = limit
    for key, rows in groups.items():
        if remaining and rows:
            selected[key].append(rows.pop(0))
            remaining -= 1
    for key, rows in groups.items():
        selected[key].extend(rows[:remaining])
        remaining -= min(len(rows), remaining)
    incomplete = bool(tree.get("truncated")) or any(len(selected[key]) < count
                                                       for key, count in totals.items())
    if incomplete:
        status = "incomplete_review"
    elif totals["supporting"] and (totals["opposing"] or totals["disputed"]):
        status = "mixed_records"
    elif totals["supporting"]:
        status = "supporting_records"
    elif totals["opposing"] or totals["disputed"]:
        status = "opposing_or_disputed_records"
    elif totals["context_only"]:
        status = "insufficient_variant_context"
    else:
        status = "not_found_in_snapshot"
    return {"schema_version": "1.0", "query": {**tree["query"], "therapy": therapy.strip(),
                                                "effect": effect, "scope": scope},
            "status": status, "counts": totals, "excluded": excluded, "incomplete": incomplete,
            "evidence": selected,
            "limitations": ["This checks a bounded CIViC snapshot, not treatment efficacy, FDA status or patient suitability.",
                            "An opposing report is not necessarily a direct contradiction; study contexts may differ.",
                            "No matched record does not establish absence of evidence outside this snapshot."]}


def get_claim_evidence(session: Session, *, gene: str, variant: str, disease: str,
                       therapy: str, effect: str, scope: str = "variant",
                       limit: int = 20) -> dict[str, Any]:
    """Use the same capped Evidence Tree as the browser; flag incomplete input."""
    return evaluate_evidence_claim(get_evidence_tree(session, gene=gene, variant=variant,
                                                     disease=disease, limit=200),
                                   therapy=therapy, effect=effect, scope=scope, limit=limit)
