"""Typed signed observations and conservative, local-only persistence.

Signs describe an effect within a relation family, never generic benefit or
causality. This importer reuses EntityIdentifier, Relation and Evidence tables.
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy import Index, insert, tuple_
from sqlmodel import Session, select

from .models import Entity, EntityIdentifier, EntityType, Evidence, Relation
from .normalization import normalize_identifier
from .sources.base import EdgeRecord, EntityRecord, ExternalIdentifier, SourceDescriptor

# Subject type, object type, sign, biological interpretation.
SIGNED_RELATIONS = {
    "upregulates": ("drug", "gene", 1, "drug_induced_transcription"),
    "downregulates": ("drug", "gene", -1, "drug_induced_transcription"),
    "activates": ("drug", "protein", 1, "protein_functional_modulation"),
    "inhibits": ("drug", "protein", -1, "protein_functional_modulation"),
    "upregulated_in": ("gene", "disease", 1, "disease_expression_association"),
    "downregulated_in": ("gene", "disease", -1, "disease_expression_association"),
}
BIOLOGICAL_TYPES = {"gene", "protein"}
SIGNED_BATCH_SIZE = 250


def identifier_key(identifier: ExternalIdentifier) -> str:
    """Return the existing crosswalk's normalized identity key.

    Args:
        identifier: Source-supplied external identifier.

    Returns:
        Namespace-qualified exact identifier.
    """
    value = normalize_identifier(identifier)
    return f"{value.namespace}:{value.value}"


def stable_digest(value: object) -> str:
    """Hash a JSON-compatible observation without lossy rounding.

    Args:
        value: Source content or provenance to fingerprint.

    Returns:
        Deterministic SHA-256 hex digest.
    """
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


@dataclass
class SignedImportReport:
    """Exact counters plus identifier-level diagnostics, suitable for JSON export."""

    input_records: int = 0
    parsed_records: int = 0
    scoped_records: int = 0
    mapped_records: int = 0
    relations_created: int = 0
    evidence_created: int = 0
    duplicate_relationships: int = 0
    duplicate_evidence: int = 0
    skipped: Counter = field(default_factory=Counter)
    identifiers: dict[str, dict] = field(default_factory=dict)

    def reset(self) -> None:
        """Reset parser counters in place so caller references remain valid.

        Returns:
            None.
        """
        self.__dict__.update(SignedImportReport().__dict__)


class TypedCrosswalk:
    """Resolve all canonical/alternate claims; never choose the first owner."""

    def __init__(self, session: Session):
        """Index the current database, including legacy ambiguous aliases.

        Args:
            session: Open database session.
        """
        self.session = session
        self.entities = {entity.id: entity for entity in session.exec(select(Entity))}
        self.owners = defaultdict(set)
        self.taxa = defaultdict(set)
        for entity in self.entities.values():
            if entity.canonical_id:
                self.owners[entity.canonical_id].add(entity.id)
            metadata = json.loads(entity.entity_metadata or "{}")
            if metadata.get("taxon_id"):
                self.taxa[entity.id].add(int(metadata["taxon_id"]))
            if (entity.canonical_id or "").startswith("hgnc:"):
                self.taxa[entity.id].add(9606)
        for alias in session.exec(select(EntityIdentifier)):
            self.owners[f"{alias.namespace}:{alias.value}"].add(alias.entity_id)
            if alias.taxon_id:
                self.taxa[alias.entity_id].add(alias.taxon_id)
        self.registration_issues = []
        self.blocked_keys: set[str] = set()

    def resolve(
        self, identifier: ExternalIdentifier, expected: str, taxon: int | None
    ) -> tuple[UUID | None, str]:
        """Reject ambiguity, type conflicts, and unknown/conflicting species.

        Args:
            identifier: Exact external ID, never an entity display name.
            expected: Required entity type.
            taxon: Required species for biological entities.

        Returns:
            Entity UUID and matched status, or no UUID and a diagnostic status.
        """
        key = identifier_key(identifier)
        owners = self.owners.get(key, set())
        if key in self.blocked_keys:
            return None, "conflicting"
        if not owners:
            return None, "unmatched"
        if len(owners) != 1:
            return None, "ambiguous"
        owner = next(iter(owners))
        if self.entities[owner].type != expected:
            return None, "conflicting"
        if expected in BIOLOGICAL_TYPES and (taxon is None or self.taxa[owner] != {taxon}):
            return None, "conflicting"
        return owner, "matched"

    def register(self, records: Iterable[EntityRecord]) -> dict:
        """Add trusted crosswalk records without overwriting existing identities.

        Preflight the entire mapping batch so conflicting aliases cannot become
        dependent on row order. Gene/protein product IDs belong to separate nodes.

        Args:
            records: Source-backed, typed identity records.

        Returns:
            Counts of created entities, mapped records, and rejected records.
        """
        records = list(records)
        claims = defaultdict(set)
        for record in records:
            primary = identifier_key(record.identifiers[0])
            for identifier in record.identifiers:
                claims[identifier_key(identifier)].add(primary)
        # Different primary IDs may legitimately share an existing identity, but
        # new contradictory mappings require explicit review rather than merging.
        for key, primary_ids in claims.items():
            if len(primary_ids) > 1:
                self.blocked_keys.add(key)
        counts = Counter()
        alias_rows = []
        existing_aliases = {
            (row.entity_id, row.namespace, row.value, row.taxon_id)
            for row in self.session.exec(select(EntityIdentifier))
        }
        for record in records:
            keys = [identifier_key(i) for i in record.identifiers]
            owners = set().union(*(self.owners.get(key, set()) for key in keys))
            taxon = record.metadata.get("taxon_id")
            if record.metadata.get("identifier_mapping_conflicts"):
                status = "conflicting"
            elif any(key in self.blocked_keys for key in keys) or len(owners) > 1:
                status = "ambiguous"
            elif owners and any(
                self.resolve(i, record.entity_type, taxon)[1] == "conflicting"
                for i in record.identifiers
                if identifier_key(i) in self.owners
            ):
                status = "conflicting"
            else:
                status = "matched"
            if status != "matched":
                self.blocked_keys.update(keys)
                self.registration_issues.append({"identifiers": keys, "status": status})
                counts[status] += 1
                continue
            if owners:
                entity = self.entities[next(iter(owners))]
            else:
                entity = Entity(
                    type=EntityType(record.entity_type),
                    name=record.name,
                    canonical_id=keys[0],
                    entity_metadata=json.dumps(record.metadata),
                )
                self.session.add(entity)
                self.entities[entity.id] = entity
                counts["created"] += 1
            counts["matched"] += 1
            if taxon:
                self.taxa[entity.id].add(taxon)
            for identifier in record.identifiers:
                normalized = normalize_identifier(identifier)
                self.owners[identifier_key(identifier)].add(entity.id)
                key = (entity.id, normalized.namespace, normalized.value, taxon)
                if key not in existing_aliases:
                    alias_rows.append(
                        EntityIdentifier(
                            entity_id=entity.id,
                            namespace=normalized.namespace,
                            value=normalized.value,
                            taxon_id=taxon,
                            mapping_source=record.metadata.get("source"),
                        )
                    )
                    existing_aliases.add(key)
        self.session.flush()
        self.session.add_all(alias_rows)
        self.session.commit()
        return dict(counts)


def import_signed_observations(
    session: Session,
    records: Iterable[EdgeRecord],
    descriptor: SourceDescriptor,
    crosswalk: TypedCrosswalk,
    report: SignedImportReport,
) -> SignedImportReport:
    """Persist typed observations, preserving distinct contexts and releases.

    Args:
        session: Local database session; caller controls database destination.
        records: Validated source observations, not model predictions.
        descriptor: Original dataset and licensing metadata.
        crosswalk: Strict identifier index for this database.
        report: Parser counters to extend with mapping/import results.

    Returns:
        Updated report, including every skipped identifier and duplicate count.
    """
    try:
        result = _import_signed_observations(session, records, descriptor, crosswalk, report)
        session.commit()
        return result
    except BaseException:
        session.rollback()
        raise


def _import_signed_observations(
    session: Session,
    records: Iterable[EdgeRecord],
    descriptor: SourceDescriptor,
    crosswalk: TypedCrosswalk,
    report: SignedImportReport,
) -> SignedImportReport:
    """Validate and batch observations within the caller's atomic transaction.

    Args:
        session: Transaction-owning session.
        records: Streaming signed observations.
        descriptor: Source license and provenance.
        crosswalk: Species-aware identity resolver.
        report: Counters shared with the source parser.

    Returns:
        Updated import report; no commit is performed here.
    """
    # Composite indexes bound lookups by the current batch, not total graph size.
    for table, name, columns in (
        (
            Relation.__table__,
            "ix_signed_relation_identity",
            ("subject_id", "predicate", "object_id"),
        ),
        (Evidence.__table__, "ix_signed_evidence_identity", ("source", "source_id", "relation_id")),
    ):
        index = next((item for item in table.indexes if item.name == name), None)
        if index is None:
            index = Index(name, *(table.c[column] for column in columns))
        index.create(session.connection(), checkfirst=True)
    pending = []
    for record in records:
        spec = SIGNED_RELATIONS.get(record.predicate)
        context = record.context
        if (
            spec is None
            or context.get("effect_sign") != spec[2]
            or context.get("biological_relationship") != spec[3]
            or context.get("observation_status") not in {"observed", "transformed", "inferred"}
            or context.get("model_generated") is not False
            or not all(
                context.get(k)
                for k in ("release", "file_sha256", "original_predicate", "original_source_dataset")
            )
            or (record.evidence_type is not None and record.evidence_type != spec[3])
            or not record.source_record_id
            or not descriptor.license
        ):
            report.skipped["invalid_signed_contract"] += 1
            continue
        resolved = []
        for identifier, expected in zip((record.subject, record.object), spec[:2]):
            taxon = context.get("taxon_id") if expected in BIOLOGICAL_TYPES else None
            owner, status = crosswalk.resolve(identifier, expected, taxon)
            key = f"{identifier_key(identifier)}|{expected}|{taxon}"
            report.identifiers[key] = {
                "status": status,
                "expected_type": expected,
                "taxon_id": taxon,
            }
            resolved.append(owner)
        if any(owner is None for owner in resolved):
            report.skipped["unresolved_or_conflicting_endpoint"] += 1
            continue
        report.mapped_records += 1
        # Original ID remains intact in context. The evidence key also captures
        # context, release and source scores, so differing observations coexist.
        fingerprint = context
        if record.confidence is not None:
            fingerprint = {"context": context, "source_confidence": record.confidence}
        source_id = f"{record.source_record_id}:{stable_digest(fingerprint)}"
        pending.append(
            (
                (resolved[0], record.predicate, resolved[1]),
                {
                    "source": descriptor.key,
                    "source_id": source_id,
                    "source_url": record.source_url,
                    "source_type": descriptor.source_type,
                    "license": descriptor.license,
                    "evidence_type": spec[3],
                    "context": json.dumps(
                        {
                            **context,
                            "original_source_record_id": record.source_record_id,
                            "redistribution": descriptor.redistribution,
                            "license_url": descriptor.license_url,
                        },
                        sort_keys=True,
                    ),
                    "extraction_method": record.extraction_method or "source_adapter_transform",
                    "confidence": record.confidence,
                },
            )
        )
        if len(pending) >= SIGNED_BATCH_SIZE:
            _persist_signed_batch(session, pending, report)
            pending.clear()
    if pending:
        _persist_signed_batch(session, pending, report)
    return report


def _persist_signed_batch(session: Session, batch: list, report: SignedImportReport) -> None:
    """Insert a bounded batch with the same identity rules as individual imports.

    Args:
        session: Transaction-owning session; never commit individual batches.
        batch: Resolved relation keys and provenance-bearing evidence mappings.
        report: Counters to extend, including duplicates within/across batches.

    Returns:
        None. Raises on pre-existing duplicate relation identities.
    """
    relation_table, evidence_table = Relation.__table__, Evidence.__table__
    keys = {key for key, _ in batch}
    existing = session.execute(
        select(Relation.subject_id, Relation.predicate, Relation.object_id, Relation.id).where(
            tuple_(Relation.subject_id, Relation.predicate, Relation.object_id).in_(keys)
        )
    ).all()
    relations = {}
    for subject, predicate, target, relation_id in existing:
        key = (subject, predicate, target)
        if key in relations:
            raise ValueError(f"Ambiguous existing relation identity: {key}")
        relations[key] = relation_id
    new_relations = []
    for key, _ in batch:
        if key in relations:
            report.duplicate_relationships += 1
        else:
            relations[key] = uuid4()
            new_relations.append(
                {
                    "id": relations[key],
                    "subject_id": key[0],
                    "predicate": key[1],
                    "object_id": key[2],
                }
            )
            report.relations_created += 1
    if new_relations:
        session.execute(insert(relation_table), new_relations)
    # One descriptor per import; source_id includes all context and raw scores.
    source = batch[0][1]["source"]
    evidence_keys = set(
        session.execute(
            select(Evidence.relation_id, Evidence.source_id).where(
                Evidence.source == source,
                Evidence.source_id.in_({item["source_id"] for _, item in batch}),
            )
        ).all()
    )
    new_evidence = []
    for key, item in batch:
        relation_id = relations[key]
        evidence_key = (relation_id, item["source_id"])
        if evidence_key in evidence_keys:
            report.duplicate_evidence += 1
            continue
        evidence_keys.add(evidence_key)
        new_evidence.append({**item, "relation_id": relation_id})
        report.evidence_created += 1
    if new_evidence:
        session.execute(insert(evidence_table), new_evidence)


def signed_effects(session: Session, drug_id: UUID) -> list[dict]:
    """List drug-induced expression observations with uncollapsed provenance.

    Args:
        session: Database session.
        drug_id: Resolved drug entity UUID.

    Returns:
        Evidence-bearing observations; opposite signs are flagged, not averaged.
    """
    return _expression_observations(session, drug_id=drug_id)


def signed_compounds(session: Session, gene_id: UUID) -> list[dict]:
    """List compounds affecting one gene, preserving both signs and every evidence.

    Args:
        session: Database session.
        gene_id: Resolved human gene UUID, not a protein identifier.

    Returns:
        Source-backed observations with separate drug/gene IDs and opposite-sign flags.
    """
    return _expression_observations(session, gene_id=gene_id)


def _expression_observations(
    session: Session, *, drug_id: UUID | None = None, gene_id: UUID | None = None
) -> list[dict]:
    """Read a single entity's transcriptional evidence in either query direction.

    Args:
        session: Database session.
        drug_id: Optional drug endpoint filter.
        gene_id: Optional gene endpoint filter.

    Returns:
        Uncollapsed evidence. Both-sign flags describe observations, not causality.
    """
    if drug_id is None and gene_id is None:
        raise ValueError("A drug or gene endpoint is required")
    observations = []
    signs = defaultdict(set)
    statement = (
        select(Relation, Evidence)
        .join(Evidence, Evidence.relation_id == Relation.id)
        .where(Relation.predicate.in_(["upregulates", "downregulates"]))
    )
    if drug_id is not None:
        statement = statement.where(Relation.subject_id == drug_id)
    if gene_id is not None:
        statement = statement.where(Relation.object_id == gene_id)
    for relation, evidence in session.exec(statement):
        context = json.loads(evidence.context or "{}")
        if (
            evidence.evidence_type != "drug_induced_transcription"
            or context.get("model_generated") is not False
        ):
            continue
        pair = (str(relation.subject_id), str(relation.object_id))
        signs[pair].add(relation.predicate)
        observations.append(
            {
                "drug_id": pair[0],
                "gene_id": pair[1],
                "predicate": relation.predicate,
                "source": evidence.source,
                "source_id": evidence.source_id,
                "context": context,
                "license": evidence.license,
                "source_url": evidence.source_url,
            }
        )
    for observation in observations:
        pair = (observation["drug_id"], observation["gene_id"])
        observation["opposite_direction_observed"] = len(signs[pair]) > 1
    return observations
