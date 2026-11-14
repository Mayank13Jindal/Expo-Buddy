from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.storage import MARKER
from app.db.models import Base
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    values = {"app_url": "https://localhost:8443", "assets_free_floor_bytes": 0, "chatgpt_callback_port": 0}
    for name in ("assets", "previews", "db", "models", "exports", "backup"):
        path = tmp_path / name
        path.mkdir()
        volume_id = uuid4()
        (path / MARKER).write_text(str(volume_id))
        values[f"{name}_dir"] = path
        values[f"{name}_volume_id"] = volume_id
    password = tmp_path / "password"
    password.write_text("a" * 48)
    values["database_password_file"] = password
    host = tmp_path / "host"
    host.write_text(str(uuid4()))
    values["host_id_file"] = host
    from cryptography.fernet import Fernet

    encryption = tmp_path / "encryption"
    encryption.write_bytes(Fernet.generate_key())
    values["encryption_key_file"] = encryption
    return Settings(**values)


@pytest.fixture
def engine():
    database = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(database, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(database)
    yield database
    database.dispose()


@pytest.fixture
def client(settings, engine):
    with TestClient(
        create_app(settings, engine=engine),
        base_url="https://localhost:8443",
        headers={"Origin": "https://localhost:8443"},
    ) as web:
        yield web


@pytest.fixture
def signed_in(client):
    assert (
        client.post("/api/v1/auth/setup", json={"password": "fake-test-password-123"}).status_code
        == 201
    )
    client.headers["x-csrf-token"] = client.cookies["expo_csrf"]
    return client
