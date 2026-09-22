"""Real PostgreSQL and local-encoder tests. No generation API calls."""

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import psycopg
from helpers import demo_database
from signalwatch_ai.database import connect, MAINTENANCE_LOCK
from signalwatch_ai import knowledge, encoder, evaluation
from signalwatch_ai.agent import validate_evidence
from signalwatch_ai.migration import migrate
from signalwatch_ai.telemetry import read_measurements
from signalwatch_ai.web import create_app


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.db = demo_database(self)

    def test_corrupt_or_incomplete_corpus_blocks_new_work_without_breaking_page(self):
        from psycopg.types.json import Jsonb

        with connect(self.db) as db:
            original = db.execute(
                "SELECT manifest FROM corpus_generations WHERE active"
            ).fetchone()["manifest"]
        for manifest in (
            {},
            {**original, "splitter": 999},
            {**original, "passages": 999},
        ):
            with connect(self.db) as db:
                db.execute(
                    "UPDATE corpus_generations SET manifest=%s WHERE active",
                    (Jsonb(manifest),),
                )
            client = create_app(self.db).test_client()
            self.assertFalse(knowledge.status(self.db)["ready"])
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/api/investigations").status_code, 200)
            self.assertEqual(client.post("/api/investigate", json={}).status_code, 503)
        with connect(self.db) as db:
            db.execute(
                "UPDATE corpus_generations SET manifest=%s WHERE active",
                (Jsonb(original),),
            )
            db.execute("DELETE FROM passages")
        self.assertFalse(knowledge.status(self.db)["ready"])
        with self.assertRaises(RuntimeError):
            knowledge.search_documents("cooling", self.db)

    def test_insufficient_answer_with_both_categories_stays_insufficient(self):
        trace = [
            {"tool": "read_measurements", "result": [{"reference": "m"}]},
            {"tool": "search_documents", "result": [{"id": "d"}]},
        ]
        self.assertEqual(
            validate_evidence("Insufficient evidence. [ref:m] [ref:d]", trace),
            "insufficient_evidence",
        )
        self.assertEqual(
            validate_evidence("Observed [ref:m] [ref:d]", trace), "references_valid"
        )

    def test_unexpected_failure_closes_attempt_and_export_carries_configuration(self):
        with patch(
            "signalwatch_ai.evaluation.search_documents",
            side_effect=OSError("private path"),
        ):
            with self.assertRaises(OSError):
                evaluation.run(self.db, modes=("semantic",), split="held_out")
        with connect(self.db, readonly=True) as db:
            run = db.execute(
                "SELECT * FROM evaluation_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            result = db.execute(
                "SELECT result FROM evaluation_results WHERE run_id=%s", (run["id"],)
            ).fetchone()["result"]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(result["status"], "error")
        self.assertNotIn("private path", result["error"])
        with tempfile.TemporaryDirectory() as folder:
            evaluation.export(self.db, run["id"], folder)
            config = json.loads(
                Path(folder, f"evaluation-{run['id']}.json").read_text()
            )["config"]
        self.assertIn("encoder", config["corpus_manifest"])
        self.assertIn("tools", config["prompt"])
        self.assertIn("agent.py", config["code_sha256"])
        self.assertEqual(len(config["telemetry_sha256"]), 64)

    def test_failed_report_keeps_usage_and_completed_tools(self):
        def events(*args, **kwargs):
            yield {
                "type": "metrics",
                "calls": 2,
                "tokens": None,
                "known_tokens": 12,
                "model": "test:free",
            }
            yield {"type": "tool", "call": {"tool": "search_documents", "result": []}}
            raise RuntimeError("Provider unavailable")

        with connect(self.db) as db:
            run_id = db.execute(
                "INSERT INTO evaluation_runs(kind,config) VALUES ('reports','{}') RETURNING id"
            ).fetchone()["id"]
        with patch(
            "signalwatch_ai.evaluation.investigation_events", side_effect=events
        ):
            evaluation.run_attempt(
                self.db,
                run_id,
                "reports",
                {"id": "case", "scenario": "demo", "context": "", "expected": ""},
                "semantic",
                1,
                1,
            )
        with connect(self.db, readonly=True) as db:
            result = db.execute(
                "SELECT result FROM evaluation_results WHERE run_id=%s", (run_id,)
            ).fetchone()["result"]
        self.assertEqual(
            (result["status"], result["calls"], result["known_tokens"]),
            ("error", 2, 12),
        )
        self.assertIsNone(result["tokens"])
        self.assertEqual(len(result["trace"]), 1)

    def test_fixture_splits_do_not_share_expected_passages(self):
        cases = json.loads((evaluation.FIXTURES / "retrieval.json").read_text())
        development = {
            p for c in cases if c["split"] == "development" for p in c["expected"]
        }
        held = {p for c in cases if c["split"] == "held_out" for p in c["expected"]}
        self.assertFalse(development & held)

    def test_applicability_and_revision_boundaries(self):
        for at, expected in [
            ("2026-08-31T23:59:59Z", "cooling-old.md"),
            ("2026-09-01T00:00:00Z", "cooling.md"),
            ("2026-10-01T00:00:00Z", "cooling-future.md"),
        ]:
            rows = knowledge.search_documents(
                "cooling", self.db, at=at, mode="lexical", limit=20
            )
            self.assertEqual(
                {r["document"] for r in rows if r["document"].startswith("cooling")},
                {expected},
            )
        rows = knowledge.search_documents(
            "temperature", self.db, equipment="M-02", limit=20
        )
        self.assertTrue(rows)
        self.assertTrue(all(r["equipment"] in ("general", "M-02") for r in rows))

    def test_real_local_encoder_and_unanswerable_query(self):
        self.assertEqual(len(encoder.encode(["Heat removal"])[0]), 384)
        self.assertTrue(knowledge.search_documents("inadequate heat removal", self.db))
        self.assertEqual(
            knowledge.search_documents("Where can I buy concert tickets?", self.db), []
        )
        for query in ("", "!!!", "the", "x " * 2001):
            with self.assertRaises(ValueError):
                knowledge.search_documents(query, self.db)

    def test_stale_sources_block_investigations_but_preserve_history_routes(self):
        with patch(
            "signalwatch_ai.knowledge.source_manifest", return_value={"changed": True}
        ):
            self.assertFalse(knowledge.status(self.db)["ready"])
            client = create_app(self.db).test_client()
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/api/investigations").status_code, 200)
            self.assertEqual(client.post("/api/investigate", json={}).status_code, 503)

    def test_bad_metadata_and_long_paragraph_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "docs"
            shutil.copytree(knowledge.DOCUMENTS, folder)
            catalog = json.loads((folder / "catalog.json").read_text())
            catalog.append(catalog[0])
            (folder / "catalog.json").write_text(json.dumps(catalog))
            with self.assertRaises(ValueError):
                knowledge.read_sources(folder)
        docs = knowledge.read_sources()
        docs[0]["sections"] = [("Long section", "temperature " * 500)]
        with self.assertRaisesRegex(ValueError, "too long"):
            knowledge.make_passages(docs)

    def test_failed_preparation_and_app_lock_preserve_generation(self):
        before = knowledge.status(self.db)["generation"]
        with connect(self.db) as lock:
            lock.execute("SELECT pg_advisory_lock_shared(%s)", (MAINTENANCE_LOCK,))
            with self.assertRaisesRegex(RuntimeError, "Stop the app"):
                knowledge.prepare(self.db)
        self.assertEqual(knowledge.status(self.db)["generation"], before)
        with patch("signalwatch_ai.encoder.encode", return_value=[[1, 2, 3]] * 26):
            with self.assertRaises(psycopg.Error):
                knowledge.prepare(self.db)
        self.assertEqual(knowledge.status(self.db)["generation"], before)

    def test_rebuild_changes_generation_and_retains_old_sources(self):
        before = knowledge.status(self.db)["generation"]
        old = knowledge.document_sections(self.db, before)
        knowledge.prepare(self.db)
        self.assertNotEqual(knowledge.status(self.db)["generation"], before)
        self.assertEqual(knowledge.document_sections(self.db, before), old)

    def test_readonly_connection_cannot_write(self):
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            with connect(self.db, readonly=True) as db:
                db.execute("DELETE FROM measurements")

    def test_database_outage_returns_explicit_error(self):
        with patch(
            "signalwatch_ai.telemetry.connect",
            side_effect=psycopg.OperationalError("secret"),
        ):
            response = create_app(self.db).test_client().get("/")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.text)

    def test_insufficient_evidence_requires_successful_search_and_honest_label(self):
        trace = [
            {
                "tool": "read_measurements",
                "result": [{"reference": "temperature@time"}],
            },
            {"tool": "search_documents", "result": []},
        ]
        self.assertEqual(
            validate_evidence("Insufficient evidence. [ref:temperature@time]", trace),
            "insufficient_evidence",
        )
        for report in (
            "The motor is repaired. [ref:temperature@time]",
            "Insufficient evidence. [ref:invented]",
        ):
            with self.assertRaises(RuntimeError):
                validate_evidence(report, trace)
        trace[-1]["result"] = {"error": "database unavailable"}
        with self.assertRaises(RuntimeError):
            validate_evidence("Insufficient evidence", trace)

    def test_evaluation_records_failures_and_exports_denominators(self):
        with patch(
            "signalwatch_ai.evaluation.search_documents",
            side_effect=RuntimeError("test failure"),
        ):
            run_id = evaluation.run(self.db, modes=("semantic",), split="held_out")
        with tempfile.TemporaryDirectory() as folder:
            path = evaluation.export(self.db, run_id, folder)
            self.assertIn("Completed: 0/10", Path(path).read_text())
            rows = json.loads(Path(folder, f"evaluation-{run_id}.json").read_text())[
                "results"
            ]
            self.assertTrue(all(r["result"]["status"] == "error" for r in rows))
        with self.assertRaises(ValueError):
            evaluation.run(self.db, kind="reports", live=False)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.db = demo_database(self)
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.folder / "legacy.sqlite3"
        self.payload = {
            "report": "Observation [ref:legacy-doc]",
            "trace": [
                {
                    "tool": "search_documents",
                    "result": [{"id": "legacy-doc", "text": "Old source"}],
                }
            ],
            "context": "Original context",
        }
        with closing(sqlite3.connect(self.source)) as src, src:
            src.execute(
                "CREATE TABLE measurements(sensor text,timestamp text,value real)"
            )
            src.executemany(
                "INSERT INTO measurements VALUES (?,?,?)",
                [
                    ("temperature", "2026-09-10T08:00:00Z", 79),
                    ("temperature", "2026-09-10T08:02:00Z", 90),
                ],
            )
            src.execute(
                "CREATE TABLE investigations(id integer,created_at text,scenario text,alert_time text,payload text)"
            )
            src.execute(
                "INSERT INTO investigations VALUES (7,'2026-09-10T10:00:00Z','legacy','2026-09-10T08:02:00Z',?)",
                (json.dumps(self.payload),),
            )

    def test_import_preserves_snapshots_gaps_and_is_repeatable(self):
        before = self.source.read_bytes()
        result = migrate(
            self.source, self.db, dataset="legacy", backup_dir=self.folder / "backups"
        )
        self.assertEqual(result["status"], "imported_and_verified")
        self.assertEqual(
            len(read_measurements(self.db, "temperature", scenario="legacy")), 2
        )
        with connect(self.db, readonly=True) as db:
            self.assertEqual(
                db.execute("SELECT payload FROM investigations WHERE id=7").fetchone()[
                    "payload"
                ],
                self.payload,
            )
        self.assertEqual(
            migrate(
                self.source,
                self.db,
                dataset="legacy",
                backup_dir=self.folder / "backups",
            )["status"],
            "already_imported",
        )
        self.assertEqual(self.source.read_bytes(), before)

    def test_conflicting_report_rolls_back_new_measurements(self):
        with connect(self.db) as db:
            db.execute(
                "INSERT INTO investigations VALUES (7,now(),'demo',now(),'{}'::jsonb)"
            )
        with self.assertRaisesRegex(ValueError, "Report ID conflict"):
            migrate(
                self.source,
                self.db,
                dataset="legacy",
                backup_dir=self.folder / "backups",
            )
        self.assertEqual(
            read_measurements(self.db, "temperature", scenario="legacy"), []
        )

    def test_unknown_tables_are_not_imported(self):
        with closing(sqlite3.connect(self.source)) as src, src:
            src.execute("CREATE TABLE private_data(value text)")
        with self.assertRaisesRegex(ValueError, "Not a supported"):
            migrate(
                self.source,
                self.db,
                dataset="legacy",
                backup_dir=self.folder / "backups",
            )
