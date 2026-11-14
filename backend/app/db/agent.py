from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.library import Record
from app.db.models import Base


class APIToken(Record, Base):
    __tablename__ = "api_tokens"
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSON, default=lambda: ["read"])
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    minute: Mapped[str] = mapped_column(String(20), default="")
    calls: Mapped[int] = mapped_column(Integer, default=0)


class AgentAudit(Record, Base):
    __tablename__ = "agent_audit"
    token_id: Mapped[UUID | None] = mapped_column(ForeignKey("api_tokens.id"), index=True)
    tool: Mapped[str] = mapped_column(String(100))
    arguments_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40))
