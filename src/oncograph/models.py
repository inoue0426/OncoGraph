from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class Entity(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    type: EntityType = Field(index=True)
    name: str = Field(index=True)
    canonical_id: str | None = Field(default=None, index=True)
    description: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Relation(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    subject_id: UUID = Field(foreign_key="entity.id", index=True)
    predicate: str = Field(index=True)
    object_id: UUID = Field(foreign_key="entity.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Evidence(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    relation_id: UUID = Field(foreign_key="relation.id", index=True)
    source: str = Field(index=True)
    source_id: str | None = Field(default=None, index=True)
    source_url: str | None = None
    summary: str | None = None
    context: str | None = None
    extraction_method: str = "manual"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_status: VerificationStatus = Field(default=VerificationStatus.UNVERIFIED)
    retrieved_at: datetime = Field(default_factory=utcnow)
