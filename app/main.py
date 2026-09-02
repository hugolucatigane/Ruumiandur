from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai_summary import SummaryResult, generate_summary, prepare_facts
from .analytics import analyse_readings, build_device_status, fallback_summary
from .config import Settings
from .database import Database
from .models import IngestResult, ReadingCreate


STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    database = Database(app_settings.database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        yield

    app = FastAPI(
        title="Ruumiandur API",
        version="0.1.0",
        description="ESP8266 ruumianduri prototüübi REST API",
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.settings = app_settings
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        if request.method == "POST" and request.url.path == "/api/readings":
            body = exc.body if isinstance(exc.body, dict) else {}
            raw_device_id = body.get("device_id")
            device_id = raw_device_id[:64] if isinstance(raw_device_id, str) else None
            detail = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()[:3]
            )
            database.record_event(device_id, "invalid_payload", detail)
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/readings", response_model=IngestResult, status_code=201)
    async def create_reading(reading: ReadingCreate) -> IngestResult:
        status, reading_id, received_at = database.insert_reading(reading)
        return IngestResult(status=status, reading_id=reading_id, received_at=received_at)

    @app.get("/api/readings")
    async def get_readings(
        device_id: str = Query(default="esp8266-bedroom-1", min_length=1, max_length=64),
        limit: int = Query(default=100, ge=1, le=500),
        minutes: float | None = Query(default=None, gt=0, le=10_080),
    ) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes) if minutes else None
        readings = database.recent_readings(device_id, limit=limit, since=since)
        return {"device_id": device_id, "count": len(readings), "readings": readings}

    @app.get("/api/status")
    async def get_status(
        device_id: str = Query(default="esp8266-bedroom-1", min_length=1, max_length=64),
    ) -> dict[str, Any]:
        return _device_status(database, device_id, app_settings)

    @app.get("/api/summary")
    async def get_summary(
        device_id: str = Query(default="esp8266-bedroom-1", min_length=1, max_length=64),
        hours: float = Query(default=24.0, gt=0, le=24),
        use_ai: bool = True,
    ) -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        readings = database.recent_readings(device_id, limit=10_000, since=since)
        status = _device_status(database, device_id, app_settings)
        report = analyse_readings(readings, status, hours, app_settings)
        fallback = fallback_summary(report)
        if use_ai:
            result = await asyncio.to_thread(generate_summary, report, fallback)
        else:
            result = generate_summary_without_ai(report, fallback)
        return {
            **report,
            "summary": result.text,
            "summary_source": result.source,
            "ai_input_bytes": result.input_bytes,
            "ai_error": result.error,
        }

    return app


def _device_status(database: Database, device_id: str, settings: Settings) -> dict[str, Any]:
    return build_device_status(
        database.latest_reading(device_id),
        database.latest_event(device_id),
        database.latest_invalid_event(device_id),
        database.rejected_count(device_id),
        settings,
    )


def generate_summary_without_ai(report: dict[str, Any], fallback: str):
    _, input_bytes = prepare_facts(report)
    return SummaryResult(fallback, "rules_requested", input_bytes)


app = create_app()
