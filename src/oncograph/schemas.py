from uuid import UUID

from sqlmodel import SQLModel

from .models import EntityType, VerificationStatus


class EntityCreate(SQLModel):
    type: EntityType
    name: str
    canonical_id: str | None = None
    description: str | None = None


class RelationCreate(SQLModel):
    subject_id: UUID
    predicate: str
    object_id: UUID


class EvidenceCreate(SQLModel):
    relation_id: UUID
    source: str
    source_id: str | None = None
    source_url: str | None = None
    summary: str | None = None
    context: str | None = None
    extraction_method: str = "manual"
    confidence: float | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
