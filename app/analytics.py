from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import fmean
from typing import Any

from .config import Settings


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _round(value: float) -> float:
    return round(value, 1)


def build_device_status(
    latest_reading: dict[str, Any] | None,
    latest_event: dict[str, Any] | None,
    latest_invalid: dict[str, Any] | None,
    rejected_last_24h: int,
    settings: Settings,
    now: datetime | None = None,
    recent_readings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    valid_time = parse_time(latest_reading["received_at"]) if latest_reading else None
    event_time = parse_time(latest_event["received_at"]) if latest_event else None
    message_time = max((value for value in (valid_time, event_time) if value), default=None)

    if message_time is None:
        state = "unknown"
        message = "Andurilt pole veel ühtegi sõnumit saabunud."
    else:
        seconds_since_message = max(0.0, (now - message_time).total_seconds())
        valid_is_fresh = valid_time is not None and (now - valid_time).total_seconds() <= settings.offline_after_seconds
        if seconds_since_message > settings.offline_after_seconds:
            state = "offline"
            message = f"Andur vaikib: viimasest sõnumist on {round(seconds_since_message)} sekundit."
        elif not valid_is_fresh:
            state = "degraded"
            message = "Andur saadab sõnumeid, kuid värsket kehtivat mõõtmist pole."
        elif latest_invalid and parse_time(latest_invalid["received_at"]) > valid_time:
            state = "degraded"
            message = "Viimane sõnum oli vigane; näidatakse viimast kehtivat mõõtmist."
        else:
            state = "online"
            message = "Andur saadab kehtivaid mõõtmisi."

    messages = [message]
    sensor_warnings = detect_stuck_sensors(recent_readings or [], settings, now)
    if sensor_warnings and state not in {"offline", "unknown"}:
        if state == "online":
            state = "degraded"
            messages = []
        messages.extend(warning["message"] for warning in sensor_warnings)
        message = " ".join(messages)

    return {
        "state": state,
        "message": message,
        "messages": messages,
        "sensor_warnings": sensor_warnings,
        "last_valid_at": latest_reading["received_at"] if latest_reading else None,
        "last_message_at": message_time.isoformat(timespec="milliseconds") if message_time else None,
        "seconds_since_valid": round((now - valid_time).total_seconds(), 1) if valid_time else None,
        "rejected_last_24h": rejected_last_24h,
        "expected_interval_seconds": settings.expected_interval_seconds,
        "offline_after_seconds": settings.offline_after_seconds,
        "thresholds": _thresholds(settings),
    }


def detect_stuck_sensors(
    readings_descending: list[dict[str, Any]],
    settings: Settings,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return warnings for channels that stayed effectively flat for a full window."""
    now = now or datetime.now(timezone.utc)
    window_seconds = settings.sensor_stuck_window_minutes * 60.0
    window_start = now - timedelta(seconds=window_seconds)
    readings = sorted(
        (
            row
            for row in readings_descending
            if window_start <= parse_time(row["measured_at"]) <= now
        ),
        key=lambda row: row["measured_at"],
    )
    if not readings:
        return []

    interval_seconds = settings.expected_interval_seconds
    expected_samples = max(1, ceil(window_seconds / interval_seconds))
    required_samples = ceil(
        expected_samples * settings.sensor_stuck_min_coverage_ratio
    )
    observed_span_seconds = (
        parse_time(readings[-1]["measured_at"])
        - parse_time(readings[0]["measured_at"])
    ).total_seconds() + interval_seconds
    minimum_span_seconds = max(0.0, window_seconds - 2 * interval_seconds)
    latest_age_seconds = (
        now - parse_time(readings[-1]["measured_at"])
    ).total_seconds()
    freshness_limit = max(
        settings.offline_after_seconds,
        settings.expected_interval_seconds * 3,
    )
    if (
        len(readings) < required_samples
        or observed_span_seconds < minimum_span_seconds
        or latest_age_seconds > freshness_limit
    ):
        return []

    channels = (
        (
            "temperature_stuck",
            "temperature_c",
            "Temperatuurinäit",
            settings.temperature_stuck_tolerance_c,
            "°C",
        ),
        (
            "humidity_stuck",
            "humidity_pct",
            "Õhuniiskuse näit",
            settings.humidity_stuck_tolerance_pct,
            "%",
        ),
        (
            "gas_stuck",
            "gas_level_pct",
            "MQ-2 suhteline gaasitase",
            settings.gas_stuck_tolerance_pct,
            "%",
        ),
    )
    warnings: list[dict[str, Any]] = []
    for code, field, label, tolerance, unit in channels:
        if field == "gas_level_pct" and readings[-1].get("gas_warmup", False):
            continue
        channel_rows = [
            row
            for row in readings
            if row.get(field) is not None
            and not (field == "gas_level_pct" and row.get("gas_warmup", False))
        ]
        if len(channel_rows) < required_samples:
            continue
        values = [float(row[field]) for row in channel_rows]
        minimum = min(values)
        maximum = max(values)
        spread = maximum - minimum
        if spread > tolerance:
            continue
        message = (
            f"{label} on vähemalt {settings.sensor_stuck_window_minutes:g} minuti jooksul "
            f"püsinud praktiliselt muutumatuna ({minimum:.2f}–{maximum:.2f} {unit}); "
            "andur võib olla kinni jäänud."
        )
        warnings.append(
            {
                "code": code,
                "severity": "warning",
                "at": channel_rows[-1]["measured_at"],
                "value": _round(values[-1]),
                "spread": round(spread, 3),
                "sample_count": len(channel_rows),
                "window_minutes": settings.sensor_stuck_window_minutes,
                "message": message,
            }
        )
    return warnings


def analyse_readings(
    readings_descending: list[dict[str, Any]],
    status: dict[str, Any],
    requested_hours: float,
    settings: Settings,
) -> dict[str, Any]:
    readings = sorted(readings_descending, key=lambda row: row["measured_at"])
    coverage = _coverage_metrics(readings, requested_hours, settings)
    if not readings:
        return {
            "requested_hours": requested_hours,
            "sample_count": 0,
            "period_start": None,
            "period_end": None,
            **coverage,
            "statistics": None,
            "anomalies": [],
            "device_status": status,
            "thresholds": _thresholds(settings),
        }

    temperatures = [float(row["temperature_c"]) for row in readings]
    humidities = [float(row["humidity_pct"]) for row in readings]
    gas_rows = [
        row
        for row in readings
        if row.get("gas_level_pct") is not None and not row.get("gas_warmup", False)
    ]
    gas_levels = [float(row["gas_level_pct"]) for row in gas_rows]
    statistics = {
        "temperature_c": {
            "average": _round(fmean(temperatures)),
            "minimum": _round(min(temperatures)),
            "maximum": _round(max(temperatures)),
        },
        "humidity_pct": {
            "average": _round(fmean(humidities)),
            "minimum": _round(min(humidities)),
            "maximum": _round(max(humidities)),
        },
        "gas_level_pct": None,
    }
    if gas_levels:
        statistics["gas_level_pct"] = {
            "average": _round(fmean(gas_levels)),
            "minimum": _round(min(gas_levels)),
            "maximum": _round(max(gas_levels)),
            "sample_count": len(gas_levels),
        }
    anomalies: list[dict[str, Any]] = []
    _add_range_anomalies(anomalies, readings, statistics, settings)
    _add_change_anomalies(anomalies, readings, settings)
    _add_gap_anomaly(anomalies, readings, settings)
    anomalies.extend(status.get("sensor_warnings", []))

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    anomalies.sort(
        key=lambda event: (
            severity_order[event["severity"]],
            0 if event["code"].endswith("_stuck") else 1,
            event.get("at") or "",
        )
    )
    return {
        "requested_hours": requested_hours,
        "sample_count": len(readings),
        "period_start": readings[0]["measured_at"],
        "period_end": readings[-1]["measured_at"],
        **coverage,
        "statistics": statistics,
        "anomalies": anomalies[:6],
        "device_status": status,
        "thresholds": _thresholds(settings),
    }


def _coverage_metrics(
    readings: list[dict[str, Any]],
    requested_hours: float,
    settings: Settings,
) -> dict[str, Any]:
    requested_seconds = requested_hours * 60 * 60
    interval_seconds = settings.expected_interval_seconds
    expected_sample_count = max(1, ceil(requested_seconds / interval_seconds))

    if readings:
        first_time = parse_time(readings[0]["measured_at"])
        last_time = parse_time(readings[-1]["measured_at"])
        observed_span_seconds = max(
            0.0,
            (last_time - first_time).total_seconds() + interval_seconds,
        )
    else:
        observed_span_seconds = 0.0

    sample_coverage_seconds = len(readings) * interval_seconds
    coverage_seconds = min(
        requested_seconds,
        observed_span_seconds,
        sample_coverage_seconds,
    )
    coverage_ratio = coverage_seconds / requested_seconds
    return {
        "expected_sample_count": expected_sample_count,
        "coverage_seconds": round(coverage_seconds, 1),
        "coverage_minutes": round(coverage_seconds / 60.0, 1),
        "coverage_ratio": round(coverage_ratio, 4),
        "coverage_percent": round(coverage_ratio * 100.0, 1),
        "coverage_sufficient": coverage_ratio >= settings.summary_min_coverage_ratio,
        "minimum_coverage_percent": round(settings.summary_min_coverage_ratio * 100.0, 1),
    }


def _thresholds(settings: Settings) -> dict[str, Any]:
    return {
        "temperature_c": [settings.temperature_min_c, settings.temperature_max_c],
        "humidity_pct": [settings.humidity_min_pct, settings.humidity_max_pct],
        "gas_level_pct": [0.0, settings.gas_warning_pct],
        "temperature_change_c": settings.temperature_spike_c,
        "humidity_change_pct": settings.humidity_spike_pct,
        "gas_change_pct": settings.gas_spike_pct,
        "change_window_minutes": settings.spike_window_minutes,
        "data_gap_seconds": settings.expected_interval_seconds * 3,
        "sensor_stuck": {
            "window_minutes": settings.sensor_stuck_window_minutes,
            "minimum_coverage_ratio": settings.sensor_stuck_min_coverage_ratio,
            "temperature_tolerance_c": settings.temperature_stuck_tolerance_c,
            "humidity_tolerance_pct": settings.humidity_stuck_tolerance_pct,
            "gas_tolerance_pct": settings.gas_stuck_tolerance_pct,
        },
        "source": "configurable prototype product rules; AI does not set thresholds",
    }


def _add_range_anomalies(
    anomalies: list[dict[str, Any]],
    readings: list[dict[str, Any]],
    statistics: dict[str, Any],
    settings: Settings,
) -> None:
    temp = statistics["temperature_c"]
    humidity = statistics["humidity_pct"]
    gas = statistics.get("gas_level_pct")
    highest_temp = max(readings, key=lambda row: row["temperature_c"])
    lowest_temp = min(readings, key=lambda row: row["temperature_c"])
    highest_humidity = max(readings, key=lambda row: row["humidity_pct"])
    lowest_humidity = min(readings, key=lambda row: row["humidity_pct"])

    if temp["average"] > settings.temperature_max_c:
        anomalies.append(_event("temperature_average_high", "warning", readings[-1], temp["average"], f"Keskmine temperatuur {temp['average']:.1f} °C ületas seadistatud {settings.temperature_max_c:.1f} °C piiri."))
    elif temp["maximum"] > settings.temperature_max_c:
        anomalies.append(_event("temperature_peak_high", "warning", highest_temp, temp["maximum"], f"Temperatuur tõusis väärtuseni {temp['maximum']:.1f} °C."))
    if temp["average"] < settings.temperature_min_c:
        anomalies.append(_event("temperature_average_low", "warning", readings[-1], temp["average"], f"Keskmine temperatuur {temp['average']:.1f} °C jäi alla seadistatud {settings.temperature_min_c:.1f} °C piiri."))
    elif temp["minimum"] < settings.temperature_min_c:
        anomalies.append(_event("temperature_peak_low", "warning", lowest_temp, temp["minimum"], f"Temperatuur langes väärtuseni {temp['minimum']:.1f} °C."))

    if humidity["average"] > settings.humidity_max_pct:
        anomalies.append(_event("humidity_average_high", "warning", readings[-1], humidity["average"], f"Keskmine õhuniiskus {humidity['average']:.1f}% ületas seadistatud {settings.humidity_max_pct:.1f}% piiri."))
    elif humidity["maximum"] > settings.humidity_max_pct:
        anomalies.append(_event("humidity_peak_high", "warning", highest_humidity, humidity["maximum"], f"Õhuniiskus tõusis väärtuseni {humidity['maximum']:.1f}%."))
    if humidity["average"] < settings.humidity_min_pct:
        anomalies.append(_event("humidity_average_low", "warning", readings[-1], humidity["average"], f"Keskmine õhuniiskus {humidity['average']:.1f}% jäi alla seadistatud {settings.humidity_min_pct:.1f}% piiri."))
    elif humidity["minimum"] < settings.humidity_min_pct:
        anomalies.append(_event("humidity_peak_low", "warning", lowest_humidity, humidity["minimum"], f"Õhuniiskus langes väärtuseni {humidity['minimum']:.1f}%."))

    if gas:
        valid_gas_rows = [
            row
            for row in readings
            if row.get("gas_level_pct") is not None and not row.get("gas_warmup", False)
        ]
        highest_gas = max(valid_gas_rows, key=lambda row: row["gas_level_pct"])
        if gas["average"] > settings.gas_warning_pct:
            anomalies.append(
                _event(
                    "gas_average_high",
                    "warning",
                    readings[-1],
                    gas["average"],
                    f"MQ-2 suhteline gaasitase {gas['average']:.1f}% ületas seadistatud {settings.gas_warning_pct:.1f}% piiri.",
                )
            )
        elif gas["maximum"] > settings.gas_warning_pct:
            anomalies.append(
                _event(
                    "gas_peak_high",
                    "warning",
                    highest_gas,
                    gas["maximum"],
                    f"MQ-2 suhteline gaasitase tõusis väärtuseni {gas['maximum']:.1f}%.",
                )
            )


def _event(code: str, severity: str, row: dict[str, Any], value: float, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "at": row["measured_at"],
        "value": _round(float(value)),
        "message": message,
    }


def _add_change_anomalies(
    anomalies: list[dict[str, Any]],
    readings: list[dict[str, Any]],
    settings: Settings,
) -> None:
    largest_temp_change: tuple[float, dict[str, Any]] | None = None
    largest_humidity_change: tuple[float, dict[str, Any]] | None = None
    largest_gas_change: tuple[float, dict[str, Any]] | None = None
    max_window_seconds = settings.spike_window_minutes * 60

    for previous, current in zip(readings, readings[1:]):
        elapsed = (parse_time(current["measured_at"]) - parse_time(previous["measured_at"])).total_seconds()
        if elapsed <= 0 or elapsed > max_window_seconds:
            continue
        temp_change = abs(float(current["temperature_c"]) - float(previous["temperature_c"]))
        humidity_change = abs(float(current["humidity_pct"]) - float(previous["humidity_pct"]))
        if temp_change >= settings.temperature_spike_c and (largest_temp_change is None or temp_change > largest_temp_change[0]):
            largest_temp_change = temp_change, current
        if humidity_change >= settings.humidity_spike_pct and (largest_humidity_change is None or humidity_change > largest_humidity_change[0]):
            largest_humidity_change = humidity_change, current
        previous_gas = previous.get("gas_level_pct")
        current_gas = current.get("gas_level_pct")
        if (
            previous_gas is not None
            and current_gas is not None
            and not previous.get("gas_warmup", False)
            and not current.get("gas_warmup", False)
        ):
            gas_change = abs(float(current_gas) - float(previous_gas))
            if gas_change >= settings.gas_spike_pct and (
                largest_gas_change is None or gas_change > largest_gas_change[0]
            ):
                largest_gas_change = gas_change, current

    if largest_temp_change:
        change, row = largest_temp_change
        anomalies.append(_event("temperature_rapid_change", "warning", row, change, f"Temperatuur muutus lühikese ajaga {change:.1f} °C."))
    if largest_humidity_change:
        change, row = largest_humidity_change
        anomalies.append(_event("humidity_rapid_change", "warning", row, change, f"Õhuniiskus muutus lühikese ajaga {change:.1f} protsendipunkti."))
    if largest_gas_change:
        change, row = largest_gas_change
        anomalies.append(_event("gas_rapid_change", "warning", row, change, f"MQ-2 suhteline gaasitase muutus lühikese ajaga {change:.1f} protsendipunkti."))


def _add_gap_anomaly(
    anomalies: list[dict[str, Any]],
    readings: list[dict[str, Any]],
    settings: Settings,
) -> None:
    largest_gap = 0.0
    gap_row: dict[str, Any] | None = None
    for previous, current in zip(readings, readings[1:]):
        gap = (parse_time(current["measured_at"]) - parse_time(previous["measured_at"])).total_seconds()
        if gap > largest_gap:
            largest_gap = gap
            gap_row = current
    threshold = settings.expected_interval_seconds * 3
    if gap_row and largest_gap > threshold:
        anomalies.append(_event("data_gap", "info", gap_row, largest_gap, f"Mõõtmistes oli {round(largest_gap)} sekundi pikkune andmelünk."))


def fallback_summary(report: dict[str, Any]) -> str:
    status = report["device_status"]
    if report["sample_count"] == 0:
        return f"Valitud perioodi kohta pole kehtivaid mõõtmisi. {status['message']}"

    if not report["coverage_sufficient"]:
        requested_hours = f"{report['requested_hours']:g}"
        first = (
            f"{requested_hours} tunni kokkuvõtte jaoks pole piisavalt andmeid: "
            f"saabus {report['sample_count']} mõõtmist, oodati ligikaudu "
            f"{report['expected_sample_count']} ({report['coverage_percent']:.1f}% katvus; "
            f"nõutud vähemalt {report['minimum_coverage_percent']:.1f}%)."
        )
        if report["anomalies"]:
            second = "Olemasolevates andmetes tuvastati: " + " ".join(
                event["message"] for event in _selected_anomalies(report["anomalies"])
            )
        else:
            second = (
                "Olemasolevates andmetes ebatavalisi väärtusi ei tuvastatud, "
                "kuid kogu perioodi kohta ei saa järeldust teha."
            )
        second = _append_status_messages(second, status)
        return f"{first} {second}"

    stats = report["statistics"]
    first = (
        f"Valitud perioodil oli {report['sample_count']} mõõtmise põhjal keskmine temperatuur "
        f"{stats['temperature_c']['average']:.1f} °C ja õhuniiskus "
        f"{stats['humidity_pct']['average']:.1f}%."
    )
    gas = stats.get("gas_level_pct")
    if gas:
        first += f" MQ-2 suhteline gaasitase oli keskmiselt {gas['average']:.1f}%."
    if report["anomalies"]:
        second = " ".join(
            event["message"] for event in _selected_anomalies(report["anomalies"])
        )
    else:
        second = "Seadistatud piiride järgi ebatavalisi väärtusi ei olnud."
    second = _append_status_messages(second, status)
    return f"{first} {second}"


def _append_status_messages(text: str, status: dict[str, Any]) -> str:
    if status["state"] not in {"offline", "degraded"}:
        return text
    messages = status.get("messages") or [status["message"]]
    for message in messages:
        if message and message not in text:
            text = f"{text} {message}"
    return text


def _selected_anomalies(anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_measurements: set[str] = set()
    for event in anomalies:
        measurement = event["code"].split("_", 1)[0]
        if measurement in seen_measurements:
            continue
        selected.append(event)
        seen_measurements.add(measurement)
        if len(selected) == 3:
            break
    return selected
