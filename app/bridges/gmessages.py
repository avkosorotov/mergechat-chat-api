"""Adapter for Go-based megabridge databases (gmessages, facebook, instagram, twitter, gvoice).

All these bridges share the same portal schema: id, receiver, mxid, room_type, name.
"""

from __future__ import annotations

from app.bridges.base import BridgeAdapter, BridgePortalInfo, RoomType


def _resolve_type(room_type: str) -> RoomType:
    if room_type in ("group", "community"):
        return "group"
    if room_type in ("channel", "broadcast", "newsletter"):
        return "channel"
    return "dm"


class _MegabridgeAdapter(BridgeAdapter):
    """Base adapter for Go megabridge schema (portal with id, mxid, room_type, name)."""

    async def get_portals(self, room_ids: list[str]) -> list[BridgePortalInfo]:
        rows = await self.pool.fetch(
            """
            SELECT p.mxid AS room_id, p.id AS remote_id,
                   COALESCE(p.room_type, '') AS room_type, p.name AS display_name
            FROM portal p WHERE p.mxid = ANY($1)
            """,
            room_ids,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"], remote_id=r["remote_id"],
                room_type=_resolve_type(r["room_type"]),
                bridge_slug=self.slug, display_name=r["display_name"],
            )
            for r in rows
        ]

    async def get_user_portals(self, matrix_user_id: str) -> list[BridgePortalInfo]:
        rows = await self.pool.fetch(
            """
            SELECT p.mxid AS room_id, p.id AS remote_id,
                   COALESCE(p.room_type, '') AS room_type, p.name AS display_name
            FROM portal p
            WHERE p.mxid IS NOT NULL
              AND (p.receiver = (SELECT id FROM "user" WHERE mxid = $1 LIMIT 1) OR p.receiver = '')
            """,
            matrix_user_id,
        )
        return [
            BridgePortalInfo(
                room_id=r["room_id"], remote_id=r["remote_id"],
                room_type=_resolve_type(r["room_type"]),
                bridge_slug=self.slug, display_name=r["display_name"],
            )
            for r in rows
        ]


class GMessagesAdapter(_MegabridgeAdapter):
    slug = "gmessages"


class FacebookAdapter(_MegabridgeAdapter):
    slug = "facebook"


class InstagramAdapter(_MegabridgeAdapter):
    slug = "instagram"


class TwitterAdapter(_MegabridgeAdapter):
    slug = "twitter"


class GVoiceAdapter(_MegabridgeAdapter):
    slug = "gvoice"
