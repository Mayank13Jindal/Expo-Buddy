from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.library import Record, now
from app.db.models import Base
from app.db.search import Vector384


class AssetDerivative(Record, Base):
    __tablename__ = "asset_derivatives"
    __table_args__ = (UniqueConstraint("document_page_id", "kind", "revision"),)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), index=True)
    document_page_id: Mapped[UUID] = mapped_column(ForeignKey("document_pages.id"))
    kind: Mapped[str] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(240))
    params: Mapped[dict] = mapped_column(JSON, default=dict)


class ExtractionRun(Record, Base):
    __tablename__ = "extraction_runs"
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    stage: Mapped[str] = mapped_column(String(24))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200), default="")
    version: Mapped[str] = mapped_column(String(100), default="")
    input_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(500))


class OCRResult(Record, Base):
    __tablename__ = "ocr_results"
    __table_args__ = (UniqueConstraint("document_page_id", "revision"),)
    document_page_id: Mapped[UUID] = mapped_column(ForeignKey("document_pages.id"), index=True)
    extraction_run_id: Mapped[UUID] = mapped_column(ForeignKey("extraction_runs.id"))
    revision: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    text: Mapped[str] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(String(120))


class SearchChunk(Record, Base):
    __tablename__ = "search_chunks"
    __table_args__ = (UniqueConstraint("source_type", "source_id", "ordinal"),)
    source_type: Mapped[str] = mapped_column(String(20), index=True)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID | None] = mapped_column(ForeignKey("documents.id"), index=True)
    page_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_pages.id"))
    expo_id: Mapped[UUID | None] = mapped_column(ForeignKey("expos.id"), index=True)
    company_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_revision: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list | None] = mapped_column(Vector384().with_variant(JSON(), "sqlite"))
    model_version: Mapped[str] = mapped_column(String(100), default="")
    embedding_text_revision: Mapped[int | None] = mapped_column(Integer)
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR().with_variant(Text(), "sqlite"))


class Job(Record, Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("kind", "target_id", "input_revision"),)
    kind: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    input_revision: Mapped[int] = mapped_column(Integer)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    pool: Mapped[str] = mapped_column(String(10), default="local", index=True)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(String(500))
