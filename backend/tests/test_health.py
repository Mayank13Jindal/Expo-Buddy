from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.storage import MARKER, StorageGuard, StorageUnavailable, configured_volumes
from app.main import create_app


def test_liveness_and_unavailable_database(settings: Settings):
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("password=do-not-display")
    with TestClient(create_app(settings, engine=engine)) as client:
        assert client.get("/api/v1/health/live").json() == {"status": "alive"}
        response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert "password" not in response.text
        assert "do-not-display" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["release_ready"] is False


def test_startup_refuses_missing_drive(settings: Settings):
    (settings.assets_dir / MARKER).unlink()
    with pytest.raises(StorageUnavailable):
        with TestClient(create_app(settings, engine=MagicMock())):
            pass


def test_health_changes_when_storage_is_lost(settings: Settings):
    guard = StorageGuard(configured_volumes(settings), interval=0)
    with TestClient(create_app(settings, engine=MagicMock(), storage=guard)) as client:
        (settings.backup_dir / MARKER).unlink()
        response = client.get("/api/v1/health")
        disk = next(row for row in response.json()["storage"] if row["name"] == "backups")
        assert disk["status"] == "unavailable"


@pytest.mark.parametrize("url", ["http://localhost", "https://host/path", "https://u:p@host"])
def test_canonical_url_validation(settings: Settings, url: str):
    with pytest.raises(ValidationError):
        Settings(**{**settings.model_dump(), "app_url": url})


def test_database_password_is_escaped_and_redacted(settings: Settings):
    settings.database_password_file.write_text("with@slash/special?and%space " * 2)
    assert "with@slash" not in str(settings.database_url)
    assert settings.database_url.password.startswith("with@slash")


def test_json_is_bounded_before_parsing_or_authentication(client):
    assert (
        client.post(
            "/api/v1/auth/login",
            content=b"x" * (1024 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/mcp", content=b"x" * 65537, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
