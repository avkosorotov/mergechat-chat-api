from __future__ import annotations

from pydantic import BaseModel


class FilterRule(BaseModel):
    bridge_slug: str
    show_private: bool = True
    show_groups: bool = True
    show_channels: bool = True
    show_bots: bool = True


class FilterRequest(BaseModel):
    matrix_user_id: str
    rules: list[FilterRule]
    search: str | None = None
    page: int = 1
    page_size: int = 50
