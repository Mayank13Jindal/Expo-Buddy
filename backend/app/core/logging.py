import json
import logging
from datetime import UTC, datetime


class SafeJsonFormatter(logging.Formatter):
    """Only emit fixed event identifiers, never exception messages or request data."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "time": datetime.now(UTC).isoformat(),
                "level": record.levelname.lower(),
                "event": getattr(record, "event", "runtime_event"),
                "component": record.name,
            }
        )


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeJsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
