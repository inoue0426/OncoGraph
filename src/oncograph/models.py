from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class EntityType(StrEnum):
    DRUG = "drug"
    TARGET = "target"
    GENE = "gene"
    PROTEIN = "protein"
    DISEASE = "disease"
    PAPER = "paper"
    TRIAL = "trial"
    PATHWAY = "pathway"
    GO_TERM = "go_term"
    CELL_TYPE = "cell_type"
    CELL_STATE = "cell_state"
    LIGAND = "ligand"
    RECEPTOR = "receptor"
    PERTURBATION = "perturbation"
    MODEL_SYSTEM = "model_system"
    CELL_LINE = "cell_line"
    PDX = "pdx"
    ORGANOID = "organoid"
    COHORT = "cohort"
    ASSAY = "assay"
    PHENOTYPE = "phenotype"
    RESPONSE = "response"
    RESISTANCE_MECHANISM = "resistance_mechanism"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ClaimState(StrEnum):
    """What a piece of evidence says about its relation, not how reliable it is.

    Confidence/verification_status are orthogonal: a CONTRADICTS row can still
    be high-confidence, and an UNVERIFIED row can still SUPPORT its relation.
    """

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    UNCERTAIN = "uncertain"
    CONTEXT_DEPENDENT = "context_dependent"


class ResolutionIssueType(StrEnum):
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


class Entity(SQLModel, table=True):
    """A node in the graph, identified where possible by a stable external ID.

    ``entity_metadata`` is a JSON object (serialized to text) for type-specific
    properties that don't need their own column -- e.g. a Publication's
    journal/year/authors/publication type. Prefer this over adding columns
    for one entity type; promote to a real column only once it needs to be
    indexed/queried directly (mirrors ``Evidence.context``). Named
    ``entity_metadata`` rather than ``metadata`` -- SQLAlchemy's declarative
    base reserves that attribute name.
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    type: EntityType = Field(index=True)
    name: str = Field(index=True)
    canonical_id: str | None = Field(default=None, index=True)
    description: str | None = None
    entity_metadata: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Relation(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    subject_id: UUID = Field(foreign_key="entity.id", index=True)
    predicate: str = Field(index=True)
    object_id: UUID = Field(foreign_key="entity.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Evidence(SQLModel, table=True):
    """A provenance-bearing claim attached to one Relation.

    ``context`` is a JSON object (serialized to text), deliberately used
    instead of adding a new column per future dimension (cancer type, tissue,
    cell state, dose, timepoint, responder context, ...). Promote a context
    key to a real column only once it needs to be indexed/queried directly.
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    relation_id: UUID = Field(foreign_key="relation.id", index=True)
    source: str = Field(index=True)
    source_id: str | None = Field(default=None, index=True)
    source_url: str | None = None
    source_type: str | None = Field(default=None, index=True)
    evidence_type: str | None = Field(default=None, index=True)
    license: str | None = None
    # The Publication (Entity where type == "paper") this evidence cites, if
    # any. A relation can have several Evidence rows, each citing a different
    # publication, so this is how "multiple publications per relation" works
    # -- no separate junction table needed.
    publication_id: UUID | None = Field(default=None, foreign_key="entity.id", index=True)
    summary: str | None = None
    context: str | None = None
    extraction_method: str = "manual"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    claim_state: ClaimState = Field(default=ClaimState.SUPPORTS, index=True)
    verification_status: VerificationStatus = Field(default=VerificationStatus.UNVERIFIED)
    retrieved_at: datetime = Field(default_factory=utcnow)


class EntityResolutionIssue(SQLModel, table=True):
    """A durable log of identifier resolution problems, for validation/reporting.

    Two kinds: UNRESOLVED (an edge referenced an identifier with no matching
    entity -- the edge is skipped, never guessed at) and CONFLICT (the same
    canonical identifier was claimed by incoming records with different
    entity types, e.g. one adapter calling HGNC:1 a gene and another calling
    it a disease -- the existing entity's type is kept, not silently
    overwritten). This is in addition to, not instead of, the transient
    ImportReport.errors surfaced during a single import run.
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    issue_type: ResolutionIssueType = Field(index=True)
    namespace: str = Field(index=True)
    value: str = Field(index=True)
    source: str | None = Field(default=None, index=True)
    detail: str | None = None
    detected_at: datetime = Field(default_factory=utcnow)
