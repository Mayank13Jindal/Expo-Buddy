from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.library import Record
from app.db.models import Base


class Company(Record, Base):
    __tablename__ = "companies"
    display_name: Mapped[str] = mapped_column(
        String(300), default="Unidentified company", index=True
    )
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    website: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    business_role: Mapped[str] = mapped_column(String(300), default="")
    products: Mapped[list] = mapped_column(JSON, default=list)
    services: Mapped[list] = mapped_column(JSON, default=list)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Contact(Record, Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("source_document_id", "source_key"),)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    source_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"))
    source_key: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(300), default="")
    designation: Mapped[str] = mapped_column(String(300), default="")
    department: Mapped[str] = mapped_column(String(300), default="")
    channels: Mapped[list] = mapped_column(JSON, default=list)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContactChannel(Record, Base):
    __tablename__ = "contact_channels"
    __table_args__ = (UniqueConstraint("owner_type", "owner_id", "kind", "raw"),)
    owner_type: Mapped[str] = mapped_column(String(16))
    owner_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(80), default="")
    raw: Mapped[str] = mapped_column(Text)
    normalised: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Appearance(Record, Base):
    __tablename__ = "appearances"
    __table_args__ = (UniqueConstraint("document_id", "company_id", "contact_id"),)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contacts.id"))
    expo_id: Mapped[UUID] = mapped_column(ForeignKey("expos.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)


class FieldValue(Record, Base):
    __tablename__ = "field_values"
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    field: Mapped[str] = mapped_column(String(80))
    value: Mapped[object] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    extraction_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("extraction_runs.id"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Proposal(Record, Base):
    __tablename__ = "proposals"
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    field: Mapped[str] = mapped_column(String(80))
    current_value: Mapped[object | None] = mapped_column(JSON)
    proposed_value: Mapped[object] = mapped_column(JSON)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    actor: Mapped[str] = mapped_column(String(100), default="ai")
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"))


class EditHistory(Record, Base):
    __tablename__ = "edit_history"
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    field: Mapped[str] = mapped_column(String(80))
    old: Mapped[object | None] = mapped_column(JSON)
    new: Mapped[object | None] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(100), default="owner")
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DuplicateSuggestion(Record, Base):
    __tablename__ = "duplicate_suggestions"
    __table_args__ = (UniqueConstraint("entity_type", "source_id", "candidate_id"),)
    entity_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[UUID] = mapped_column(Uuid)
    candidate_id: Mapped[UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending")


class ProviderSetting(Record, Base):
    __tablename__ = "provider_settings"
    provider: Mapped[str] = mapped_column(String(30), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(200), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_secret: Mapped[str | None] = mapped_column(Text)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_status: Mapped[str] = mapped_column(String(80), default="off")
    month: Mapped[str] = mapped_column(String(7), default="")
    spent: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    reserved: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    spending_cap: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)


class Tag(Record, Base):
    __tablename__ = "tags"
    label: Mapped[str] = mapped_column(String(100), unique=True)
    source: Mapped[str] = mapped_column(String(100), default="owner")


class TagLink(Record, Base):
    __tablename__ = "tag_links"
    __table_args__ = (UniqueConstraint("tag_id", "entity_type", "entity_id"),)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("tags.id"))
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[UUID] = mapped_column(Uuid, index=True)
