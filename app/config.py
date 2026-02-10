from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class BridgeConfig:
    slug: str
    framework: str  # "python" | "go"
    dsn: str


@dataclass
class AppConfig:
    shared_secret: str
    homeserver_url: str
    homeserver_domain: str
    synapse_dsn: str
    bridges: list[BridgeConfig] = field(default_factory=list)

    @classmethod
    def load(cls, path: str = "/app/config.yaml") -> AppConfig:
        p = Path(path)
        if not p.exists():
            # Fallback for local dev
            p = Path(__file__).parent.parent / "config.yaml"
        with open(p) as f:
            raw = yaml.safe_load(f)
        bridges = [
            BridgeConfig(slug=b["slug"], framework=b["framework"], dsn=b["dsn"])
            for b in raw.get("bridges", [])
        ]
        return cls(
            shared_secret=raw["shared_secret"],
            homeserver_url=raw["homeserver_url"],
            homeserver_domain=raw["homeserver_domain"],
            synapse_dsn=raw["synapse_dsn"],
            bridges=bridges,
        )
