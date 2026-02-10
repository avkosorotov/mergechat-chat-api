from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.auth import verify_token
from app.models.filters import FilterRequest
from app.models.room import OrphanedRoomsResponse, RoomListResponse
from app.services import room_service

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_token)])


@router.get("/rooms", response_model=RoomListResponse)
async def list_rooms(
    request: Request,
    matrix_user_id: str = Query(..., description="Matrix user ID, e.g. @conn-xxx:domain"),
    bridge_slug: str | None = Query(None, description="Filter by bridge slug"),
    type: str | None = Query(None, description="Comma-separated room types: dm,group,channel,bot"),
    search: str | None = Query(None, description="Search rooms by name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> RoomListResponse:
    room_types = [t.strip() for t in type.split(",")] if type else None

    return await room_service.get_rooms(
        pool_manager=request.app.state.pool_manager,
        bridge_registry=request.app.state.bridge_registry,
        matrix_user_id=matrix_user_id,
        bridge_slug=bridge_slug,
        room_types=room_types,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/rooms/orphaned", response_model=OrphanedRoomsResponse)
async def list_orphaned_rooms(
    request: Request,
    matrix_user_id: str = Query(..., description="Matrix user ID, e.g. @conn-xxx:domain"),
) -> OrphanedRoomsResponse:
    """Find rooms where user is joined but no bridge has portal info."""
    return await room_service.get_orphaned_rooms(
        pool_manager=request.app.state.pool_manager,
        bridge_registry=request.app.state.bridge_registry,
        matrix_user_id=matrix_user_id,
    )


@router.post("/rooms/filter", response_model=RoomListResponse)
async def filter_rooms(
    request: Request,
    body: FilterRequest,
) -> RoomListResponse:
    return await room_service.get_rooms_filtered(
        pool_manager=request.app.state.pool_manager,
        bridge_registry=request.app.state.bridge_registry,
        matrix_user_id=body.matrix_user_id,
        rules=body.rules,
        search=body.search,
        page=body.page,
        page_size=body.page_size,
    )
