from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import settings


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not settings.admin_auth_enabled:
        return
    expected = f"Bearer {settings.effective_admin_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )


def validate_admin_credentials(username: str, password: str) -> bool:
    if not settings.admin_auth_enabled:
        return True
    return username == settings.admin_username and password == settings.admin_password
