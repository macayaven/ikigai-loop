"""Shared base for all core schemas: frozen, extra fields forbidden."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Tier = Literal["public", "private", "sensitive"]
Dimension = Literal["love", "good_at", "world_needs", "paid_for", "limit", "contrast"]


class SchemaModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)
