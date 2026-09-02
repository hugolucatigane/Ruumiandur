from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import ReadingCreate


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    boot_id TEXT NOT NULL,
                    room TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    uptime_ms INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    temperature_c REAL NOT NULL,
                    humidity_pct REAL NOT NULL,
                    simulated INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    UNIQUE(device_id, boot_id, seq)
                );

                CREATE TABLE IF NOT EXISTS ingestion_events (
                    id INTEGER PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    device_id TEXT,
                    event_type TEXT NOT NULL,
                    detail TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_readings_device_received
                ON readings(device_id, received_at DESC);

                CREATE INDEX IF NOT EXISTS idx_events_device_received
                ON ingestion_events(device_id, received_at DESC);
                """
            )
            connection.execute("PRAGMA optimize")

    def insert_reading(self, reading: ReadingCreate) -> tuple[str, int, str]:
        received_at = iso_utc(utc_now())
        values = (
            reading.device_id,
            reading.boot_id,
            reading.room,
            reading.seq,
            reading.uptime_ms,
            received_at,
            reading.temperature_c,
            reading.humidity_pct,
            int(reading.simulated),
            reading.mode,
        )
        with self.session() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO readings (
                    device_id, boot_id, room, seq, uptime_ms, received_at,
                    temperature_c, humidity_pct, simulated, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            if cursor.rowcount == 1:
                return "stored", int(cursor.lastrowid), received_at

            row = connection.execute(
                """
                SELECT id, received_at FROM readings
                WHERE device_id = ? AND boot_id = ? AND seq = ?
                """,
                (reading.device_id, reading.boot_id, reading.seq),
            ).fetchone()
            if row is None:
                raise RuntimeError("duplicate reading could not be resolved")
            self._insert_event(
                connection,
                reading.device_id,
                "duplicate_payload",
                f"boot_id={reading.boot_id}, seq={reading.seq}",
            )
            return "duplicate", int(row["id"]), str(row["received_at"])

    def record_event(self, device_id: str | None, event_type: str, detail: str) -> None:
        with self.session() as connection:
            self._insert_event(connection, device_id, event_type, detail)

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        device_id: str | None,
        event_type: str,
        detail: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO ingestion_events(received_at, device_id, event_type, detail)
            VALUES (?, ?, ?, ?)
            """,
            (iso_utc(utc_now()), device_id, event_type, detail[:500]),
        )

    def recent_readings(
        self,
        device_id: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        parameters: list[Any] = [device_id]
        where = "device_id = ?"
        if since is not None:
            where += " AND received_at >= ?"
            parameters.append(iso_utc(since))
        parameters.append(limit)
        with self.session() as connection:
            rows = connection.execute(
                f"""
                SELECT id, device_id, boot_id, room, seq, uptime_ms, received_at,
                       temperature_c, humidity_pct, simulated, mode
                FROM readings
                WHERE {where}
                ORDER BY received_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["simulated"] = bool(row["simulated"])
        return result

    def latest_reading(self, device_id: str) -> dict[str, Any] | None:
        rows = self.recent_readings(device_id, limit=1)
        return rows[0] if rows else None

    def latest_event(self, device_id: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT received_at, event_type, detail
                FROM ingestion_events
                WHERE device_id = ?
                ORDER BY received_at DESC
                LIMIT 1
                """,
                (device_id,),
            ).fetchone()
        return dict(row) if row else None

    def latest_invalid_event(self, device_id: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT received_at, event_type, detail
                FROM ingestion_events
                WHERE device_id = ? AND event_type = 'invalid_payload'
                ORDER BY received_at DESC
                LIMIT 1
                """,
                (device_id,),
            ).fetchone()
        return dict(row) if row else None

    def rejected_count(self, device_id: str, hours: float = 24.0) -> int:
        since = iso_utc(utc_now() - timedelta(hours=hours))
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM ingestion_events
                WHERE device_id = ? AND event_type = 'invalid_payload'
                  AND received_at >= ?
                """,
                (device_id, since),
            ).fetchone()
        return int(row["count"])
