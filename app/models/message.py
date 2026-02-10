from __future__ import annotations

from pydantic import BaseModel


class ReactionInfo(BaseModel):
    key: str          # emoji, e.g. "👍"
    count: int
    senders: list[str]  # sender MXIDs


class MessageItem(BaseModel):
    event_id: str
    sender: str
    sender_name: str
    sender_avatar: str | None = None  # mxc:// URL
    timestamp: int  # origin_server_ts (ms)
    stream_ordering: int  # pagination token
    msgtype: str = "m.text"  # m.text, m.image, m.file, m.video, m.audio
    body: str = ""
    media_url: str | None = None  # mxc:// URL
    thumbnail_url: str | None = None  # mxc:// URL
    file_name: str | None = None
    file_size: int | None = None
    reply_to_event_id: str | None = None
    reactions: list[ReactionInfo] = []
    is_edited: bool = False


class MessagesResponse(BaseModel):
    messages: list[MessageItem]
    room_id: str
    has_more: bool  # True if limit results were returned
    before_cursor: int | None  # min stream_ordering (for loading older)
    after_cursor: int | None  # max stream_ordering (for polling new)


class InvitesResponse(BaseModel):
    invites: list[str]
    total: int
