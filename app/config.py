from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


@dataclass(frozen=True)
class Settings:
    database_path: Path
    expected_interval_seconds: float = 10.0
    offline_after_seconds: float = 35.0
    temperature_min_c: float = 18.0
    temperature_max_c: float = 24.0
    humidity_min_pct: float = 30.0
    humidity_max_pct: float = 60.0
    temperature_spike_c: float = 3.0
    humidity_spike_pct: float = 20.0
    spike_window_minutes: float = 15.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("ROOM_SENSOR_DB", "data/ruumiandur.sqlite")),
            expected_interval_seconds=_float_env("EXPECTED_INTERVAL_SECONDS", 10.0),
            offline_after_seconds=_float_env("OFFLINE_AFTER_SECONDS", 35.0),
            temperature_min_c=_float_env("TEMP_MIN_C", 18.0),
            temperature_max_c=_float_env("TEMP_MAX_C", 24.0),
            humidity_min_pct=_float_env("HUMIDITY_MIN_PCT", 30.0),
            humidity_max_pct=_float_env("HUMIDITY_MAX_PCT", 60.0),
            temperature_spike_c=_float_env("TEMP_SPIKE_C", 3.0),
            humidity_spike_pct=_float_env("HUMIDITY_SPIKE_PCT", 20.0),
            spike_window_minutes=_float_env("SPIKE_WINDOW_MINUTES", 15.0),
        )

