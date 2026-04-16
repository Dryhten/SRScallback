from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import settings
from .database import db


def normalize_hook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "eventType": payload["action"],
        "vhost": payload.get("vhost") or "__defaultVhost__",
        "app": payload.get("app"),
        "stream": payload.get("stream"),
        "clientId": payload.get("client_id"),
        "ip": payload.get("ip"),
        "param": payload.get("param"),
        "rawPayload": payload,
    }


def validate_target_url(target_url: str) -> None:
    parsed = urlparse(target_url)
    host = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("target.url must use http or https")
    if settings.allowed_target_hosts:
        if not any(host == allowed or host.endswith(f".{allowed}") for allowed in settings.allowed_target_hosts):
            raise ValueError("target host is not in the allowed host list")
    if not settings.allow_private_targets and host in {"127.0.0.1", "localhost"}:
        raise ValueError("private target addresses are not allowed")


def build_delivery_headers(auth_type: str, auth_config: dict[str, Any], body: bytes) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {auth_config['token']}"
    elif auth_type == "hmac_sha256":
        secret = auth_config["secret"].encode("utf-8")
        digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
        header_name = auth_config.get("header", "X-Signature")
        headers[header_name] = digest
    return headers


async def deliver_due_items(client: httpx.AsyncClient) -> int:
    processed = 0
    claims = db.claim_due_deliveries(limit=10)
    for claim in claims:
        processed += 1
        delivery = claim["delivery"]
        payload_bytes = json.dumps(delivery.payload).encode("utf-8")
        headers = build_delivery_headers(claim["authType"], claim["authConfig"], payload_bytes)
        try:
            response = await client.post(
                delivery.targetUrl,
                content=payload_bytes,
                headers=headers,
                timeout=claim["timeoutMs"] / 1000,
            )
            response_body = response.text[:4000]
            if 200 <= response.status_code < 300:
                db.mark_delivery_success(delivery.id, response.status_code, response_body)
                continue
            db.mark_delivery_failure(
                delivery.id,
                attempt_count=delivery.attemptCount + 1,
                max_attempts=delivery.maxAttempts,
                backoff_ms=claim["backoffMs"],
                error_message=f"downstream returned {response.status_code}",
                response_status=response.status_code,
                response_body=response_body,
            )
        except Exception as exc:
            db.mark_delivery_failure(
                delivery.id,
                attempt_count=delivery.attemptCount + 1,
                max_attempts=delivery.maxAttempts,
                backoff_ms=claim["backoffMs"],
                error_message=str(exc),
                response_status=None,
                response_body=None,
            )
    return processed
