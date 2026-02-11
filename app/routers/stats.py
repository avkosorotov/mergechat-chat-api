"""Stats router — message counting for billing."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request

from app.auth import verify_token
from app.services import stats_service

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_token)])


@router.get("/stats/messages")
async def message_stats(
    request: Request,
    date: str | None = Query(None, description="Date in YYYY-MM-DD format (default: today UTC)"),
) -> dict:
    """Count messages for a given date, grouped by bridge.

    Returns sent/received counts per bridge for billing purposes.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return await stats_service.get_message_stats(
        pool_manager=request.app.state.pool_manager,
        bridge_registry=request.app.state.bridge_registry,
        date=date,
    )
