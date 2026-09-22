from datetime import datetime, timedelta, timezone
import os
from unittest.mock import patch
from helpers import demo_database
import unittest

from signalwatch_ai.knowledge import document_sections, search_documents
from signalwatch_ai.telemetry import detect_alerts, read_measurements, seed_demo
from signalwatch_ai.web import create_app


def readings(values):
    start = datetime(2026, 9, 10, 8, tzinfo=timezone.utc)
    return [
        {
            "sensor": "temperature",
            "timestamp": (start + timedelta(minutes=i)).isoformat(),
            "value": value,
        }
        for i, value in enumerate(values)
    ]


class AlertTests(unittest.TestCase):
    def test_boundary_continuity_and_reentry(self):
        alerts = detect_alerts(readings([79, 80, 81, 95, 80, 82]))
        self.assertEqual([a["value"] for a in alerts], [81, 82])
        self.assertEqual([a["excess"] for a in alerts], [1, 2])

    def test_missing_sample_does_not_imply_continuity(self):
        rows = readings([90, 91, 92])
        self.assertEqual(len(detect_alerts([rows[0], rows[2]])), 2)
        self.assertEqual(detect_alerts([]), [])

    def test_invalid_numeric_and_ordered_input(self):
        for rows in [readings([float("nan")]), list(reversed(readings([70, 90])))]:
            with self.assertRaises(ValueError):
                detect_alerts(rows)


class StorageAndWebTests(unittest.TestCase):
    def setUp(self):
        self.path = demo_database(self)
        self.client = create_app(self.path).test_client()

    def test_seed_is_repeatable_and_read_does_not_mutate(self):
        before = read_measurements(self.path, "temperature")
        rows = read_measurements(self.path, "temperature")
        self.assertEqual(len(rows), 181)
        self.assertEqual(read_measurements(self.path, "temperature"), before)
        seed_demo(self.path)
        self.assertEqual(read_measurements(self.path, "temperature"), rows)

    def test_interval_is_inclusive_and_timezone_normalized(self):
        rows = read_measurements(
            self.path, "speed", "2026-09-10T10:00:00+02:00", "2026-09-10T10:01:00+02:00"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["timestamp"], "2026-09-10T08:00:00+00:00")
        self.assertEqual(
            read_measurements(self.path, "speed", "2027-01-01T00:00:00Z"), []
        )

    def test_invalid_queries_return_400(self):
        for query in [
            {"sensor": "arbitrary SQL"},
            {"sensor": "speed", "start": "2026-09-10T08:00:00"},
            {"sensor": "speed", "start": "bad"},
            {
                "sensor": "speed",
                "start": "2026-09-11T00:00:00Z",
                "end": "2026-09-10T00:00:00Z",
            },
        ]:
            self.assertEqual(
                self.client.get("/api/measurements", query_string=query).status_code,
                400,
            )

    def test_document_evidence_and_no_results(self):
        matches = search_documents("cooling", self.path)
        self.assertTrue(matches)
        self.assertTrue(
            all(len(m["version"]) == 64 and m["section"] and m["text"] for m in matches)
        )
        self.assertEqual(len({s["document"] for s in document_sections(self.path)}), 15)
        self.assertEqual(search_documents("zzzzzz", self.path), [])
        with self.assertRaises(ValueError):
            search_documents("", self.path)
        self.assertEqual(self.client.get("/api/documents?q=cooling").json, matches)

    def test_page_and_assets_are_available_and_ai_is_explicit(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("AI not connected", page.get_data(as_text=True))
        for path in ["/static/style.css", "/static/app.js"]:
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
