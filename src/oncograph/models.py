from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EntityType(StrEnum):
    DRUG = "drug"
    TARGET = "target"
    DISEASE = "disease"
    PAPER = "paper"
    TRIAL = "trial"


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


class EntityIdentifier(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("namespace", "value", name="uq_identifier_namespace_value"),)
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    entity_id: UUID = Field(foreign_key="entity.id", index=True)
    namespace: str = Field(index=True)
    value: str = Field(index=True)
    source: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Relation(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("subject_id", "predicate", "object_id", name="uq_relation_spo"),)
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


class SourceSnapshot(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(index=True)
    version: str | None = Field(default=None, index=True)
    retrieved_at: datetime = Field(default_factory=utcnow, index=True)
    checksum: str | None = Field(default=None, index=True)
    record_count: int | None = None
    license_url: str | None = None
    notes: str | None = None


class ResolutionConflict(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    namespace: str = Field(index=True)
    value: str = Field(index=True)
    candidate_entity_id: UUID | None = Field(default=None, foreign_key="entity.id", index=True)
    reason: str
    source: str | None = Field(default=None, index=True)
    resolved: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow)
