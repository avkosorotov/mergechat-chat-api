"""Abstract base class for bridge database adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

import asyncpg

RoomType = Literal["dm", "group", "channel", "bot"]


class BridgePortalInfo:
    """Metadata about a portal (chat) from the bridge DB."""

    __slots__ = ("room_id", "remote_id", "room_type", "bridge_slug")

    def __init__(
        self,
        room_id: str,
        remote_id: str,
        room_type: RoomType,
        bridge_slug: str,
    ) -> None:
        self.room_id = room_id
        self.remote_id = remote_id
        self.room_type = room_type
        self.bridge_slug = bridge_slug


class BridgeAdapter(ABC):
    """Base class for reading portal metadata from a bridge DB."""

    slug: str

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @abstractmethod
    async def get_portals(
        self,
        room_ids: list[str],
    ) -> list[BridgePortalInfo]:
        """Return portal info for rooms that belong to this bridge."""
        ...

    @abstractmethod
    async def get_user_portals(
        self,
        matrix_user_id: str,
    ) -> list[BridgePortalInfo]:
        """Return all portals visible to a specific matrix user."""
        ...
