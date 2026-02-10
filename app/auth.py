from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.config import AppConfig


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def verify_token(request: Request, config: AppConfig = Depends(get_config)) -> str:
    """Verify Bearer token matches shared_secret. Returns the token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth[7:]
    if token != config.shared_secret:
        raise HTTPException(status_code=403, detail="Invalid token")
    return token
