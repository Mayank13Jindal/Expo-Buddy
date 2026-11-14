from alembic import context

from app.core.config import Settings
from app.db import (
    capture,  # noqa: F401
    grouping,  # noqa: F401
    intelligence,  # noqa: F401
    library,  # noqa: F401
    processing,  # noqa: F401
    search,  # noqa: F401
)
from app.db.models import Base
from app.db.session import build_engine


def run_migrations() -> None:
    if context.is_offline_mode():
        context.configure(
            url="postgresql+psycopg://",
            target_metadata=Base.metadata,
            literal_binds=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = build_engine(Settings())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
