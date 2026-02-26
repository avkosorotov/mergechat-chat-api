"""Adapter for mautrix-discord bridge database (Go, legacy schema with dcid/type)."""

from __future__ import annotations

from app.bridges.base import BridgeAdapter, BridgePortalInfo, RoomType


def _resolve_type(dc_type: int | None) -> RoomType:
    # Discord channel types: 0=guild_text, 1=dm, 2=guild_voice, 3=group_dm, ...
    if dc_type == 1:
        return "dm"
    if dc_type == 3:
        return "group"
    return "channel"


class DiscordAdapter(BridgeAdapter):
    slug = "discord"

    async def get_portals(self, room_ids: list[str]) -> list[BridgePortalInfo]:
        rows = await self.pool.fetch(
            """
            SELECT p.mxid AS room_id, p.dcid AS remote_id,
                   p.type AS dc_type, p.plain_name AS display_name
            FROM portal p WHERE p.mxid = ANY($1)
            """,
            room_ids,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"], remote_id=r["remote_id"],
                room_type=_resolve_type(r["dc_type"]),
                bridge_slug=self.slug, display_name=r["display_name"],
            )
            for r in rows
        ]

    async def get_user_portals(self, matrix_user_id: str) -> list[BridgePortalInfo]:
        rows = await self.pool.fetch(
            """
            SELECT p.mxid AS room_id, p.dcid AS remote_id,
                   p.type AS dc_type, p.plain_name AS display_name
            FROM portal p
            WHERE p.mxid IS NOT NULL
              AND (p.receiver = '' OR p.receiver = $1)
            """,
            matrix_user_id,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"], remote_id=r["remote_id"],
                room_type=_resolve_type(r["dc_type"]),
                bridge_slug=self.slug, display_name=r["display_name"],
            )
            for r in rows
        ]
