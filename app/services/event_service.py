"""Business logic: SSE event streaming for real-time chat updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, AsyncGenerator

from app.db import synapse as synapse_db
from app.models.message import MessageItem, ReactionInfo

if TYPE_CHECKING:
    from starlette.requests import Request

    from app.db.pool_manager import PoolManager

logger = logging.getLogger("chat-api.events")

# How often to poll Synapse DB for new events (seconds)
POLL_INTERVAL = 1.0
# How often to send SSE heartbeat comment (seconds)
HEARTBEAT_INTERVAL = 15.0


async def stream_room_events(
    request: Request,
    pool_manager: PoolManager,
    room_id: str,
    matrix_user_id: str,
    since: int,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a room, polling Synapse DB every second.

    Event types:
    - message: new message in the room
    - reaction: new reaction on an existing message
    - edit: message content was edited
    - redact: message was deleted/redacted
    - (comment): heartbeat to keep connection alive
    """
    synapse_pool = pool_manager.synapse_pool
    last_stream = since
    last_heartbeat = time.monotonic()

    logger.info(
        "SSE stream started: room=%s user=%s since=%d",
        room_id, matrix_user_id, since,
    )

    try:
        while True:
            if await request.is_disconnected():
                break

            events_found = False

            # 1. New messages
            new_messages = await synapse_db.get_new_events(
                synapse_pool, room_id, last_stream
            )
            if new_messages:
                events_found = True
                sender_ids = list({m["sender"] for m in new_messages})
                event_ids = [m["event_id"] for m in new_messages]

                profiles = await synapse_db.get_sender_profiles(
                    synapse_pool, room_id, sender_ids
                )
                reactions_map = await synapse_db.get_reactions_for_messages(
                    synapse_pool, room_id, event_ids
                )
                edits_map = await synapse_db.get_edits_for_messages(
                    synapse_pool, room_id, event_ids
                )

                for msg in new_messages:
                    profile = profiles.get(msg["sender"], {})
                    event_id = msg["event_id"]
                    edit = edits_map.get(event_id)
                    body = edit["edited_body"] if edit else msg["body"]
                    is_edited = edit is not None

                    msg_reactions = [
                        ReactionInfo(
                            key=r["key"], count=r["count"], senders=r["senders"]
                        )
                        for r in reactions_map.get(event_id, [])
                    ]

                    item = MessageItem(
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
                    )

                    yield f"event: message\ndata: {item.model_dump_json()}\n\n"
                    last_stream = max(last_stream, msg["stream_ordering"])

            # 2. New reactions
            new_reactions = await synapse_db.get_new_reactions(
                synapse_pool, room_id, last_stream
            )
            if new_reactions:
                events_found = True
                for reaction in new_reactions:
                    yield (
                        f"event: reaction\n"
                        f"data: {json.dumps(reaction)}\n\n"
                    )
                    last_stream = max(last_stream, reaction["stream_ordering"])

            # 3. Edits
            new_edits = await synapse_db.get_new_edits(
                synapse_pool, room_id, last_stream
            )
            if new_edits:
                events_found = True
                for edit in new_edits:
                    yield (
                        f"event: edit\n"
                        f"data: {json.dumps(edit)}\n\n"
                    )
                    last_stream = max(last_stream, edit["stream_ordering"])

            # 4. Redactions
            new_redactions = await synapse_db.get_new_redactions(
                synapse_pool, room_id, last_stream
            )
            if new_redactions:
                events_found = True
                for redaction in new_redactions:
                    yield (
                        f"event: redact\n"
                        f"data: {json.dumps(redaction)}\n\n"
                    )
                    last_stream = max(last_stream, redaction["stream_ordering"])

            # Heartbeat
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                yield f": heartbeat {int(time.time())}\n\n"
                last_heartbeat = now

            # Adaptive sleep: if events were found, poll sooner
            if events_found:
                await asyncio.sleep(0.3)
            else:
                await asyncio.sleep(POLL_INTERVAL)

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled: room=%s user=%s", room_id, matrix_user_id)
    except Exception:
        logger.exception("SSE stream error: room=%s user=%s", room_id, matrix_user_id)
    finally:
        logger.info("SSE stream ended: room=%s user=%s", room_id, matrix_user_id)
