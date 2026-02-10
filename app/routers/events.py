from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import StreamingResponse

from app.auth import verify_token
from app.services import event_service

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_token)])


@router.get("/rooms/{room_id}/events")
async def stream_room_events(
    request: Request,
    room_id: str,
    matrix_user_id: str = Query(..., description="Matrix user ID, e.g. @conn-xxx:domain"),
    since: int = Query(0, description="stream_ordering cursor to resume from"),
) -> StreamingResponse:
    return StreamingResponse(
        event_service.stream_room_events(
            request=request,
            pool_manager=request.app.state.pool_manager,
            room_id=room_id,
            matrix_user_id=matrix_user_id,
            since=since,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
