from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "srs-callback-gateway")
    db_path: Path = Path(os.getenv("DB_PATH", "/data/gateway.db"))
    delivery_poll_interval_ms: int = int(os.getenv("DELIVERY_POLL_INTERVAL_MS", "1500"))
    http_timeout_ms: int = int(os.getenv("DEFAULT_TARGET_TIMEOUT_MS", "5000"))
    downstream_payload_mode: str = os.getenv("DOWNSTREAM_PAYLOAD_MODE", "raw").lower()
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "mozhishijie@123")
    allowed_target_hosts: list[str] = None  # type: ignore[assignment]
    allow_private_targets: bool = os.getenv("ALLOW_PRIVATE_TARGETS", "true").lower() == "true"
    seed_demo_route: bool = os.getenv("SEED_DEMO_ROUTE", "false").lower() == "true"

    def __post_init__(self) -> None:
        self.allowed_target_hosts = _split_csv(os.getenv("ALLOWED_TARGET_HOSTS", ""))
        if self.downstream_payload_mode not in {"raw", "extended"}:
            self.downstream_payload_mode = "raw"
        if not self.db_path.is_absolute():
            self.db_path = Path.cwd() / self.db_path

    @property
    def admin_auth_enabled(self) -> bool:
        return bool(self.admin_token or self.admin_password)

    @property
    def effective_admin_token(self) -> str:
        if self.admin_token:
            return self.admin_token
        seed = f"{self.app_name}:{self.admin_username}:{self.admin_password}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()


settings = Settings()
