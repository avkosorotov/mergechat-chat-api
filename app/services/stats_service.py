"""Message counting stats — aggregate by bridge from Synapse events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.db import synapse as synapse_db

if TYPE_CHECKING:
    from app.bridges.registry import BridgeRegistry
    from app.db.pool_manager import PoolManager

logger = logging.getLogger("chat-api.stats")


async def get_message_stats(
    pool_manager: PoolManager,
    bridge_registry: BridgeRegistry,
    date: str,  # "YYYY-MM-DD"
) -> dict:
    """Count messages for given date, grouped by bridge.

    Classification:
    - sender LIKE '@conn-%' → sent (user sent through MergeChat)
    - everything else → received (from remote messenger)

    Returns:
    {
        "date": "2026-02-11",
        "bridges": [{"bridge": "telegram", "sent": 42, "received": 156}, ...],
        "total_sent": 52,
        "total_received": 186,
    }
    """
    # Parse date to timestamp range (UTC day boundaries in ms)
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ts = int(day.timestamp() * 1000)
    end_ts = start_ts + 86400 * 1000  # +24h

    synapse_pool = pool_manager.synapse_pool
    if not synapse_pool:
        return {"date": date, "bridges": [], "total_sent": 0, "total_received": 0}

    # 1. Count messages grouped by room_id + sender
    counts = await synapse_db.count_messages_by_room_sender(synapse_pool, start_ts, end_ts)
    if not counts:
        return {"date": date, "bridges": [], "total_sent": 0, "total_received": 0}

    # 2. Collect unique room_ids
    room_ids = list({c["room_id"] for c in counts})

    # 3. Resolve room_id → bridge_slug via bridge adapters
    room_to_bridge: dict[str, str] = {}
    for slug, adapter in bridge_registry.adapters.items():
        try:
            portals = await adapter.get_portals(room_ids)
            for p in portals:
                room_to_bridge[p.room_id] = slug
        except Exception:
            logger.exception("Failed to query portals for bridge %s", slug)

    # 4. Classify sent/received per bridge
    bridge_stats: dict[str, dict[str, int]] = {}  # {slug: {sent, received}}

    for c in counts:
        bridge_slug = room_to_bridge.get(c["room_id"])
        if not bridge_slug:
            continue  # unknown room (not in any bridge portal table)

        if bridge_slug not in bridge_stats:
            bridge_stats[bridge_slug] = {"sent": 0, "received": 0}

        # @conn-* senders = messages sent by user through MergeChat
        if c["sender"].startswith("@conn-"):
            bridge_stats[bridge_slug]["sent"] += c["cnt"]
        else:
            bridge_stats[bridge_slug]["received"] += c["cnt"]

    # 5. Build response
    bridges = [
        {"bridge": slug, "sent": stats["sent"], "received": stats["received"]}
        for slug, stats in sorted(bridge_stats.items())
    ]
    total_sent = sum(b["sent"] for b in bridges)
    total_received = sum(b["received"] for b in bridges)

    return {
        "date": date,
        "bridges": bridges,
        "total_sent": total_sent,
        "total_received": total_received,
    }
