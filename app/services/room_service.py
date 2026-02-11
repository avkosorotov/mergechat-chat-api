"""Core business logic: merge Synapse room data with bridge portal metadata."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.bridges.base import BridgePortalInfo
from app.db import synapse as synapse_db
from app.models.filters import FilterRule
from app.models.room import ChatApiRoom, LastMessage, OrphanedRoom, OrphanedRoomsResponse, RoomListResponse

if TYPE_CHECKING:
    import asyncpg

    from app.bridges.registry import BridgeRegistry
    from app.db.pool_manager import PoolManager

logger = logging.getLogger("chat-api.rooms")

# room_type label mapping for filter fields
_FILTER_MAP = {
    "dm": "show_private",
    "group": "show_groups",
    "channel": "show_channels",
    "bot": "show_bots",
}

# System/promo messages that indicate an empty chat (no real conversation)
_SYSTEM_MESSAGE_PATTERNS = [
    "теперь в max",
    "теперь в макс",
    "now in max",
    "напишите что-нибудь",
]


def _is_system_only(room: ChatApiRoom) -> bool:
    """Check if a room has no real messages (empty or system-message only)."""
    if not room.last_message:
        return True
    body = (room.last_message.body or "").strip().lower()
    if not body:
        return True
    for pattern in _SYSTEM_MESSAGE_PATTERNS:
        if pattern in body:
            return True
    return False


async def get_rooms(
    pool_manager: PoolManager,
    bridge_registry: BridgeRegistry,
    matrix_user_id: str,
    bridge_slug: str | None = None,
    room_types: list[str] | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> RoomListResponse:
    """Fetch paginated room list with bridge metadata."""
    synapse_pool: asyncpg.Pool = pool_manager.synapse_pool

    # 1. Get joined rooms from Synapse
    joined_room_ids = await synapse_db.get_joined_rooms(synapse_pool, matrix_user_id)
    if not joined_room_ids:
        return RoomListResponse(rooms=[], total=0, page=page, page_size=page_size, has_more=False)

    # 2. Fetch bridge portal info for all rooms (parallel across bridges)
    portal_map = await _fetch_portal_map(bridge_registry, joined_room_ids)

    # 3. Filter by bridge_slug
    if bridge_slug:
        joined_room_ids = [
            rid for rid in joined_room_ids
            if rid in portal_map and portal_map[rid].bridge_slug == bridge_slug
        ]

    # 4. Filter by room_type
    if room_types:
        type_set = set(room_types)
        joined_room_ids = [
            rid for rid in joined_room_ids
            if rid in portal_map and portal_map[rid].room_type in type_set
        ]

    # 5. Fetch Synapse metadata + last messages + unread counts (parallel)
    meta_task = synapse_db.get_rooms_metadata(synapse_pool, joined_room_ids)
    msg_task = synapse_db.get_last_messages(synapse_pool, joined_room_ids)
    unread_task = synapse_db.get_unread_counts(synapse_pool, joined_room_ids, matrix_user_id)
    room_meta, last_msgs, unread_counts = await asyncio.gather(meta_task, msg_task, unread_task)

    # 5b. For small rooms without room avatar, get contact avatar (batch)
    no_avatar_ids = [
        rid for rid in joined_room_ids
        if not (room_meta.get(rid, {}).get("avatar_mxc"))
        and (room_meta.get(rid, {}).get("members_count", 0) <= 3)
    ]
    dm_avatars = await synapse_db.get_dm_avatar_urls(
        synapse_pool, no_avatar_ids, [matrix_user_id]
    ) if no_avatar_ids else {}

    # 6. Build room objects
    rooms: list[ChatApiRoom] = []
    for rid in joined_room_ids:
        meta = room_meta.get(rid, {})
        portal = portal_map.get(rid)
        msg = last_msgs.get(rid)

        name = meta.get("name") or ""
        members_count = meta.get("members_count", 0)

        # Use bridge portal display_name if Synapse name is empty or numeric
        if (not name or name.isdigit()) and portal and portal.display_name:
            name = portal.display_name

        # Fallback: for small rooms without a name (or with a numeric-only name
        # from bridges that use user IDs as room names), try contact display name
        if (not name or name.isdigit()) and members_count <= 3:
            members = await synapse_db.get_room_members_display(
                synapse_pool, rid
            )
            contacts = [m for m in members if m["user_id"] != matrix_user_id]
            for c in contacts:
                if c["display_name"] and not c["display_name"].isdigit():
                    name = c["display_name"]
                    break

        # Human-readable fallback for numeric names from bridges
        if name and name.isdigit() and portal:
            name = f"Контакт #{name}"
        elif not name:
            name = rid

        # Avatar: room avatar first, then contact avatar for DMs/bots
        avatar_mxc = meta.get("avatar_mxc") or dm_avatars.get(rid)

        # For rooms without portal info, infer bridge from puppet members
        bridge_slug = portal.bridge_slug if portal else None
        room_type = portal.room_type if portal else None
        remote_id = portal.remote_id if portal else None

        room = ChatApiRoom(
            room_id=rid,
            name=name,
            avatar_mxc=avatar_mxc,
            bridge_slug=bridge_slug,
            room_type=room_type,
            remote_id=remote_id,
            members_count=meta.get("members_count", 0),
            unread_count=unread_counts.get(rid, 0),
            can_send=True,
            last_message=LastMessage(
                sender_name=msg["sender"] if msg else None,
                body=msg["body"] if msg else "",
                timestamp=msg["timestamp"] if msg else 0,
            ) if msg else None,
            connection_user_id=matrix_user_id,
        )
        rooms.append(room)

    # 7. Hide empty / system-only chats
    rooms = [r for r in rooms if not _is_system_only(r)]

    # 8. Search filter
    if search:
        q = search.lower()
        rooms = [r for r in rooms if q in r.name.lower()]

    # 9. Sort by last message timestamp (most recent first), then by name
    rooms.sort(
        key=lambda r: (
            -(r.last_message.timestamp if r.last_message else 0),
            r.name.lower(),
        )
    )

    # 10. Paginate
    total = len(rooms)
    start = (page - 1) * page_size
    end = start + page_size
    page_rooms = rooms[start:end]

    return RoomListResponse(
        rooms=page_rooms,
        total=total,
        page=page,
        page_size=page_size,
        has_more=end < total,
    )


async def get_rooms_filtered(
    pool_manager: PoolManager,
    bridge_registry: BridgeRegistry,
    matrix_user_id: str,
    rules: list[FilterRule],
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> RoomListResponse:
    """Fetch rooms with preset-based filtering (server-side equivalent of applyFilterPreset)."""
    synapse_pool = pool_manager.synapse_pool

    # 1. Get joined rooms
    joined_room_ids = await synapse_db.get_joined_rooms(synapse_pool, matrix_user_id)
    if not joined_room_ids:
        return RoomListResponse(rooms=[], total=0, page=page, page_size=page_size, has_more=False)

    # 2. Fetch portal info
    portal_map = await _fetch_portal_map(bridge_registry, joined_room_ids)

    # 3. Build rules lookup: bridge_slug → FilterRule
    rules_map: dict[str, FilterRule] = {r.bridge_slug: r for r in rules}

    # 4. Filter rooms by preset rules
    filtered_ids: list[str] = []
    for rid in joined_room_ids:
        portal = portal_map.get(rid)
        if not portal:
            continue
        rule = rules_map.get(portal.bridge_slug)
        if not rule:
            continue
        # Check if this room_type is enabled in the rule
        filter_field = _FILTER_MAP.get(portal.room_type, "show_private")
        if getattr(rule, filter_field, True):
            filtered_ids.append(rid)

    # 5. Fetch metadata
    meta_task = synapse_db.get_rooms_metadata(synapse_pool, filtered_ids)
    msg_task = synapse_db.get_last_messages(synapse_pool, filtered_ids)
    unread_task = synapse_db.get_unread_counts(synapse_pool, filtered_ids, matrix_user_id)
    room_meta, last_msgs, unread_counts = await asyncio.gather(meta_task, msg_task, unread_task)

    # 5b. Contact avatars for small rooms without room avatar
    no_avatar_ids = [
        rid for rid in filtered_ids
        if not (room_meta.get(rid, {}).get("avatar_mxc"))
        and (room_meta.get(rid, {}).get("members_count", 0) <= 3)
    ]
    dm_avatars = await synapse_db.get_dm_avatar_urls(
        synapse_pool, no_avatar_ids, [matrix_user_id]
    ) if no_avatar_ids else {}

    # 6. Build rooms
    rooms: list[ChatApiRoom] = []
    for rid in filtered_ids:
        meta = room_meta.get(rid, {})
        portal = portal_map.get(rid)
        msg = last_msgs.get(rid)

        name = meta.get("name") or ""
        members_count = meta.get("members_count", 0)

        # Use bridge portal display_name if Synapse name is empty or numeric
        if (not name or name.isdigit()) and portal and portal.display_name:
            name = portal.display_name

        if (not name or name.isdigit()) and members_count <= 3:
            members = await synapse_db.get_room_members_display(
                synapse_pool, rid
            )
            contacts = [m for m in members if m["user_id"] != matrix_user_id]
            for c in contacts:
                if c["display_name"] and not c["display_name"].isdigit():
                    name = c["display_name"]
                    break
        if name and name.isdigit() and portal:
            name = f"Контакт #{name}"
        elif not name:
            name = rid

        avatar_mxc = meta.get("avatar_mxc") or dm_avatars.get(rid)

        room = ChatApiRoom(
            room_id=rid,
            name=name,
            avatar_mxc=avatar_mxc,
            bridge_slug=portal.bridge_slug if portal else None,
            room_type=portal.room_type if portal else None,
            remote_id=portal.remote_id if portal else None,
            members_count=members_count,
            unread_count=unread_counts.get(rid, 0),
            can_send=True,
            last_message=LastMessage(
                sender_name=msg["sender"] if msg else None,
                body=msg["body"] if msg else "",
                timestamp=msg["timestamp"] if msg else 0,
            ) if msg else None,
            connection_user_id=matrix_user_id,
        )
        rooms.append(room)

    # 7. Hide empty / system-only chats
    rooms = [r for r in rooms if not _is_system_only(r)]

    # 8. Search
    if search:
        q = search.lower()
        rooms = [r for r in rooms if q in r.name.lower()]

    # 9. Sort
    rooms.sort(
        key=lambda r: (
            -(r.last_message.timestamp if r.last_message else 0),
            r.name.lower(),
        )
    )

    # 10. Paginate
    total = len(rooms)
    start = (page - 1) * page_size
    end = start + page_size

    return RoomListResponse(
        rooms=rooms[start:end],
        total=total,
        page=page,
        page_size=page_size,
        has_more=end < total,
    )


async def get_orphaned_rooms(
    pool_manager: PoolManager,
    bridge_registry: BridgeRegistry,
    matrix_user_id: str,
) -> OrphanedRoomsResponse:
    """Find rooms where user is joined but no bridge has portal info.

    For @conn-* users, every room should have a portal entry in some bridge DB.
    Rooms without portal entries are "orphaned" — the bridge lost track of them
    (typically after a reconnect that created new portal rooms).
    """
    synapse_pool = pool_manager.synapse_pool

    # 1. Get all joined rooms
    joined_room_ids = await synapse_db.get_joined_rooms(synapse_pool, matrix_user_id)
    if not joined_room_ids:
        return OrphanedRoomsResponse(orphaned_rooms=[], total=0, total_joined=0)

    total_joined = len(joined_room_ids)

    # 2. Fetch portal info from all bridges
    portal_map = await _fetch_portal_map(bridge_registry, joined_room_ids)

    # 3. Orphaned = joined but NOT in any bridge portal
    orphaned_ids = [rid for rid in joined_room_ids if rid not in portal_map]

    if not orphaned_ids:
        return OrphanedRoomsResponse(orphaned_rooms=[], total=0, total_joined=total_joined)

    # 4. Fetch metadata for orphaned rooms
    meta_task = synapse_db.get_rooms_metadata(synapse_pool, orphaned_ids)
    msg_task = synapse_db.get_last_messages(synapse_pool, orphaned_ids)
    room_meta, last_msgs = await asyncio.gather(meta_task, msg_task)

    # 5. Build response
    orphaned: list[OrphanedRoom] = []
    for rid in orphaned_ids:
        meta = room_meta.get(rid, {})
        msg = last_msgs.get(rid)

        name = meta.get("name") or ""
        members_count = meta.get("members_count", 0)

        # Name fallback for small rooms
        if not name and members_count <= 3:
            members = await synapse_db.get_room_members_display(
                synapse_pool, rid
            )
            contacts = [m for m in members if m["user_id"] != matrix_user_id]
            if contacts:
                name = contacts[0]["display_name"]

        if not name:
            name = rid

        orphaned.append(OrphanedRoom(
            room_id=rid,
            name=name,
            members_count=members_count,
            last_activity=msg["timestamp"] if msg else 0,
        ))

    # Sort: oldest activity first (most likely to be truly orphaned)
    orphaned.sort(key=lambda r: r.last_activity)

    return OrphanedRoomsResponse(
        orphaned_rooms=orphaned,
        total=len(orphaned),
        total_joined=total_joined,
    )


async def _fetch_portal_map(
    bridge_registry: BridgeRegistry,
    room_ids: list[str],
) -> dict[str, BridgePortalInfo]:
    """Fetch portal info from all bridges in parallel.

    Returns {room_id: BridgePortalInfo}.
    """
    tasks = []
    for slug in bridge_registry.available_slugs:
        adapter = bridge_registry.get(slug)
        if adapter:
            tasks.append(adapter.get_portals(room_ids))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    portal_map: dict[str, BridgePortalInfo] = {}
    for result in results:
        if isinstance(result, Exception):
            logger.error("Bridge portal fetch failed: %s", result)
            continue
        for info in result:
            portal_map[info.room_id] = info

    return portal_map
