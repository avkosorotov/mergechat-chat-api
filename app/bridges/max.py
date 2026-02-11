"""Adapter for mautrix-max bridge database."""

from __future__ import annotations

import asyncpg

from app.bridges.base import BridgeAdapter, BridgePortalInfo, RoomType


class MaxAdapter(BridgeAdapter):
    slug = "max"

    async def get_portals(
        self,
        room_ids: list[str],
    ) -> list[BridgePortalInfo]:
        rows = await self.pool.fetch(
            """
            SELECT
                p.mxid AS room_id,
                p.max_chat_id::text AS remote_id,
                p.name AS portal_name
            FROM portal p
            WHERE p.mxid = ANY($1)
            """,
            room_ids,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"],
                remote_id=r["remote_id"],
                room_type="dm",
                bridge_slug=self.slug,
                display_name=r["portal_name"] if r["portal_name"] and not r["portal_name"].isdigit() else None,
            )
            for r in rows
        ]

    async def get_user_portals(
        self,
        matrix_user_id: str,
    ) -> list[BridgePortalInfo]:
        """Get all portals visible to a specific matrix user.

        mautrix-max portals are shared (not scoped per user like telegram),
        so we return all portals where the user exists in the user table.
        """
        rows = await self.pool.fetch(
            """
            SELECT
                p.mxid AS room_id,
                p.max_chat_id::text AS remote_id
            FROM portal p
            WHERE p.mxid IS NOT NULL
              AND EXISTS (SELECT 1 FROM "user" u WHERE u.mxid = $1)
            """,
            matrix_user_id,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"],
                remote_id=r["remote_id"],
                room_type="dm",
                bridge_slug=self.slug,
            )
            for r in rows
        ]
