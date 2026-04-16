from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterator

from .config import settings
from .schemas import DeliveryRecord, EventRecord, RouteCreate, RouteRecord, RouteUpdate


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso_now() -> str:
    return utc_now().isoformat()


def build_downstream_payload(event_id: str, timestamp: str, normalized_event: dict[str, Any], route_id: str) -> dict[str, Any]:
    if settings.downstream_payload_mode == "extended":
        return {
            "eventId": event_id,
            "eventType": normalized_event["eventType"],
            "timestamp": timestamp,
            "matchedRouteId": route_id,
            "streamContext": {
                "vhost": normalized_event.get("vhost"),
                "app": normalized_event.get("app"),
                "stream": normalized_event.get("stream"),
            },
            "srsPayload": normalized_event["rawPayload"],
        }
    return dict(normalized_event["rawPayload"])


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS routes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    match_vhost TEXT NOT NULL,
                    match_app TEXT NOT NULL,
                    match_stream TEXT NOT NULL,
                    event_types TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    target_timeout_ms INTEGER NOT NULL,
                    target_auth_type TEXT NOT NULL,
                    target_auth_config TEXT NOT NULL,
                    retry_max_attempts INTEGER NOT NULL,
                    retry_backoff_ms INTEGER NOT NULL,
                    priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    vhost TEXT,
                    app TEXT,
                    stream TEXT,
                    client_id TEXT,
                    ip TEXT,
                    param TEXT,
                    raw_payload TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    route_id TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    next_attempt_at TEXT,
                    last_attempt_at TEXT,
                    last_error TEXT,
                    response_status INTEGER,
                    response_body TEXT,
                    target_url TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_routes_enabled_priority ON routes(enabled, priority DESC);
                CREATE INDEX IF NOT EXISTS idx_deliveries_due ON deliveries(status, next_attempt_at);
                CREATE INDEX IF NOT EXISTS idx_deliveries_event_id ON deliveries(event_id);
                """
            )

    def seed_demo_route(self) -> None:
        if not settings.seed_demo_route or self.list_routes():
            return
        demo = RouteCreate.model_validate(
            {
                "name": "demo-route",
                "enabled": True,
                "match": {
                    "vhost": "*",
                    "app": "live",
                    "stream": "*",
                    "eventTypes": ["on_publish", "on_unpublish"],
                },
                "target": {
                    "url": "http://127.0.0.1:15000/demo",
                    "timeoutMs": 5000,
                    "authType": "none",
                    "authConfig": {},
                },
                "retry": {"maxAttempts": 5, "backoffMs": 5000},
                "priority": 100,
            }
        )
        self.create_route(demo)

    def _route_from_row(self, row: sqlite3.Row) -> RouteRecord:
        return RouteRecord.model_validate(
            {
                "id": row["id"],
                "name": row["name"],
                "enabled": bool(row["enabled"]),
                "match": {
                    "vhost": row["match_vhost"],
                    "app": row["match_app"],
                    "stream": row["match_stream"],
                    "eventTypes": json.loads(row["event_types"]),
                },
                "target": {
                    "url": row["target_url"],
                    "timeoutMs": row["target_timeout_ms"],
                    "authType": row["target_auth_type"],
                    "authConfig": json.loads(row["target_auth_config"]),
                },
                "retry": {
                    "maxAttempts": row["retry_max_attempts"],
                    "backoffMs": row["retry_backoff_ms"],
                },
                "priority": row["priority"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
        )

    def list_routes(self) -> list[RouteRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM routes ORDER BY priority DESC, created_at DESC"
            ).fetchall()
        return [self._route_from_row(row) for row in rows]

    def get_route(self, route_id: str) -> RouteRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM routes WHERE id = ?", (route_id,)).fetchone()
        return self._route_from_row(row) if row else None

    def create_route(self, route: RouteCreate) -> RouteRecord:
        route_id = uuid.uuid4().hex
        timestamp = iso_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO routes (
                    id, name, enabled, match_vhost, match_app, match_stream, event_types,
                    target_url, target_timeout_ms, target_auth_type, target_auth_config,
                    retry_max_attempts, retry_backoff_ms, priority, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    route_id,
                    route.name,
                    int(route.enabled),
                    route.match.vhost,
                    route.match.app,
                    route.match.stream,
                    json.dumps(route.match.eventTypes),
                    str(route.target.url),
                    route.target.timeoutMs,
                    route.target.authType,
                    json.dumps(route.target.authConfig),
                    route.retry.maxAttempts,
                    route.retry.backoffMs,
                    route.priority,
                    timestamp,
                    timestamp,
                ),
            )
        created = self.get_route(route_id)
        assert created is not None
        return created

    def update_route(self, route_id: str, route: RouteUpdate) -> RouteRecord | None:
        timestamp = iso_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE routes
                SET name = ?, enabled = ?, match_vhost = ?, match_app = ?, match_stream = ?,
                    event_types = ?, target_url = ?, target_timeout_ms = ?, target_auth_type = ?,
                    target_auth_config = ?, retry_max_attempts = ?, retry_backoff_ms = ?,
                    priority = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    route.name,
                    int(route.enabled),
                    route.match.vhost,
                    route.match.app,
                    route.match.stream,
                    json.dumps(route.match.eventTypes),
                    str(route.target.url),
                    route.target.timeoutMs,
                    route.target.authType,
                    json.dumps(route.target.authConfig),
                    route.retry.maxAttempts,
                    route.retry.backoffMs,
                    route.priority,
                    timestamp,
                    route_id,
                ),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_route(route_id)

    def delete_route(self, route_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM routes WHERE id = ?", (route_id,))
        return cursor.rowcount > 0

    def get_matching_routes(self, event_type: str, vhost: str | None, app: str | None, stream: str | None) -> list[RouteRecord]:
        matched: list[RouteRecord] = []
        for route in self.list_routes():
            if not route.enabled:
                continue
            if event_type not in route.match.eventTypes:
                continue
            if not fnmatchcase(vhost or "", route.match.vhost):
                continue
            if not fnmatchcase(app or "", route.match.app):
                continue
            if not fnmatchcase(stream or "", route.match.stream):
                continue
            matched.append(route)
        return matched

    def create_event_and_deliveries(self, normalized_event: dict[str, Any], routes: list[RouteRecord]) -> tuple[EventRecord, list[DeliveryRecord]]:
        event_id = uuid.uuid4().hex
        timestamp = iso_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO events (
                    id, event_type, vhost, app, stream, client_id, ip, param, raw_payload, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    normalized_event["eventType"],
                    normalized_event.get("vhost"),
                    normalized_event.get("app"),
                    normalized_event.get("stream"),
                    normalized_event.get("clientId"),
                    normalized_event.get("ip"),
                    normalized_event.get("param"),
                    json.dumps(normalized_event["rawPayload"]),
                    timestamp,
                ),
            )
            for route in routes:
                delivery_id = uuid.uuid4().hex
                payload = build_downstream_payload(event_id, timestamp, normalized_event, route.id)
                connection.execute(
                    """
                    INSERT INTO deliveries (
                        id, event_id, route_id, status, attempt_count, max_attempts, next_attempt_at,
                        last_attempt_at, last_error, response_status, response_body, target_url,
                        payload, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        delivery_id,
                        event_id,
                        route.id,
                        "pending",
                        0,
                        route.retry.maxAttempts,
                        timestamp,
                        None,
                        None,
                        None,
                        None,
                        str(route.target.url),
                        json.dumps(payload),
                        timestamp,
                        timestamp,
                    ),
                )
        event = self.get_event(event_id)
        assert event is not None
        return event, self.list_deliveries(event_id=event_id)

    def get_event(self, event_id: str) -> EventRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return None
        return EventRecord.model_validate(
            {
                "id": row["id"],
                "eventType": row["event_type"],
                "vhost": row["vhost"],
                "app": row["app"],
                "stream": row["stream"],
                "clientId": row["client_id"],
                "ip": row["ip"],
                "param": row["param"],
                "rawPayload": json.loads(row["raw_payload"]),
                "receivedAt": row["received_at"],
            }
        )

    def list_events(self, limit: int = 100) -> list[EventRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events ORDER BY received_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            EventRecord.model_validate(
                {
                    "id": row["id"],
                    "eventType": row["event_type"],
                    "vhost": row["vhost"],
                    "app": row["app"],
                    "stream": row["stream"],
                    "clientId": row["client_id"],
                    "ip": row["ip"],
                    "param": row["param"],
                    "rawPayload": json.loads(row["raw_payload"]),
                    "receivedAt": row["received_at"],
                }
            )
            for row in rows
        ]

    def _delivery_from_row(self, row: sqlite3.Row) -> DeliveryRecord:
        return DeliveryRecord.model_validate(
            {
                "id": row["id"],
                "eventId": row["event_id"],
                "routeId": row["route_id"],
                "routeName": row["route_name"] if "route_name" in row.keys() else None,
                "status": row["status"],
                "attemptCount": row["attempt_count"],
                "maxAttempts": row["max_attempts"],
                "nextAttemptAt": row["next_attempt_at"],
                "lastAttemptAt": row["last_attempt_at"],
                "lastError": row["last_error"],
                "responseStatus": row["response_status"],
                "responseBody": row["response_body"],
                "targetUrl": row["target_url"],
                "payload": json.loads(row["payload"]),
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
        )

    def list_deliveries(self, *, status: str | None = None, event_id: str | None = None, limit: int = 200) -> list[DeliveryRecord]:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("d.status = ?")
            params.append(status)
        if event_id:
            clauses.append("d.event_id = ?")
            params.append(event_id)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT d.*, r.name AS route_name
                FROM deliveries d
                JOIN routes r ON r.id = d.route_id
                {where_sql}
                ORDER BY d.created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._delivery_from_row(row) for row in rows]

    def claim_due_deliveries(self, now: datetime | None = None, limit: int = 10) -> list[dict[str, Any]]:
        now = now or utc_now()
        now_iso = now.isoformat()
        claimed: list[dict[str, Any]] = []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.*, r.name AS route_name, r.target_timeout_ms, r.target_auth_type, r.target_auth_config,
                       r.retry_backoff_ms
                FROM deliveries d
                JOIN routes r ON r.id = d.route_id
                WHERE d.status IN ('pending', 'retrying')
                  AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?)
                ORDER BY d.created_at ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
            for row in rows:
                cursor = connection.execute(
                    """
                    UPDATE deliveries
                    SET status = 'processing', updated_at = ?
                    WHERE id = ? AND status IN ('pending', 'retrying')
                    """,
                    (now_iso, row["id"]),
                )
                if cursor.rowcount:
                    claimed.append(
                        {
                            "delivery": self._delivery_from_row(row),
                            "timeoutMs": row["target_timeout_ms"],
                            "authType": row["target_auth_type"],
                            "authConfig": json.loads(row["target_auth_config"]),
                            "backoffMs": row["retry_backoff_ms"],
                        }
                    )
        return claimed

    def mark_delivery_success(self, delivery_id: str, response_status: int | None, response_body: str | None) -> None:
        timestamp = iso_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE deliveries
                SET status = 'succeeded', attempt_count = attempt_count + 1,
                    last_attempt_at = ?, response_status = ?, response_body = ?,
                    last_error = NULL, next_attempt_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, response_status, response_body, timestamp, delivery_id),
            )

    def mark_delivery_failure(
        self,
        delivery_id: str,
        *,
        attempt_count: int,
        max_attempts: int,
        backoff_ms: int,
        error_message: str,
        response_status: int | None,
        response_body: str | None,
    ) -> None:
        timestamp = utc_now()
        next_attempt = timestamp + timedelta(milliseconds=backoff_ms * max(1, 2 ** max(0, attempt_count - 1)))
        terminal = attempt_count >= max_attempts
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE deliveries
                SET status = ?, attempt_count = ?, last_attempt_at = ?, last_error = ?,
                    response_status = ?, response_body = ?, next_attempt_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    "failed" if terminal else "retrying",
                    attempt_count,
                    timestamp.isoformat(),
                    error_message[:1000],
                    response_status,
                    response_body[:4000] if response_body else None,
                    None if terminal else next_attempt.isoformat(),
                    timestamp.isoformat(),
                    delivery_id,
                ),
            )

    def retry_delivery(self, delivery_id: str) -> bool:
        timestamp = iso_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE deliveries
                SET status = 'pending', next_attempt_at = ?, last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, delivery_id),
            )
        return cursor.rowcount > 0

    def metrics_snapshot(self) -> dict[str, int]:
        with self.connect() as connection:
            values = {
                "routes_total": connection.execute("SELECT COUNT(*) FROM routes").fetchone()[0],
                "events_total": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "deliveries_pending": connection.execute(
                    "SELECT COUNT(*) FROM deliveries WHERE status IN ('pending', 'retrying', 'processing')"
                ).fetchone()[0],
                "deliveries_failed": connection.execute(
                    "SELECT COUNT(*) FROM deliveries WHERE status = 'failed'"
                ).fetchone()[0],
                "deliveries_succeeded": connection.execute(
                    "SELECT COUNT(*) FROM deliveries WHERE status = 'succeeded'"
                ).fetchone()[0],
            }
        return values


db = Database(settings.db_path)
