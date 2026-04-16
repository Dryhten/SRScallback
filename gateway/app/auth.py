from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import settings


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not settings.admin_token:
        return
    expected = f"Bearer {settings.admin_token}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
