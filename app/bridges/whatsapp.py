"""Adapter for mautrix-whatsapp bridge database (Go-based, different schema)."""

from __future__ import annotations

import asyncpg

from app.bridges.base import BridgeAdapter, BridgePortalInfo, RoomType


def _resolve_type_mega(chat_id: str, room_type: str) -> RoomType:
    """Determine room type from megabridge schema fields.

    Uses room_type column if available, falls back to JID patterns.
    """
    if room_type == "group" or room_type == "community":
        return "group"
    if room_type == "channel" or room_type == "newsletter" or room_type == "broadcast":
        return "channel"
    if room_type == "dm" or room_type == "":
        # Check JID patterns as fallback
        if "@g.us" in chat_id:
            return "group"
        if "@newsletter" in chat_id or "@broadcast" in chat_id:
            return "channel"
        return "dm"
    return "dm"


class WhatsAppAdapter(BridgeAdapter):
    slug = "whatsapp"

    async def get_portals(
        self,
        room_ids: list[str],
    ) -> list[BridgePortalInfo]:
        # mautrix-whatsapp megabridge schema (v0.11+):
        # portal table: id, receiver, mxid, room_type, other_user_id, ...
        rows = await self.pool.fetch(
            """
            SELECT
                p.mxid AS room_id,
                p.id AS remote_id,
                COALESCE(p.room_type, '') AS room_type
            FROM portal p
            WHERE p.mxid = ANY($1)
            """,
            room_ids,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"],
                remote_id=r["remote_id"],
                room_type=_resolve_type_mega(r["remote_id"], r["room_type"]),
                bridge_slug=self.slug,
            )
            for r in rows
        ]

    async def get_user_portals(
        self,
        matrix_user_id: str,
    ) -> list[BridgePortalInfo]:
        """Get all portals visible to a specific matrix user."""
        rows = await self.pool.fetch(
            """
            SELECT
                p.mxid AS room_id,
                p.id AS remote_id,
                COALESCE(p.room_type, '') AS room_type
            FROM portal p
            WHERE p.mxid IS NOT NULL
              AND (
                  p.receiver = (SELECT id FROM "user" WHERE mxid = $1 LIMIT 1)
                  OR p.receiver = ''
              )
            """,
            matrix_user_id,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"],
                remote_id=r["remote_id"],
                room_type=_resolve_type_mega(r["remote_id"], r["room_type"]),
                bridge_slug=self.slug,
            )
            for r in rows
        ]
