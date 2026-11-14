"""Host-side configuration helpers; deliberately standard-library only."""

from pathlib import Path

NAMES = ("ASSETS", "PREVIEWS", "DB", "MODELS", "EXPORTS", "BACKUP")
LABELS = {"ASSETS": "originals", "PREVIEWS": "previews", "DB": "database",
          "MODELS": "models", "EXPORTS": "exports", "BACKUP": "backups"}
MARKER = ".expo-buddy-volume"


def read_env(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.replace("_", "").isalnum():
            raise ValueError("Invalid .env line")
        result[key] = value.strip().strip("'\"")
    return result

