"""PostgreSQL connection and explicit schema initialization."""

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

# Shared by the web server and preparation/migration commands.
MAINTENANCE_LOCK = 7419026


def connect(dsn=None, *, readonly=False):
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "Set DATABASE_URL and initialize PostgreSQL with signalwatch-db init."
        )
    db = psycopg.connect(
        dsn,
        row_factory=dict_row,
        connect_timeout=5,
        options="-c timezone=UTC -c statement_timeout=30000",
    )
    db.read_only = readonly
    return db


def initialize(dsn=None):
    with connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (MAINTENANCE_LOCK,))
        exists = db.execute("SELECT to_regclass('schema_version') AS name").fetchone()
        if exists["name"]:
            versions = db.execute("SELECT version FROM schema_version").fetchall()
            if versions != [{"version": 1}]:
                raise RuntimeError("Unsupported database schema version.")
        db.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
