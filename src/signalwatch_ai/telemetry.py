"""Synthetic measurements and deterministic alert detection. All times are UTC."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sqlite3

SENSORS = {"temperature": "°C", "speed": "rpm"}
TEMPERATURE_LIMIT = 80.0
SCENARIOS = {
    "timeline": "Continuous history",
    "demo": "Peak with rising motor speed",
    "sustained": "Sustained high temperature",
    "missing": "Missing samples",
    "spike": "Isolated spike",
    "steady-speed": "High temperature, constant speed",
}


def seed_demo(path: Path, scenario: str = "demo") -> None:
    """Create the demo once. Never replace existing measurements."""
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS measurements (
            sensor TEXT NOT NULL, timestamp TEXT NOT NULL, value REAL NOT NULL,
            PRIMARY KEY (sensor, timestamp))""")
        if db.execute("SELECT 1 FROM measurements LIMIT 1").fetchone():
            return
        start = datetime(2026, 9, 10, 8, tzinfo=timezone.utc)
        rows = []
        episodes = ["demo", "sustained", "missing", "spike", "steady-speed"]
        for elapsed in range(1441 if scenario == "timeline" else 181):
            timestamp = (start + timedelta(minutes=elapsed)).isoformat()
            minute = elapsed
            episode = scenario
            if scenario == "timeline":
                block, minute = divmod(elapsed, 240)
                episode = (
                    episodes[block]
                    if block < len(episodes) and minute <= 180
                    else "baseline"
                )
                if episode == "baseline":
                    minute += 240

            heat = max(0, 1 - abs(minute - 105) / 30)
            temperature = round(64 + 31 * heat + 1.2 * math.sin(minute / 8), 1)
            speed = round(1200 + 300 * heat + 35 * math.sin(minute / 12))
            if episode == "sustained":
                temperature = 92.0 if minute >= 90 else 64.0
            elif episode == "spike":
                temperature = 95.0 if minute == 105 else 64.0
            if episode in ("steady-speed", "spike", "sustained"):
                speed = 1200
            if episode == "missing" and 96 <= minute <= 110:
                continue
            rows.extend(
                (("temperature", timestamp, temperature), ("speed", timestamp, speed))
            )
        db.executemany("INSERT INTO measurements VALUES (?, ?, ?)", rows)


def utc_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Specify a timezone in timestamps.")
    return parsed.astimezone(timezone.utc).isoformat()


def read_measurements(
    path: Path, sensor: str, start: str | None = None, end: str | None = None
) -> list[dict]:
    if sensor not in SENSORS:
        raise ValueError("Unknown sensor.")
    start = utc_timestamp(start) if start else "0000"
    end = utc_timestamp(end) if end else "9999"
    if start > end:
        raise ValueError("Start must precede end.")
    # Read-only connection: this function cannot change the database.
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in db.execute(
                "SELECT sensor, timestamp, value FROM measurements "
                "WHERE sensor = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                (sensor, start, end),
            )
        ]


def detect_alerts(readings: list[dict]) -> list[dict]:
    """One alert per excursion above 80 °C; equality is normal.

    A missing minute starts a new observation segment. Do not infer continuity
    or recovery across missing data. Input must be temperature readings in order.
    """
    alerts = []
    previous_time = None
    above = False
    for reading in readings:
        now = datetime.fromisoformat(reading["timestamp"])
        if reading["sensor"] != "temperature" or not math.isfinite(reading["value"]):
            raise ValueError("Expected finite temperature measurements.")
        if previous_time is not None and now <= previous_time:
            raise ValueError("Measurements must be strictly chronological.")
        if previous_time is None or now - previous_time != timedelta(minutes=1):
            above = False
        is_above = reading["value"] > TEMPERATURE_LIMIT
        if is_above and not above:
            alerts.append(
                {
                    **reading,
                    "id": reading["timestamp"],
                    "threshold": TEMPERATURE_LIMIT,
                    "excess": round(reading["value"] - TEMPERATURE_LIMIT, 1),
                }
            )
        above, previous_time = is_above, now
    return alerts


def dataset_range(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        start, end = db.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM measurements"
        ).fetchone()
    return {"start": start, "end": end, "timezone": "UTC"}
