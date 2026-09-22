"""Explicit, verified import of one legacy SQLite file. Originals stay untouched."""

from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

from psycopg.types.json import Jsonb
from .database import connect, MAINTENANCE_LOCK
from .telemetry import SENSORS, utc_timestamp, detect_alerts


def read_legacy_snapshot(source, dataset, backup_dir):
    source = Path(source).resolve(strict=True)
    backup_dir = Path(backup_dir).resolve()
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        tables = {
            r[0]
            for r in original.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not tables & {"measurements", "investigations"} or tables - {
            "measurements",
            "investigations",
            "sqlite_sequence",
        }:
            raise ValueError("Not a supported SignalWatch SQLite database.")
        if "measurements" in tables and not dataset:
            raise ValueError("Specify --dataset for a measurements database.")
        backup_dir.mkdir(parents=True, exist_ok=True)
        # SQLite's backup API also includes committed WAL data.
        snapshot = (
            backup_dir
            / f"{source.stem}-{hashlib.sha256(str(source).encode()).hexdigest()[:12]}.sqlite3"
        )
        if snapshot == source:
            raise ValueError("Backup must differ from the original file.")
        # Existing recovery copies are never overwritten.
        snapshot = snapshot.with_stem(snapshot.stem + f"-{time.time_ns()}")
        with closing(sqlite3.connect(snapshot)) as copy:
            original.backup(copy)
    with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as src:
        src.row_factory = sqlite3.Row
        measures = (
            [
                dict(r)
                for r in src.execute(
                    "SELECT * FROM measurements ORDER BY sensor,timestamp"
                )
            ]
            if "measurements" in tables
            else []
        )
        reports = (
            [dict(r) for r in src.execute("SELECT * FROM investigations ORDER BY id")]
            if "investigations" in tables
            else []
        )
    return source, snapshot, measures, reports


def migrate(
    source,
    database=None,
    *,
    dataset=None,
    backup_dir=Path("data/local/migration-backups"),
):
    source, snapshot, measures, reports = read_legacy_snapshot(
        source, dataset, backup_dir
    )
    fingerprint = hashlib.sha256(
        json.dumps([dataset, measures, reports], sort_keys=True).encode()
    ).hexdigest()
    for row in measures:
        if row["sensor"] not in SENSORS or not math.isfinite(row["value"]):
            raise ValueError("Invalid legacy measurement.")
        row["timestamp"] = utc_timestamp(row["timestamp"])
    if len({(r["sensor"], r["timestamp"]) for r in measures}) != len(measures):
        raise ValueError("Timestamps collide after UTC normalization.")
    expected_alerts = detect_alerts(
        sorted(
            [r for r in measures if r["sensor"] == "temperature"],
            key=lambda r: r["timestamp"],
        )
    )
    summary = {
        "measurements": len(measures),
        "reports": len(reports),
        "backup": str(snapshot),
        "dataset": dataset,
    }
    with connect(database) as db:
        if not db.execute(
            "SELECT pg_try_advisory_xact_lock(%s) AS locked", (MAINTENANCE_LOCK,)
        ).fetchone()["locked"]:
            raise RuntimeError("Stop the app before migrating.")
        if db.execute(
            "SELECT 1 FROM imports WHERE fingerprint=%s", (fingerprint,)
        ).fetchone():
            return {**summary, "status": "already_imported"}
        if measures:
            import_measurements(db, dataset, measures, expected_alerts)
        import_reports(db, reports)
        db.execute(
            "SELECT setval(pg_get_serial_sequence('investigations','id'), COALESCE((SELECT max(id) FROM investigations),1), EXISTS(SELECT 1 FROM investigations))"
        )
        db.execute(
            "INSERT INTO imports(fingerprint,source,summary) VALUES (%s,%s,%s)",
            (fingerprint, str(source), Jsonb(summary)),
        )
    return {**summary, "status": "imported_and_verified"}


def import_measurements(db, dataset, measures, expected_alerts):
    existing = [
        {**r, "timestamp": r["timestamp"].isoformat()}
        for r in db.execute(
            "SELECT sensor,timestamp,value FROM measurements WHERE dataset=%s ORDER BY sensor,timestamp",
            (dataset,),
        )
    ]
    if existing and existing != sorted(
        measures, key=lambda r: (r["sensor"], r["timestamp"])
    ):
        raise ValueError(
            "Target dataset contains different readings. Choose an unused dataset; nothing was imported."
        )
    db.execute(
        "INSERT INTO datasets(id) VALUES (%s) ON CONFLICT DO NOTHING",
        (dataset,),
    )
    if not existing:
        with db.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO measurements(dataset,sensor,timestamp,value) VALUES (%s,%s,%s,%s)",
                [(dataset, r["sensor"], r["timestamp"], r["value"]) for r in measures],
            )
    actual = [
        {**r, "timestamp": r["timestamp"].isoformat()}
        for r in db.execute(
            "SELECT sensor,timestamp,value FROM measurements WHERE dataset=%s ORDER BY sensor,timestamp",
            (dataset,),
        )
    ]
    if (
        actual != sorted(measures, key=lambda r: (r["sensor"], r["timestamp"]))
        or detect_alerts([r for r in actual if r["sensor"] == "temperature"])
        != expected_alerts
    ):
        raise RuntimeError("Measurement verification failed; import rolled back.")


def import_reports(db, reports):
    for row in reports:
        if db.execute(
            "SELECT 1 FROM investigations WHERE id=%s", (row["id"],)
        ).fetchone():
            raise ValueError(
                "Report ID conflict. Import into a clean database; existing reports were not overwritten."
            )
        payload = json.loads(row["payload"])
        if not isinstance(payload, dict) or not isinstance(payload.get("report"), str):
            raise ValueError("Invalid legacy report payload.")
        db.execute(
            "INSERT INTO investigations(id,created_at,scenario,alert_time,payload) VALUES (%s,%s,%s,%s,%s)",
            (
                row["id"],
                row["created_at"],
                row["scenario"],
                row["alert_time"],
                Jsonb(payload),
            ),
        )
        if (
            db.execute(
                "SELECT payload FROM investigations WHERE id=%s", (row["id"],)
            ).fetchone()["payload"]
            != payload
        ):
            raise RuntimeError(
                "Report snapshot verification failed; import rolled back."
            )
