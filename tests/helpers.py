"""Disposable PostgreSQL fixtures; never read OpenRouter credentials."""

import atexit
import os
import uuid
import unittest
from psycopg import sql
from psycopg.conninfo import make_conninfo, conninfo_to_dict
from signalwatch_ai.database import connect, initialize
from signalwatch_ai.telemetry import seed_demo, SCENARIOS
from signalwatch_ai.knowledge import prepare

_template = None


def demo_database(test):
    global _template
    base = os.getenv("SIGNALWATCH_TEST_DATABASE_URL")
    if not base:
        raise RuntimeError(
            "Set SIGNALWATCH_TEST_DATABASE_URL to a disposable database ending in _test."
        )
    if not conninfo_to_dict(base).get("dbname", "").endswith("_test"):
        raise RuntimeError("Test database name must end in _test.")
    admin = make_conninfo(base, dbname="postgres")

    def drop(name):
        with connect(admin) as db:
            db.autocommit = True
            db.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )

    if _template is None:
        _template = "signalwatch_fixture_" + uuid.uuid4().hex
        with connect(admin) as db:
            db.autocommit = True
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(_template)))
        atexit.register(drop, _template)
        template_dsn = make_conninfo(base, dbname=_template)
        initialize(template_dsn)
        for scenario in SCENARIOS:
            seed_demo(template_dsn, scenario)
        prepare(template_dsn)
    name = "signalwatch_test_" + uuid.uuid4().hex
    with connect(admin) as db:
        db.autocommit = True
        db.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(_template)
            )
        )
    test.addCleanup(drop, name)
    return make_conninfo(base, dbname=name)


def reply(message, reason="stop"):
    return {
        "model": "test:free",
        "usage": {"total_tokens": 10},
        "choices": [{"message": message, "finish_reason": reason}],
    }
