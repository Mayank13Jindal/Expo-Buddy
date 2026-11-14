import json
import math

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db.library import Record
from app.db.models import Base


class Vector384(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "vector(384)"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if len(value) != 384 or not all(math.isfinite(float(item)) for item in value):
                raise ValueError("Expected 384 finite numbers")
            return json.dumps([float(item) for item in value])

        return process

    def result_processor(self, dialect, coltype):
        return lambda value: json.loads(value) if isinstance(value, str) else value


class SavedSearch(Record, Base):
    __tablename__ = "saved_searches"
    name: Mapped[str] = mapped_column(String(150))
    query: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)


class BulkAction(Record, Base):
    __tablename__ = "bulk_actions"
    kind: Mapped[str] = mapped_column(String(24))
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="applied")
