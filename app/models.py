from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReadingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    boot_id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Fa-f0-9-]+$")
    room: str = Field(min_length=1, max_length=80)
    seq: int = Field(ge=0, le=2_147_483_647)
    uptime_ms: int = Field(ge=0, le=4_294_967_295)
    temperature_c: float = Field(ge=-40.0, le=85.0)
    humidity_pct: float = Field(ge=0.0, le=100.0)
    simulated: bool = True
    mode: Literal["normal", "anomaly", "fault"] = "normal"

    @field_validator("temperature_c", "humidity_pct")
    @classmethod
    def finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        return value


class IngestResult(BaseModel):
    status: Literal["stored", "duplicate"]
    reading_id: int
    received_at: str

