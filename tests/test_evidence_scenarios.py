import tempfile
import unittest
from pathlib import Path
from helpers import demo_database
from signalwatch_ai.agent import validate_evidence
from signalwatch_ai.telemetry import (
    seed_demo,
    read_measurements,
    detect_alerts,
    SCENARIOS,
)
from signalwatch_ai.web import create_app


class EvidenceGateTests(unittest.TestCase):
    def test_missing_sources_errors_and_empty_results(self):
        for trace in [
            [],
            [{"tool": "search_documents", "result": []}],
            [{"tool": "read_measurements", "result": {"error": "bad"}}],
        ]:
            with self.assertRaises(RuntimeError):
                validate_evidence("test", trace)

    def test_requires_real_citations_from_both_sources(self):
        trace = [
            {
                "tool": "read_measurements",
                "result": [{"reference": "temperature@time"}],
            },
            {"tool": "search_documents", "result": [{"id": "alerts-1"}]},
        ]
        for report in [
            "no citations",
            "[ref:alerts-1]",
            "[ref:temperature@time] [ref:invented]",
        ]:
            with self.assertRaises(RuntimeError):
                validate_evidence(report, trace)
        validate_evidence("[ref:temperature@time] [ref:alerts-1]", trace)


class ScenarioTests(unittest.TestCase):
    def test_profiles_and_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            profiles = {}
            for scenario in SCENARIOS:
                path = demo_database(self)
                seed_demo(path, scenario)
                profiles[scenario] = read_measurements(
                    path, "temperature", scenario=scenario
                )
                self.assertTrue(detect_alerts(profiles[scenario]))
                if scenario == "steady-speed":
                    self.assertEqual(
                        {
                            r["value"]
                            for r in read_measurements(path, "speed", scenario=scenario)
                        },
                        {1200},
                    )
            self.assertEqual(sum(r["value"] > 80 for r in profiles["spike"]), 1)
            self.assertEqual(sum(r["value"] > 80 for r in profiles["sustained"]), 91)
            self.assertEqual(len(profiles["missing"]), 166)
            self.assertEqual(len(profiles["demo"]), 181)
            self.assertEqual(profiles["demo"], profiles["steady-speed"])

    def test_web_scenario_and_invalid_path(self):
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(demo_database(self)).test_client()
            response = client.get("/?scenario=spike")
            self.assertEqual(response.status_code, 200)
            self.assertTrue("Telemetry history" in response.text)
            self.assertEqual(
                client.get(
                    "/api/measurements?scenario=../../bad&sensor=temperature"
                ).status_code,
                400,
            )
            rows = client.get(
                "/api/measurements?scenario=missing&sensor=temperature"
            ).json
            self.assertEqual(len(rows), 166)


class TimelineTests(unittest.TestCase):
    def test_continuous_history_preserves_episodes_gaps_and_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = demo_database(self)
            seed_demo(path, "timeline")
            rows = read_measurements(path, "temperature", scenario="timeline")
            self.assertEqual(len(rows), 1426)
            self.assertEqual(rows[0]["timestamp"], "2026-09-10T08:00:00+00:00")
            self.assertEqual(rows[-1]["timestamp"], "2026-09-11T08:00:00+00:00")
            self.assertEqual(
                [row["timestamp"] for row in detect_alerts(rows)],
                [
                    "2026-09-10T09:32:00+00:00",
                    "2026-09-10T13:30:00+00:00",
                    "2026-09-10T17:32:00+00:00",
                    "2026-09-10T17:51:00+00:00",
                    "2026-09-10T21:45:00+00:00",
                    "2026-09-11T01:32:00+00:00",
                ],
            )
            self.assertEqual(
                read_measurements(
                    path,
                    "temperature",
                    "2026-09-10T17:36:00Z",
                    "2026-09-10T17:50:00Z",
                    scenario="timeline",
                ),
                [],
            )
            before = read_measurements(path, "temperature", scenario="timeline")
            seed_demo(path, "timeline")
            self.assertEqual(
                read_measurements(path, "temperature", scenario="timeline"), before
            )

    def test_model_receives_actual_history_range(self):
        import json
        from helpers import reply
        from signalwatch_ai.agent import investigation_events

        with tempfile.TemporaryDirectory() as folder:
            path = demo_database(self)
            seed_demo(path, "timeline")
            seen = []

            def completion(messages):
                seen.extend(messages)
                return reply({"content": "No evidence"})

            events = investigation_events(path, {}, "", completion, scenario="timeline")
            while not seen:
                next(events)
            events.close()
            dataset = json.loads(seen[1]["content"])["dataset"]
            self.assertEqual(dataset["end"], "2026-09-11T08:00:00+00:00")
