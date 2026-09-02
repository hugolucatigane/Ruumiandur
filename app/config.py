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
    temperature_min_c: float = 20.0
    temperature_max_c: float = 25.0
    humidity_min_pct: float = 40.0
    humidity_max_pct: float = 60.0
    temperature_spike_c: float = 3.0
    humidity_spike_pct: float = 20.0
    gas_warning_pct: float = 70.0
    gas_spike_pct: float = 20.0
    spike_window_minutes: float = 15.0
    summary_min_coverage_ratio: float = 0.8
    sensor_stuck_window_minutes: float = 120.0
    sensor_stuck_min_coverage_ratio: float = 0.8
    temperature_stuck_tolerance_c: float = 0.05
    humidity_stuck_tolerance_pct: float = 0.05
    gas_stuck_tolerance_pct: float = 0.05

    def __post_init__(self) -> None:
        if self.expected_interval_seconds <= 0.0:
            raise ValueError("expected_interval_seconds must be greater than 0")
        if not 0.0 < self.summary_min_coverage_ratio <= 1.0:
            raise ValueError("summary_min_coverage_ratio must be greater than 0 and at most 1")
        if self.sensor_stuck_window_minutes <= 0.0:
            raise ValueError("sensor_stuck_window_minutes must be greater than 0")
        if not 0.0 < self.sensor_stuck_min_coverage_ratio <= 1.0:
            raise ValueError(
                "sensor_stuck_min_coverage_ratio must be greater than 0 and at most 1"
            )
        if min(
            self.temperature_stuck_tolerance_c,
            self.humidity_stuck_tolerance_pct,
            self.gas_stuck_tolerance_pct,
        ) < 0.0:
            raise ValueError("sensor stuck tolerances must not be negative")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.getenv("ROOM_SENSOR_DB", "data/ruumiandur.sqlite")),
            expected_interval_seconds=_float_env("EXPECTED_INTERVAL_SECONDS", 10.0),
            offline_after_seconds=_float_env("OFFLINE_AFTER_SECONDS", 35.0),
            temperature_min_c=_float_env("TEMP_MIN_C", 20.0),
            temperature_max_c=_float_env("TEMP_MAX_C", 25.0),
            humidity_min_pct=_float_env("HUMIDITY_MIN_PCT", 40.0),
            humidity_max_pct=_float_env("HUMIDITY_MAX_PCT", 60.0),
            temperature_spike_c=_float_env("TEMP_SPIKE_C", 3.0),
            humidity_spike_pct=_float_env("HUMIDITY_SPIKE_PCT", 20.0),
            gas_warning_pct=_float_env("GAS_WARNING_PCT", 70.0),
            gas_spike_pct=_float_env("GAS_SPIKE_PCT", 20.0),
            spike_window_minutes=_float_env("SPIKE_WINDOW_MINUTES", 15.0),
            summary_min_coverage_ratio=_float_env("SUMMARY_MIN_COVERAGE_RATIO", 0.8),
            sensor_stuck_window_minutes=_float_env(
                "SENSOR_STUCK_WINDOW_MINUTES", 120.0
            ),
            sensor_stuck_min_coverage_ratio=_float_env(
                "SENSOR_STUCK_MIN_COVERAGE_RATIO", 0.8
            ),
            temperature_stuck_tolerance_c=_float_env(
                "TEMP_STUCK_TOLERANCE_C", 0.05
            ),
            humidity_stuck_tolerance_pct=_float_env(
                "HUMIDITY_STUCK_TOLERANCE_PCT", 0.05
            ),
            gas_stuck_tolerance_pct=_float_env(
                "GAS_STUCK_TOLERANCE_PCT", 0.05
            ),
        )
