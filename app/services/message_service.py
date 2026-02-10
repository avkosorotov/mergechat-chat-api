"""Business logic: fetch messages with sender profiles."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.db import synapse as synapse_db
from app.models.message import InvitesResponse, MessageItem, MessagesResponse, ReactionInfo

if TYPE_CHECKING:
    from app.db.pool_manager import PoolManager

logger = logging.getLogger("chat-api.messages")


async def get_messages(
    pool_manager: PoolManager,
    room_id: str,
    limit: int = 50,
    before: int | None = None,
    after: int | None = None,
) -> MessagesResponse:
    """Fetch paginated messages with sender display names and avatars."""
    synapse_pool = pool_manager.synapse_pool

    messages, min_stream, max_stream = await synapse_db.get_room_messages(
        synapse_pool,
        room_id,
        limit=limit,
        before_stream_ordering=before,
        after_stream_ordering=after,
    )

    if not messages:
        return MessagesResponse(
            messages=[],
            room_id=room_id,
            has_more=False,
            before_cursor=None,
            after_cursor=after,  # Keep the after cursor for continued polling
        )

    # Fetch sender profiles, reactions, and edits in batch
    sender_ids = list({m["sender"] for m in messages})
    event_ids = [m["event_id"] for m in messages]

    profiles = await synapse_db.get_sender_profiles(synapse_pool, room_id, sender_ids)
    reactions_map = await synapse_db.get_reactions_for_messages(synapse_pool, room_id, event_ids)
    edits_map = await synapse_db.get_edits_for_messages(synapse_pool, room_id, event_ids)

    # Build response items
    items: list[MessageItem] = []
    for msg in messages:
        profile = profiles.get(msg["sender"], {})
        event_id = msg["event_id"]

        # Apply edit if exists
        edit = edits_map.get(event_id)
        body = edit["edited_body"] if edit else msg["body"]
        is_edited = edit is not None

        # Build reactions list
        msg_reactions = [
            ReactionInfo(key=r["key"], count=r["count"], senders=r["senders"])
            for r in reactions_map.get(event_id, [])
        ]

        items.append(MessageItem(
            event_id=event_id,
            sender=msg["sender"],
            sender_name=profile.get("display_name", msg["sender"]),
            sender_avatar=profile.get("avatar_url"),
            timestamp=msg["timestamp"],
            stream_ordering=msg["stream_ordering"],
            msgtype=msg["msgtype"],
            body=body,
            media_url=msg["media_url"],
            thumbnail_url=msg["thumbnail_url"],
            file_name=msg["file_name"],
            file_size=msg["file_size"],
            reply_to_event_id=msg["reply_to_event_id"],
            reactions=msg_reactions,
            is_edited=is_edited,
        ))

    return MessagesResponse(
        messages=items,
        room_id=room_id,
        has_more=len(messages) == limit,
        before_cursor=min_stream,
        after_cursor=max_stream,
    )


async def get_invites(
    pool_manager: PoolManager,
    matrix_user_id: str,
) -> InvitesResponse:
    """Get pending room invites for a matrix user."""
    synapse_pool = pool_manager.synapse_pool
    invites = await synapse_db.get_room_invites(synapse_pool, matrix_user_id)
    return InvitesResponse(invites=invites, total=len(invites))
