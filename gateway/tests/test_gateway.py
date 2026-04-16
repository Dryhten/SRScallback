from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: Path):
    db_file = tmp_path / "gateway-test.db"
    import gateway.app.config as config

    config.settings.db_path = db_file
    config.settings.admin_token = "secret-token"
    config.settings.admin_username = "admin"
    config.settings.admin_password = "mozhishijie@123"
    config.settings.seed_demo_route = False

    import gateway.app.database as database

    database.db = database.Database(db_file)
    database.db.initialize()

    import gateway.app.main as main

    main = importlib.reload(main)
    return TestClient(main.app)


def test_route_crud_and_hook_queue(tmp_path: Path):
    headers = {"Authorization": "Bearer secret-token"}

    route_payload = {
        "name": "live-forwarder",
        "enabled": True,
        "match": {
            "vhost": "__defaultVhost__",
            "app": "live",
            "stream": "*",
            "eventTypes": ["on_publish"],
        },
        "target": {
            "url": "http://127.0.0.1:18080/callback",
            "timeoutMs": 5000,
            "authType": "none",
            "authConfig": {},
        },
        "retry": {"maxAttempts": 3, "backoffMs": 1000},
        "priority": 200,
    }

    with build_client(tmp_path) as client:
        create_response = client.post("/api/routes", headers=headers, json=route_payload)
        assert create_response.status_code == 201
        route = create_response.json()
        assert route["name"] == "live-forwarder"

        hook_response = client.post(
            "/api/srs/hook",
            json={
                "action": "on_publish",
                "vhost": "__defaultVhost__",
                "app": "live",
                "stream": "room-01",
                "client_id": "1234",
                "ip": "10.0.0.10",
            },
        )
        assert hook_response.status_code == 200
        hook_body = hook_response.json()
        assert hook_body["queuedDeliveries"] == 1
        assert hook_body["matchedRouteIds"] == [route["id"]]

        deliveries_response = client.get("/api/deliveries", headers=headers)
        assert deliveries_response.status_code == 200
        deliveries = deliveries_response.json()
        assert len(deliveries) == 1
        assert deliveries[0]["status"] in {"pending", "processing", "retrying", "failed"}


def test_admin_token_is_required(tmp_path: Path):
    with build_client(tmp_path) as client:
        response = client.get("/api/routes")
        assert response.status_code == 401


def test_admin_login_returns_bearer_token(tmp_path: Path):
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "mozhishijie@123"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token"] == "secret-token"
        assert body["tokenType"] == "Bearer"
        assert body["username"] == "admin"


def test_admin_login_rejects_invalid_password(tmp_path: Path):
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/admin/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 401
