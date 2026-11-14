"""Authentication must return its pooled connection before the endpoint is scheduled."""

from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.dependencies import require_session


def test_authenticated_request_releases_connection_before_endpoint(signed_in, engine, settings):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/events",
            "headers": [
                (b"cookie", ("expo_session=" + signed_in.cookies["expo_session"]).encode())
            ],
        }
    )
    with Session(engine, expire_on_commit=False) as db:
        login = require_session(request, db)
        assert login.owner_id
        assert not db.in_transaction(), (
            "Authentication retained a pooled connection before the endpoint could run."
        )
        assert login not in db
        # The endpoint can still use the dependency's reusable unit of work.
        assert db.get(type(login), login.id)


def test_request_burst_does_not_starve_small_database_pool(settings, tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine

    from app.db.models import Base
    from app.main import create_app

    pool = create_engine(
        "sqlite:///" + str(tmp_path / "burst.db"),
        connect_args={"check_same_thread": False},
        pool_size=2,
        max_overflow=0,
        pool_timeout=1,
    )
    Base.metadata.create_all(pool)
    try:
        with TestClient(
            create_app(settings, engine=pool),
            base_url="https://localhost:8443",
            headers={"Origin": "https://localhost:8443"},
            raise_server_exceptions=False,
        ) as web:
            web.post(
                "/api/v1/auth/setup", json={"password": "synthetic-burst-password"}
            ).raise_for_status()
            with ThreadPoolExecutor(max_workers=48) as workers:
                statuses = list(
                    workers.map(lambda _: web.get("/api/v1/auth/me").status_code, range(96))
                )
            assert statuses == [200] * 96
            assert pool.pool.checkedout() == 0
    finally:
        pool.dispose()
