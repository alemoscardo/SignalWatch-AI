import tempfile
import unittest
from pathlib import Path
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
                path = Path(folder) / f"{scenario}.db"
                seed_demo(path, scenario)
                profiles[scenario] = read_measurements(path, "temperature")
                self.assertTrue(detect_alerts(profiles[scenario]))
                if scenario == "steady-speed":
                    self.assertEqual(
                        {r["value"] for r in read_measurements(path, "speed")}, {1200}
                    )
            self.assertEqual(sum(r["value"] > 80 for r in profiles["spike"]), 1)
            self.assertEqual(sum(r["value"] > 80 for r in profiles["sustained"]), 91)
            self.assertEqual(len(profiles["missing"]), 166)
            self.assertEqual(len(profiles["demo"]), 181)
            self.assertEqual(profiles["demo"], profiles["steady-speed"])

    def test_web_scenario_and_invalid_path(self):
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(Path(folder) / "demo.db").test_client()
            response = client.get("/?scenario=spike")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Isolated spike", response.text)
            self.assertEqual(client.get("/?scenario=../../bad").status_code, 400)
            rows = client.get(
                "/api/measurements?scenario=missing&sensor=temperature"
            ).json
            self.assertEqual(len(rows), 166)
