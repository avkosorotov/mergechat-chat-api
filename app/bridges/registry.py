"""Bridge adapter registry — auto-discovers adapters from config."""

from __future__ import annotations

import logging

from app.bridges.base import BridgeAdapter
from app.bridges.max import MaxAdapter
from app.bridges.telegram import TelegramAdapter
from app.bridges.whatsapp import WhatsAppAdapter
from app.db.pool_manager import PoolManager

logger = logging.getLogger("chat-api.bridges")

# Map slug → adapter class
ADAPTER_CLASSES: dict[str, type[BridgeAdapter]] = {
    "telegram": TelegramAdapter,
    "whatsapp": WhatsAppAdapter,
    "max": MaxAdapter,
}


class BridgeRegistry:
    def __init__(self) -> None:
        self.adapters: dict[str, BridgeAdapter] = {}

    def init(self, pool_manager: PoolManager) -> None:
        for slug in pool_manager.available_bridges:
            adapter_cls = ADAPTER_CLASSES.get(slug)
            pool = pool_manager.get_bridge_pool(slug)
            if adapter_cls and pool:
                self.adapters[slug] = adapter_cls(pool)
                logger.info("Registered bridge adapter: %s", slug)
            else:
                logger.warning(
                    "No adapter class for bridge '%s' — rooms will show without type info",
                    slug,
                )

    def get(self, slug: str) -> BridgeAdapter | None:
        return self.adapters.get(slug)

    @property
    def available_slugs(self) -> list[str]:
        return list(self.adapters.keys())
