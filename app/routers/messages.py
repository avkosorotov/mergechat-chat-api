from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.auth import verify_token
from app.models.message import InvitesResponse, MessagesResponse
from app.services import message_service

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_token)])


@router.get("/rooms/{room_id}/messages", response_model=MessagesResponse)
async def get_room_messages(
    request: Request,
    room_id: str,
    matrix_user_id: str = Query(..., description="Matrix user ID, e.g. @conn-xxx:domain"),
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None, description="Load older: stream_ordering < this value"),
    after: int | None = Query(None, description="Poll newer: stream_ordering > this value"),
) -> MessagesResponse:
    return await message_service.get_messages(
        pool_manager=request.app.state.pool_manager,
        room_id=room_id,
        limit=limit,
        before=before,
        after=after,
    )


@router.get("/invites", response_model=InvitesResponse)
async def get_invites(
    request: Request,
    matrix_user_id: str = Query(..., description="Matrix user ID"),
) -> InvitesResponse:
    return await message_service.get_invites(
        pool_manager=request.app.state.pool_manager,
        matrix_user_id=matrix_user_id,
    )
