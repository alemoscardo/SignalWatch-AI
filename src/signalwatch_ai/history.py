"""Store completed investigation snapshots locally, without model access."""

from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3


def initialize(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS investigations (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
            scenario TEXT NOT NULL, alert_time TEXT NOT NULL, payload TEXT NOT NULL
        )""")


def save(path, scenario, alert, context, result):
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        **result,
        "scenario": scenario,
        "alert": alert,
        "context": context,
        "created_at": created_at,
    }
    with closing(sqlite3.connect(path)) as db, db:
        cursor = db.execute(
            "INSERT INTO investigations (created_at, scenario, alert_time, payload) VALUES (?, ?, ?, ?)",
            (
                created_at,
                scenario,
                alert["timestamp"],
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        return cursor.lastrowid


def list_reports(path, scenario=None):
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in db.execute(
                "SELECT id, created_at, alert_time, scenario FROM investigations WHERE (? IS NULL OR scenario = ?) ORDER BY id DESC",
                (scenario, scenario),
            )
        ]


def load(path, report_id):
    with closing(sqlite3.connect(path)) as db:
        row = db.execute(
            "SELECT payload FROM investigations WHERE id = ?", (report_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None
