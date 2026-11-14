from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.library import Record
from app.db.models import Base


class CaptureGroup(Record, Base):
    __tablename__ = "capture_groups"
    client_uuid: Mapped[UUID] = mapped_column(Uuid, unique=True)
    expo_id: Mapped[UUID] = mapped_column(ForeignKey("expos.id"), index=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    device_label: Mapped[str] = mapped_column(String(100), default="Phone")


class CaptureItem(Record, Base):
    __tablename__ = "capture_items"
    client_uuid: Mapped[UUID] = mapped_column(Uuid, unique=True)
    capture_group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("capture_groups.id"), index=True
    )
    document_page_id: Mapped[UUID] = mapped_column(ForeignKey("document_pages.id"))
    expo_id: Mapped[UUID] = mapped_column(ForeignKey("expos.id"))
    sha256: Mapped[str] = mapped_column(String(64))


class SyncReceipt(Record, Base):
    __tablename__ = "sync_receipts"
    client_uuid: Mapped[UUID] = mapped_column(Uuid, unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    server_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class QueueReport(Record, Base):
    __tablename__ = "queue_reports"
    client_uuid: Mapped[UUID] = mapped_column(Uuid, unique=True)
    device_label: Mapped[str] = mapped_column(String(100))
    files: Mapped[int] = mapped_column(Integer)
    notes: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(BigInteger)
