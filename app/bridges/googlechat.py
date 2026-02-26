"""Adapter for mautrix-googlechat bridge database (Python, legacy schema with gcid)."""

from __future__ import annotations

from app.bridges.base import BridgeAdapter, BridgePortalInfo, RoomType


def _resolve_type(gcid: str, other_user_id: str | None) -> RoomType:
    if other_user_id:
        return "dm"
    # Google Chat spaces are typically groups
    return "group"


class GoogleChatAdapter(BridgeAdapter):
    slug = "googlechat"

    async def get_portals(self, room_ids: list[str]) -> list[BridgePortalInfo]:
        rows = await self.pool.fetch(
            """
            SELECT p.mxid AS room_id, p.gcid AS remote_id,
                   p.other_user_id, p.name AS display_name
            FROM portal p WHERE p.mxid = ANY($1)
            """,
            room_ids,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"], remote_id=r["remote_id"],
                room_type=_resolve_type(r["remote_id"], r["other_user_id"]),
                bridge_slug=self.slug, display_name=r["display_name"],
            )
            for r in rows
        ]

    async def get_user_portals(self, matrix_user_id: str) -> list[BridgePortalInfo]:
        rows = await self.pool.fetch(
            """
            SELECT p.mxid AS room_id, p.gcid AS remote_id,
                   p.other_user_id, p.name AS display_name
            FROM portal p
            WHERE p.mxid IS NOT NULL
              AND (p.gc_receiver = '' OR p.gc_receiver = $1)
            """,
            matrix_user_id,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"], remote_id=r["remote_id"],
                room_type=_resolve_type(r["remote_id"], r["other_user_id"]),
                bridge_slug=self.slug, display_name=r["display_name"],
            )
            for r in rows
        ]
