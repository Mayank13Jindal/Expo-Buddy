import json
import logging
from datetime import UTC, datetime

# Safe diagnostic fields: IDs, job kinds, tool names and exception class names.
# Exception messages and request data can hold personal details, so they are never logged.
SAFE_FIELDS = ("job_id", "job_kind", "tool", "error_type")


def error_type(error: BaseException) -> str:
    return type(error).__name__


class SafeJsonFormatter(logging.Formatter):
    """Only emit fixed event identifiers and allow-listed fields, never exception messages."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": getattr(record, "event", "runtime_event"),
            "component": record.name,
        }
        for field in SAFE_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = str(value)[:100]
        return json.dumps(entry)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeJsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
