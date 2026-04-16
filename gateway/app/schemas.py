from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


ALLOWED_EVENT_TYPES = {"on_publish", "on_unpublish", "on_play", "on_stop"}


class MatchRule(BaseModel):
    vhost: str = Field(default="*")
    app: str = Field(default="*")
    stream: str = Field(default="*")
    eventTypes: list[str] = Field(default_factory=lambda: sorted(ALLOWED_EVENT_TYPES))

    @field_validator("eventTypes")
    @classmethod
    def validate_event_types(cls, value: list[str]) -> list[str]:
        items = value or sorted(ALLOWED_EVENT_TYPES)
        invalid = sorted(set(items) - ALLOWED_EVENT_TYPES)
        if invalid:
            raise ValueError(f"unsupported event types: {', '.join(invalid)}")
        return sorted(set(items))


class TargetConfig(BaseModel):
    url: HttpUrl
    timeoutMs: int = Field(default=5000, ge=500, le=60000)
    authType: Literal["none", "bearer", "hmac_sha256"] = "none"
    authConfig: dict[str, Any] = Field(default_factory=dict)

    @field_validator("authConfig")
    @classmethod
    def validate_auth_config(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        auth_type = info.data.get("authType", "none")
        if auth_type == "bearer" and not value.get("token"):
            raise ValueError("bearer auth requires authConfig.token")
        if auth_type == "hmac_sha256" and not value.get("secret"):
            raise ValueError("hmac_sha256 auth requires authConfig.secret")
        return value


class RetryConfig(BaseModel):
    maxAttempts: int = Field(default=5, ge=1, le=20)
    backoffMs: int = Field(default=5000, ge=500, le=3600000)


class RouteBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    match: MatchRule
    target: TargetConfig
    retry: RetryConfig = Field(default_factory=RetryConfig)
    priority: int = Field(default=100, ge=0, le=10000)


class RouteCreate(RouteBase):
    pass


class RouteUpdate(RouteBase):
    pass


class RouteRecord(RouteBase):
    id: str
    createdAt: datetime
    updatedAt: datetime


class HookPayload(BaseModel):
    action: str
    client_id: str | None = None
    ip: str | None = None
    vhost: str | None = None
    app: str | None = None
    stream: str | None = None
    param: str | None = None

    model_config = {"extra": "allow"}

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        if value not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"unsupported action '{value}'")
        return value


class EventRecord(BaseModel):
    id: str
    eventType: str
    vhost: str | None
    app: str | None
    stream: str | None
    clientId: str | None
    ip: str | None
    param: str | None
    rawPayload: dict[str, Any]
    receivedAt: datetime


class DeliveryRecord(BaseModel):
    id: str
    eventId: str
    routeId: str
    routeName: str | None = None
    status: str
    attemptCount: int
    maxAttempts: int
    nextAttemptAt: datetime | None
    lastAttemptAt: datetime | None
    lastError: str | None
    responseStatus: int | None
    responseBody: str | None
    targetUrl: str
    payload: dict[str, Any]
    createdAt: datetime
    updatedAt: datetime


class DeliveryRetryResponse(BaseModel):
    deliveryId: str
    status: str


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class AdminLoginResponse(BaseModel):
    token: str
    tokenType: str = "Bearer"
    username: str


class HookAcceptedResponse(BaseModel):
    code: int = 0
    eventId: str
    matchedRouteIds: list[str]
    queuedDeliveries: int
