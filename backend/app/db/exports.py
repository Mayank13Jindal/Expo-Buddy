from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.library import Record
from app.db.models import Base


class ExportPreset(Record, Base):
    __tablename__ = "export_presets"
    name: Mapped[str] = mapped_column(String(150))
    selection: Mapped[dict] = mapped_column(JSON)


class Export(Record, Base):
    __tablename__ = "exports"
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    format: Mapped[str] = mapped_column(String(8))
    selection: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    counts: Mapped[dict] = mapped_column(JSON)
    path: Mapped[str] = mapped_column(String(200), default="")
    error: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    token_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    download_hash: Mapped[str | None] = mapped_column(String(64))
    download_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
