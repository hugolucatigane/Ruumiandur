from __future__ import annotations

from datetime import datetime, timezone
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

    return {
        "state": state,
        "message": message,
        "last_valid_at": latest_reading["received_at"] if latest_reading else None,
        "last_message_at": message_time.isoformat(timespec="milliseconds") if message_time else None,
        "seconds_since_valid": round((now - valid_time).total_seconds(), 1) if valid_time else None,
        "rejected_last_24h": rejected_last_24h,
        "expected_interval_seconds": settings.expected_interval_seconds,
        "offline_after_seconds": settings.offline_after_seconds,
        "thresholds": _thresholds(settings),
    }


def analyse_readings(
    readings_descending: list[dict[str, Any]],
    status: dict[str, Any],
    requested_hours: float,
    settings: Settings,
) -> dict[str, Any]:
    readings = sorted(readings_descending, key=lambda row: row["received_at"])
    if not readings:
        return {
            "room": None,
            "requested_hours": requested_hours,
            "sample_count": 0,
            "period_start": None,
            "period_end": None,
            "coverage_minutes": 0.0,
            "statistics": None,
            "anomalies": [],
            "device_status": status,
            "thresholds": _thresholds(settings),
        }

    temperatures = [float(row["temperature_c"]) for row in readings]
    humidities = [float(row["humidity_pct"]) for row in readings]
    first_time = parse_time(readings[0]["received_at"])
    last_time = parse_time(readings[-1]["received_at"])
    coverage_minutes = max(0.0, (last_time - first_time).total_seconds() / 60.0)
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
    }
    anomalies: list[dict[str, Any]] = []
    _add_range_anomalies(anomalies, readings, statistics, settings)
    _add_change_anomalies(anomalies, readings, settings)
    _add_gap_anomaly(anomalies, readings, settings)

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    anomalies.sort(key=lambda event: (severity_order[event["severity"]], event.get("at") or ""))
    return {
        "room": readings[-1]["room"],
        "requested_hours": requested_hours,
        "sample_count": len(readings),
        "period_start": readings[0]["received_at"],
        "period_end": readings[-1]["received_at"],
        "coverage_minutes": round(coverage_minutes, 1),
        "statistics": statistics,
        "anomalies": anomalies[:6],
        "device_status": status,
        "thresholds": _thresholds(settings),
    }


def _thresholds(settings: Settings) -> dict[str, Any]:
    return {
        "temperature_c": [settings.temperature_min_c, settings.temperature_max_c],
        "humidity_pct": [settings.humidity_min_pct, settings.humidity_max_pct],
        "temperature_change_c": settings.temperature_spike_c,
        "humidity_change_pct": settings.humidity_spike_pct,
        "change_window_minutes": settings.spike_window_minutes,
        "data_gap_seconds": settings.expected_interval_seconds * 3,
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


def _event(code: str, severity: str, row: dict[str, Any], value: float, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "at": row["received_at"],
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
    max_window_seconds = settings.spike_window_minutes * 60

    for previous, current in zip(readings, readings[1:]):
        elapsed = (parse_time(current["received_at"]) - parse_time(previous["received_at"])).total_seconds()
        if elapsed <= 0 or elapsed > max_window_seconds:
            continue
        temp_change = abs(float(current["temperature_c"]) - float(previous["temperature_c"]))
        humidity_change = abs(float(current["humidity_pct"]) - float(previous["humidity_pct"]))
        if temp_change >= settings.temperature_spike_c and (largest_temp_change is None or temp_change > largest_temp_change[0]):
            largest_temp_change = temp_change, current
        if humidity_change >= settings.humidity_spike_pct and (largest_humidity_change is None or humidity_change > largest_humidity_change[0]):
            largest_humidity_change = humidity_change, current

    if largest_temp_change:
        change, row = largest_temp_change
        anomalies.append(_event("temperature_rapid_change", "warning", row, change, f"Temperatuur muutus lühikese ajaga {change:.1f} °C."))
    if largest_humidity_change:
        change, row = largest_humidity_change
        anomalies.append(_event("humidity_rapid_change", "warning", row, change, f"Õhuniiskus muutus lühikese ajaga {change:.1f} protsendipunkti."))


def _add_gap_anomaly(
    anomalies: list[dict[str, Any]],
    readings: list[dict[str, Any]],
    settings: Settings,
) -> None:
    largest_gap = 0.0
    gap_row: dict[str, Any] | None = None
    for previous, current in zip(readings, readings[1:]):
        gap = (parse_time(current["received_at"]) - parse_time(previous["received_at"])).total_seconds()
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

    stats = report["statistics"]
    room = report["room"] or "Ruumis"
    first = (
        f"{room}: {report['sample_count']} mõõtmise põhjal oli keskmine temperatuur "
        f"{stats['temperature_c']['average']:.1f} °C ja õhuniiskus "
        f"{stats['humidity_pct']['average']:.1f}%."
    )
    if report["anomalies"]:
        second = " ".join(event["message"] for event in report["anomalies"][:2])
    else:
        second = "Seadistatud piiride järgi ebatavalisi väärtusi ei olnud."
    if status["state"] in {"offline", "degraded"}:
        second = f"{second} {status['message']}"
    return f"{first} {second}"
