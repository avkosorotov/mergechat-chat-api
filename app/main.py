"""MergeChat Chat API — FastAPI service for room listing with bridge metadata."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.bridges.registry import BridgeRegistry
from app.config import AppConfig
from app.db.pool_manager import PoolManager
from app.routers import health, messages, rooms

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("chat-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Chat API...")
    config = AppConfig.load()
    app.state.config = config

    pool_manager = PoolManager()
    await pool_manager.init(config)
    app.state.pool_manager = pool_manager

    bridge_registry = BridgeRegistry()
    bridge_registry.init(pool_manager)
    app.state.bridge_registry = bridge_registry

    logger.info(
        "Chat API ready — bridges: %s",
        ", ".join(bridge_registry.available_slugs) or "none",
    )

    yield

    # Shutdown
    logger.info("Shutting down Chat API...")
    await pool_manager.close()


app = FastAPI(
    title="MergeChat Chat API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(rooms.router)
app.include_router(messages.router)
