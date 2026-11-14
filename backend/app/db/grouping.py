from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.library import Record
from app.db.models import Base


class GroupingAction(Record, Base):
    __tablename__ = "grouping_actions"
    kind: Mapped[str] = mapped_column(String(32))
    upload_session_id: Mapped[UUID | None] = mapped_column(ForeignKey("upload_sessions.id"))
    snapshot: Mapped[dict] = mapped_column(JSON)
    after_revisions: Mapped[dict] = mapped_column(JSON, default=dict)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
