import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine

from app import __version__
from app.api import (
    accuracy,
    agent,
    assets,
    auth,
    capture,
    chatgpt_connection,
    exports,
    grouping,
    image_edits,
    intelligence,
    library,
    operations,
    processing,
    providers,
    search,
    system,
    trash,
    uploads,
)
from app.api.health import read_health
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.storage import StorageGuard, StorageUnavailable, configured_volumes
from app.db.session import build_engine

log = logging.getLogger("api")


class StorageHealth(BaseModel):
    name: str
    status: str
    message: str
    warning: bool


class Health(BaseModel):
    status: str
    stage: int
    release_ready: bool
    services: dict[str, str]
    storage: list[StorageHealth]
    canonical_url: str
    message: str


async def monitor_storage(guard: StorageGuard, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        statuses = await run_in_threadpool(guard.check, force=True)
        if any(not status.ok for status in statuses):
            log.warning("storage_unavailable", extra={"event": "storage_unavailable"})


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    storage: StorageGuard | None = None,
) -> FastAPI:
    configure_logging()
    settings = settings or Settings()
    storage = storage or StorageGuard(
        configured_volumes(settings),
        interval=settings.storage_check_seconds,
    )
    engine = engine or build_engine(settings)
    from app.mcp.server import create_mcp

    mcp_app, sdk_app = create_mcp(settings, engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Refuse startup before any file work when a drive is missing or too full.
        await run_in_threadpool(storage.require_ready)
        import tempfile

        temporary = settings.previews_dir / ".tmp"
        temporary.mkdir(exist_ok=True, mode=0o700)
        previous_temporary = tempfile.tempdir
        tempfile.tempdir = str(temporary)
        _ = settings.host_id  # Must exist before any future credential import.
        task = asyncio.create_task(monitor_storage(storage, settings.storage_check_seconds))
        log.info("api_started", extra={"event": "api_started"})
        try:
            async with sdk_app.router.lifespan_context(sdk_app):
                yield
        finally:
            tempfile.tempdir = previous_temporary
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            flow = getattr(app.state, "chatgpt_loopback", None)
            if flow:
                await run_in_threadpool(flow.close)
            engine.dispose()

    app = FastAPI(
        title="Expo Buddy",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    from app.core.body_limit import JSONBodyLimit

    app.add_middleware(JSONBodyLimit)
    app.state.settings = settings
    app.state.storage = storage
    app.state.engine = engine
    app.include_router(auth.router)
    app.include_router(accuracy.router)
    app.include_router(agent.router)
    app.include_router(capture.router)
    app.include_router(exports.router)
    app.include_router(system.router)
    app.include_router(operations.router)
    app.include_router(assets.router)
    app.include_router(library.router)
    app.include_router(uploads.router)
    app.include_router(processing.router)
    app.include_router(grouping.router)
    app.include_router(intelligence.router)
    app.include_router(chatgpt_connection.router)
    app.include_router(providers.router)
    app.include_router(search.router)
    app.include_router(image_edits.router)
    app.include_router(trash.router)

    @app.exception_handler(StorageUnavailable)
    async def storage_error(request: Request, error: StorageUnavailable):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError):
        if (
            request.method == "GET"
            and request.url.path.startswith("/api/v1/documents/")
            and any(item["loc"][:1] == ("path",) for item in error.errors())
        ):
            return JSONResponse({"detail": "Document not found."}, status_code=404)
        return JSONResponse(
            {
                "detail": "Check the form and try again.",
                "fields": [list(item["loc"]) for item in error.errors()],
            },
            status_code=422,
        )

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        if request.method == "POST" and request.url.path.endswith("/files"):
            try:
                await run_in_threadpool(storage.require_ready)
            except StorageUnavailable as error:
                return JSONResponse({"detail": str(error)}, status_code=503)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/api/v1/health", response_model=Health)
    def health() -> JSONResponse:
        status = read_health(engine, storage, settings)
        return JSONResponse(status, status_code=200 if status["status"] == "ready" else 503)

    app.mount("/", mcp_app)
    return app
