from __future__ import annotations

from pydantic import BaseModel


class LastMessage(BaseModel):
    sender_name: str | None = None
    body: str = ""
    timestamp: int = 0


class ChatApiRoom(BaseModel):
    room_id: str
    name: str
    avatar_mxc: str | None = None
    bridge_slug: str | None = None
    room_type: str | None = None  # dm, group, channel, bot
    remote_id: str | None = None
    members_count: int = 0
    unread_count: int = 0
    can_send: bool = True
    last_message: LastMessage | None = None
    connection_user_id: str | None = None


class RoomListResponse(BaseModel):
    rooms: list[ChatApiRoom]
    total: int
    page: int
    page_size: int
    has_more: bool


class OrphanedRoom(BaseModel):
    room_id: str
    name: str
    members_count: int = 0
    last_activity: int = 0  # origin_server_ts of last message


class OrphanedRoomsResponse(BaseModel):
    orphaned_rooms: list[OrphanedRoom]
    total: int
    total_joined: int  # total rooms user is joined to (for context)
