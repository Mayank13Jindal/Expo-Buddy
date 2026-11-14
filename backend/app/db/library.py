"""Library schema. Source files are immutable; deletions affect records only."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


def now() -> datetime:
    return datetime.now(UTC)


class Record:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Owner(Record, Base):
    __tablename__ = "owner"
    __table_args__ = (CheckConstraint("singleton = 1"),)
    singleton: Mapped[int] = mapped_column(Integer, unique=True, default=1)
    password_hash: Mapped[str] = mapped_column(Text)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Session(Record, Base):
    __tablename__ = "sessions"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owner.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(256), default="")


class Expo(Record, Base):
    __tablename__ = "expos"
    name: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    venue: Mapped[str] = mapped_column(String(300), default="")
    city: Mapped[str] = mapped_column(String(200), default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    client_uuid: Mapped[UUID | None] = mapped_column(Uuid, unique=True)


class Preference(Record, Base):
    __tablename__ = "preferences"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owner.id"), unique=True)
    active_expo_id: Mapped[UUID | None] = mapped_column(ForeignKey("expos.id"))
    theme: Mapped[str] = mapped_column(String(16), default="system")
    region_hint: Mapped[str] = mapped_column(String(8), default="")
    default_search_scope: Mapped[str] = mapped_column(String(16), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=0)


class UploadSession(Record, Base):
    __tablename__ = "upload_sessions"
    expo_id: Mapped[UUID] = mapped_column(ForeignKey("expos.id"))
    device_label: Mapped[str] = mapped_column(String(100), default="Browser")
    state: Mapped[str] = mapped_column(String(32), default="open")
    client_uuid: Mapped[UUID | None] = mapped_column(Uuid, unique=True)


class Asset(Record, Base):
    __tablename__ = "assets"
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_path: Mapped[str] = mapped_column(String(200), unique=True)
    original_filename: Mapped[str] = mapped_column(String(250))
    mime: Mapped[str] = mapped_column(String(80))
    bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    perceptual_hash: Mapped[str | None] = mapped_column(String(64))
    capture_group_id: Mapped[UUID | None] = mapped_column(Uuid)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Record, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("upload_session_id", "ingest_key"),)
    expo_id: Mapped[UUID] = mapped_column(ForeignKey("expos.id"), index=True)
    upload_session_id: Mapped[UUID | None] = mapped_column(ForeignKey("upload_sessions.id"))
    ingest_key: Mapped[str | None] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(24), default="other")
    title: Mapped[str] = mapped_column(String(400))
    group_state: Mapped[str] = mapped_column(String(24), default="suggested")
    review_state: Mapped[str] = mapped_column(String(24), default="unreviewed")
    processing_state: Mapped[str] = mapped_column(String(32), default="received")
    review_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    processing_options: Mapped[dict] = mapped_column(JSON, default=dict)
    company_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class DocumentPage(Record, Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "order"),)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"))
    pdf_page_no: Mapped[int | None] = mapped_column(Integer)
    order: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16), default="page")


class Note(Record, Base):
    __tablename__ = "notes"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN document_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN company_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN asset_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN capture_group_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN expo_id IS NOT NULL THEN 1 ELSE 0 END) = 1"
        ),
    )
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), index=True)
    company_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id"))
    capture_group_id: Mapped[UUID | None] = mapped_column(Uuid)
    expo_id: Mapped[UUID | None] = mapped_column(ForeignKey("expos.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    client_uuid: Mapped[UUID | None] = mapped_column(Uuid, unique=True)
    origin: Mapped[str] = mapped_column(String(100), default="web")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
