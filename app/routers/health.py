from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    pm = request.app.state.pool_manager
    br = request.app.state.bridge_registry
    return {
        "status": "ok",
        "version": request.app.version,
        "synapse_connected": pm.synapse_pool is not None,
        "bridges": br.available_slugs,
    }
