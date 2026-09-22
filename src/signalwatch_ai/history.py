"""Save complete investigation snapshots in PostgreSQL, outside model tools."""

from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from .database import connect


def save(database, scenario, alert, context, result):
    created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        **result,
        "scenario": scenario,
        "alert": alert,
        "context": context,
        "created_at": created_at,
    }
    with connect(database) as db:
        return db.execute(
            "INSERT INTO investigations(created_at, scenario, alert_time, payload) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (created_at, scenario, alert["timestamp"], Jsonb(payload)),
        ).fetchone()["id"]


def list_reports(database, scenario=None):
    with connect(database, readonly=True) as db:
        rows = db.execute(
            "SELECT id, created_at, alert_time, scenario FROM investigations "
            "WHERE (%s::text IS NULL OR scenario=%s) ORDER BY id DESC",
            (scenario, scenario),
        ).fetchall()
    return [
        {
            **row,
            "created_at": row["created_at"].isoformat(),
            "alert_time": row["alert_time"].isoformat(),
        }
        for row in rows
    ]


def load(database, report_id):
    with connect(database, readonly=True) as db:
        row = db.execute(
            "SELECT payload FROM investigations WHERE id=%s", (report_id,)
        ).fetchone()
    return row["payload"] if row else None
