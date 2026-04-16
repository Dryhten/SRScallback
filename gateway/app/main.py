from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .auth import require_admin, validate_admin_credentials
from .config import settings
from .database import db
from .schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    DeliveryRetryResponse,
    HookAcceptedResponse,
    HookPayload,
    RouteCreate,
    RouteRecord,
    RouteUpdate,
)
from .services import deliver_due_items, normalize_hook_payload, validate_target_url


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class BrowserCacheHeadersMiddleware(BaseHTTPMiddleware):
    """避免浏览器长期缓存前台页面与 /static，本地改 JS/CSS 后无需强刷。"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            return response
        if not (path.startswith("/static/") or path in ("/", "/login", "/admin")):
            return response
        max_age = settings.static_cache_max_age
        if max_age > 0:
            response.headers["Cache-Control"] = f"public, max-age={max_age}"
        else:
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize()
    db.seed_demo_route()
    async with httpx.AsyncClient() as client:
        stop_event = asyncio.Event()

        async def worker() -> None:
            while not stop_event.is_set():
                await deliver_due_items(client)
                await asyncio.sleep(settings.delivery_poll_interval_ms / 1000)

        task = asyncio.create_task(worker())
        try:
            yield
        finally:
            stop_event.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(BrowserCacheHeadersMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/srs/hook", response_model=HookAcceptedResponse)
def ingest_hook(payload: HookPayload) -> HookAcceptedResponse:
    normalized = normalize_hook_payload(payload.model_dump())
    routes = db.get_matching_routes(
        normalized["eventType"],
        normalized.get("vhost"),
        normalized.get("app"),
        normalized.get("stream"),
    )
    event, deliveries = db.create_event_and_deliveries(normalized, routes)
    return HookAcceptedResponse(
        code=0,
        eventId=event.id,
        matchedRouteIds=[route.id for route in routes],
        queuedDeliveries=len(deliveries),
    )


@app.post("/api/admin/login", response_model=AdminLoginResponse)
def admin_login(payload: AdminLoginRequest) -> AdminLoginResponse:
    if not validate_admin_credentials(payload.username, payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AdminLoginResponse(token=settings.effective_admin_token, username=settings.admin_username)


@app.get("/api/routes", dependencies=[Depends(require_admin)])
def list_routes() -> list[dict]:
    return [route.model_dump(mode="json") for route in db.list_routes()]


@app.post("/api/routes", response_model=RouteRecord, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_route(route: RouteCreate) -> RouteRecord:
    try:
        validate_target_url(str(route.target.url))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return db.create_route(route)


@app.put("/api/routes/{route_id}", response_model=RouteRecord, dependencies=[Depends(require_admin)])
def update_route(route_id: str, route: RouteUpdate) -> RouteRecord:
    try:
        validate_target_url(str(route.target.url))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    updated = db.update_route(route_id, route)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="route not found")
    return updated


@app.delete("/api/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
def delete_route(route_id: str) -> Response:
    if not db.delete_route(route_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="route not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/events", dependencies=[Depends(require_admin)])
def list_events(limit: int = 100) -> list[dict]:
    return [event.model_dump(mode="json") for event in db.list_events(limit=limit)]


@app.get("/api/deliveries", dependencies=[Depends(require_admin)])
def list_deliveries(status: str | None = None, limit: int = 200) -> list[dict]:
    return [delivery.model_dump(mode="json") for delivery in db.list_deliveries(status=status, limit=limit)]


@app.post("/api/deliveries/{delivery_id}/retry", response_model=DeliveryRetryResponse, dependencies=[Depends(require_admin)])
def retry_delivery(delivery_id: str) -> DeliveryRetryResponse:
    if not db.retry_delivery(delivery_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery not found")
    return DeliveryRetryResponse(deliveryId=delivery_id, status="pending")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    db.initialize()
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    db.initialize()
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    snapshot = db.metrics_snapshot()
    lines = [
        "# HELP srs_gateway_routes_total Number of configured routes",
        "# TYPE srs_gateway_routes_total gauge",
        f"srs_gateway_routes_total {snapshot['routes_total']}",
        "# HELP srs_gateway_events_total Number of received SRS events",
        "# TYPE srs_gateway_events_total counter",
        f"srs_gateway_events_total {snapshot['events_total']}",
        "# HELP srs_gateway_deliveries_pending Number of queued or retrying deliveries",
        "# TYPE srs_gateway_deliveries_pending gauge",
        f"srs_gateway_deliveries_pending {snapshot['deliveries_pending']}",
        "# HELP srs_gateway_deliveries_failed Number of failed deliveries",
        "# TYPE srs_gateway_deliveries_failed gauge",
        f"srs_gateway_deliveries_failed {snapshot['deliveries_failed']}",
        "# HELP srs_gateway_deliveries_succeeded Number of successful deliveries",
        "# TYPE srs_gateway_deliveries_succeeded counter",
        f"srs_gateway_deliveries_succeeded {snapshot['deliveries_succeeded']}",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
