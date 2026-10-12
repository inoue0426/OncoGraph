"""Trace accepted CIViC records without upgrading them to US regulatory claims."""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from .models import Entity, Evidence, Relation


def build_evidence_tree(
    entities: list[dict[str, Any]], relations: list[dict[str, Any]],
    *, gene: str, variant: str, disease: str, jurisdiction: str = "US", limit: int = 50,
) -> dict[str, Any]:
    """Project an exported graph into a bounded, source-linked evidence tree.

    Exact, case-insensitive matching only. A profile name match without an
    exported variant membership is flagged as profile_only, never as a
    confirmed variant match. Complex profiles are always identified as such.
    """
    if jurisdiction != "US":
        raise ValueError("Only jurisdiction='US' is supported")
    if not all(isinstance(value, str) and value.strip() for value in (gene, variant, disease)):
        raise ValueError("gene, variant and disease must be nonempty strings")
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    by_id = {str(entity["id"]): entity for entity in entities}
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for relation in relations:
        if relation.get("predicate") not in {"has_civic_evidence_for", "clinically_evidenced_for"}:
            continue
        cancer = by_id.get(str(relation.get("object_id")))
        if not cancer or str(cancer.get("type", "")).lower() != "disease":
            continue
        disease_key = str(cancer.get("canonical_id") or "").casefold()
        if disease.casefold().strip() not in {disease_key, str(cancer.get("name") or "").casefold()}:
            continue
        therapy = by_id.get(str(relation.get("subject_id"))) if relation["predicate"] == "clinically_evidenced_for" else None
        for evidence in relation.get("evidence") or []:
            ctx = evidence.get("context") or {}
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except (ValueError, TypeError):
                    continue
            if (evidence.get("source") != "civic" or ctx.get("civic_review_status") != "ACCEPTED"
                    or not ctx.get("civic_evidence_id") or not ctx.get("molecular_profile_id")
                    or str(ctx.get("gene_name") or "").casefold() != gene.casefold().strip()):
                continue
            members = ctx.get("profile_variants") or []
            if not isinstance(members, list):
                members = []
            names = {str(member).casefold() for member in members}
            query_name = variant.strip().casefold()
            match = "variant_member" if names and (query_name in names or f"{gene.strip().casefold()} {query_name}" in names) else None
            if match is None and not names and query_name in {
                str(ctx.get("molecular_profile") or "").casefold(),
                str(ctx.get("molecular_profile") or "").casefold().removeprefix(gene.strip().casefold() + " "),
            }:
                match = "profile_only"
            if match is None:
                continue
            evidence_id = str(ctx["civic_evidence_id"])
            key = (evidence_id, str(ctx["molecular_profile_id"]), disease_key)
            if key not in grouped:
                grouped[key] = {
                    "evidence_id": evidence_id,
                    "profile": {"id": str(ctx["molecular_profile_id"]), "name": ctx.get("molecular_profile"),
                                "variants": members, "match_type": match, "complex_profile": len(members) > 1},
                    "disease": {"id": cancer.get("canonical_id"), "name": cancer.get("name")},
                    "evidence_type": ctx.get("civic_evidence_type"), "level": ctx.get("evidence_level"),
                    "rating": ctx.get("evidence_rating"), "significance": ctx.get("significance"),
                    "claim_state": str(evidence.get("claim_state") or "uncertain").lower(),
                    "source": "civic", "source_id": evidence.get("source_id"),
                    "source_url": evidence.get("source_url"), "citation_url": ctx.get("citation_url"),
                    "retrieved_at": evidence.get("retrieved_at"), "therapies": [],
                }
            if therapy and str(therapy.get("type", "")).lower() == "drug":
                drug = {"id": therapy.get("canonical_id"), "name": therapy.get("name")}
                if drug not in grouped[key]["therapies"]:
                    grouped[key]["therapies"].append(drug)
    records = sorted(grouped.values(), key=lambda item: (item["evidence_id"], item["profile"]["id"]))
    return {
        "schema_version": "1.0", "query": {"gene": gene.strip(), "variant": variant.strip(),
                                           "disease": disease.strip(), "jurisdiction": jurisdiction},
        "status": "matched" if records else "not_found_in_snapshot",
        "total_evidence_items": len(records), "truncated": len(records) > limit,
        "evidence": records[:limit],
        "us_regulatory_label": {"status": "not_integrated", "source": None},
        "civic_assertions": {"status": "not_integrated", "source": None},
        "limitations": ["Accepted CIViC evidence items are literature records, not FDA approvals or treatment recommendations.",
                        "Variant membership in a complex profile does not attribute evidence to that variant alone.",
                        "Absence from this bounded snapshot does not establish absence of evidence."],
    }


def get_evidence_tree(session: Session, *, gene: str, variant: str, disease: str,
                      jurisdiction: str = "US", limit: int = 50) -> dict[str, Any]:
    """Read the local SQLite database and apply the public projection."""
    evidence_rows = session.exec(select(Evidence).where(Evidence.source == "civic")).all()
    relation_ids = {row.relation_id for row in evidence_rows}
    relation_rows = session.exec(select(Relation).where(Relation.id.in_(relation_ids))).all() if relation_ids else []
    entity_ids = {entity_id for row in relation_rows for entity_id in (row.subject_id, row.object_id)}
    entity_rows = session.exec(select(Entity).where(Entity.id.in_(entity_ids))).all() if entity_ids else []
    packed = {str(row.id): {"subject_id": str(row.subject_id), "object_id": str(row.object_id),
                             "predicate": row.predicate, "evidence": []} for row in relation_rows}
    for row in evidence_rows:
        if str(row.relation_id) in packed:
            packed[str(row.relation_id)]["evidence"].append({
                "source": row.source, "source_id": row.source_id, "source_url": row.source_url,
                "context": row.context, "claim_state": row.claim_state,
                "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
            })
    return build_evidence_tree(
        [{"id": str(row.id), "type": row.type, "name": row.name, "canonical_id": row.canonical_id}
         for row in entity_rows], list(packed.values()), gene=gene, variant=variant,
        disease=disease, jurisdiction=jurisdiction, limit=limit,
    )
