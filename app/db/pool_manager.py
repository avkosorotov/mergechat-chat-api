"""Manages asyncpg connection pools for Synapse and bridge databases."""

from __future__ import annotations

import logging

import asyncpg

from app.config import AppConfig, BridgeConfig

logger = logging.getLogger("chat-api.pool")


class PoolManager:
    def __init__(self) -> None:
        self.synapse_pool: asyncpg.Pool | None = None
        self.bridge_pools: dict[str, asyncpg.Pool] = {}
        self._bridge_configs: dict[str, BridgeConfig] = {}

    async def init(self, config: AppConfig) -> None:
        logger.info("Connecting to Synapse DB...")
        self.synapse_pool = await asyncpg.create_pool(
            config.synapse_dsn, min_size=2, max_size=10
        )
        logger.info("Synapse DB pool ready")

        for bc in config.bridges:
            self._bridge_configs[bc.slug] = bc
            try:
                pool = await asyncpg.create_pool(bc.dsn, min_size=1, max_size=5)
                self.bridge_pools[bc.slug] = pool
                logger.info("Bridge DB pool ready: %s", bc.slug)
            except Exception:
                logger.exception("Failed to connect to bridge DB: %s", bc.slug)

    async def close(self) -> None:
        if self.synapse_pool:
            await self.synapse_pool.close()
        for slug, pool in self.bridge_pools.items():
            await pool.close()
            logger.info("Closed bridge pool: %s", slug)

    def get_bridge_pool(self, slug: str) -> asyncpg.Pool | None:
        return self.bridge_pools.get(slug)

    def get_bridge_config(self, slug: str) -> BridgeConfig | None:
        return self._bridge_configs.get(slug)

    @property
    def available_bridges(self) -> list[str]:
        return list(self.bridge_pools.keys())
