from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReadingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    boot_id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Fa-f0-9-]+$")
    seq: int = Field(ge=0, le=2_147_483_647)
    uptime_ms: int = Field(ge=0, le=4_294_967_295)
    sent_uptime_ms: int | None = Field(default=None, ge=0, le=4_294_967_295)
    measured_at: datetime | None = None
    temperature_c: float = Field(ge=-40.0, le=85.0)
    humidity_pct: float = Field(ge=0.0, le=100.0)
    gas_raw: int | None = Field(default=None, ge=0, le=4095)
    gas_level_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    gas_source: Literal["none", "simulated", "mq2"] = "none"
    gas_warmup: bool = False
    simulated: bool = True
    mode: Literal["normal", "anomaly", "fault"] = "normal"

    @field_validator("temperature_c", "humidity_pct", "gas_level_pct")
    @classmethod
    def finite_number(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("value must be finite")
        return value

    @field_validator("measured_at")
    @classmethod
    def measurement_time_has_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("measured_at must include a timezone")
        return value

    @model_validator(mode="after")
    def gas_fields_are_consistent(self) -> "ReadingCreate":
        has_gas_values = self.gas_raw is not None or self.gas_level_pct is not None
        if self.gas_source == "none" and has_gas_values:
            raise ValueError("gas_source must be set when gas values are present")
        if self.gas_source != "none" and (
            self.gas_raw is None or self.gas_level_pct is None
        ):
            raise ValueError("gas_raw and gas_level_pct are required for a gas sensor")
        return self


class IngestResult(BaseModel):
    status: Literal["stored", "duplicate"]
    reading_id: int
    received_at: str
