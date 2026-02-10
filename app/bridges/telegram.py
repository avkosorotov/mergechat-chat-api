"""Adapter for mautrix-telegram bridge database."""

from __future__ import annotations

import asyncpg

from app.bridges.base import BridgeAdapter, BridgePortalInfo, RoomType


def _resolve_type(peer_type: str, megagroup: bool, is_bot: bool) -> RoomType:
    if peer_type == "user":
        return "bot" if is_bot else "dm"
    if peer_type == "chat":
        return "group"
    if peer_type == "channel":
        return "group" if megagroup else "channel"
    return "dm"


class TelegramAdapter(BridgeAdapter):
    slug = "telegram"

    async def get_portals(
        self,
        room_ids: list[str],
    ) -> list[BridgePortalInfo]:
        rows = await self.pool.fetch(
            """
            SELECT
                p.mxid AS room_id,
                p.tgid::text AS remote_id,
                p.peer_type,
                p.megagroup,
                COALESCE(pu.is_bot, false) AS is_bot
            FROM portal p
            LEFT JOIN puppet pu ON p.peer_type = 'user' AND pu.id = p.tgid
            WHERE p.mxid = ANY($1)
            """,
            room_ids,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"],
                remote_id=r["remote_id"],
                room_type=_resolve_type(r["peer_type"], r["megagroup"], r["is_bot"]),
                bridge_slug=self.slug,
            )
            for r in rows
        ]

    async def get_user_portals(
        self,
        matrix_user_id: str,
    ) -> list[BridgePortalInfo]:
        """Get all portals visible to a specific matrix user.

        mautrix-telegram stores:
        - DM portals: portal.tg_receiver = user.tgid (private chats scoped per user)
        - Group/channel portals: user_portal table links user to group portals
        """
        rows = await self.pool.fetch(
            """
            WITH tg_user AS (
                SELECT tgid FROM "user" WHERE mxid = $1
            )
            -- DM portals (scoped by tg_receiver)
            SELECT
                p.mxid AS room_id,
                p.tgid::text AS remote_id,
                p.peer_type,
                p.megagroup,
                COALESCE(pu.is_bot, false) AS is_bot
            FROM portal p
            CROSS JOIN tg_user tu
            LEFT JOIN puppet pu ON p.peer_type = 'user' AND pu.id = p.tgid
            WHERE p.peer_type = 'user'
              AND p.tg_receiver = tu.tgid
              AND p.mxid IS NOT NULL

            UNION ALL

            -- Group/channel portals (via user_portal)
            SELECT
                p.mxid AS room_id,
                p.tgid::text AS remote_id,
                p.peer_type,
                p.megagroup,
                false AS is_bot
            FROM user_portal up
            JOIN "user" u ON u.tgid = up.user
            JOIN portal p ON p.tgid = up.portal AND p.tg_receiver = up.portal_receiver
            WHERE u.mxid = $1
              AND p.mxid IS NOT NULL
            """,
            matrix_user_id,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"],
                remote_id=r["remote_id"],
                room_type=_resolve_type(r["peer_type"], r["megagroup"], r["is_bot"]),
                bridge_slug=self.slug,
            )
            for r in rows
        ]
