import json
import unittest
from unittest.mock import patch

from helpers import demo_database, reply
from signalwatch_ai.agent import execute_tool, investigation_events
from signalwatch_ai.telemetry import detect_alerts, read_measurements
from signalwatch_ai.web import create_app


class HistoryProgressTests(unittest.TestCase):
    def setUp(self):
        self.path = demo_database(self)
        self.client = create_app(self.path).test_client()
        self.alert = detect_alerts(read_measurements(self.path, "temperature"))[0]
        measures = execute_tool(
            self.path,
            "read_measurements",
            json.dumps(
                {
                    "sensor": "speed",
                    "start": "2026-09-10T08:00:00Z",
                    "end": "2026-09-10T08:00:00Z",
                }
            ),
        )
        docs = execute_tool(self.path, "search_documents", '{"query":"temperature"}')
        self.result = {
            "report": f"{measures[0]['citation']} {docs[0]['citation']}",
            "trace": [
                {"tool": "read_measurements", "result": measures},
                {"tool": "search_documents", "result": docs},
            ],
            "model": "offline:free",
            "calls": 2,
            "tokens": 12,
            "seconds": 0.1,
        }
        self.body = {"alert_id": self.alert["id"], "context": "Look back two hours"}

    def test_saved_report_survives_app_restart_and_keeps_snapshots(self):
        telemetry_before = read_measurements(self.path, "temperature")
        with patch("signalwatch_ai.web.investigate", return_value=self.result):
            response = self.client.post("/api/investigate", json=self.body)
        self.assertEqual(response.status_code, 200)
        report_id = response.json["id"]
        client = create_app(self.path).test_client()
        saved = client.get(f"/api/investigations/{report_id}").json
        self.assertEqual(saved["trace"], self.result["trace"])
        self.assertEqual(saved["context"], self.body["context"])
        self.assertEqual(saved["alert"], self.alert)
        self.assertEqual(saved["scenario"], "demo")
        self.assertIn('data-sensor="speed"', saved["report_html"])
        self.assertIn('data-value="1200.0"', saved["report_html"])
        self.assertEqual(len(client.get("/api/investigations?scenario=demo").json), 1)
        self.assertEqual(client.get("/api/investigations?scenario=spike").json, [])
        self.assertEqual(client.get("/api/investigations/9999").status_code, 404)
        self.assertEqual(
            client.get("/api/investigations?scenario=bad").status_code, 400
        )
        self.assertEqual(read_measurements(self.path, "temperature"), telemetry_before)

    def test_stream_sends_progress_before_result_and_saves_once(self):
        completed = []

        def events(*args, **kwargs):
            yield {"type": "progress", "message": "Reading measurements…"}
            completed.append(True)
            yield {"type": "result", "result": self.result}

        with patch("signalwatch_ai.web.investigation_events", side_effect=events):
            response = self.client.post(
                "/api/investigate",
                json=self.body,
                headers={"Accept": "application/x-ndjson"},
                buffered=False,
            )
            iterator = iter(response.response)
            first = json.loads(next(iterator))
            self.assertEqual(first["type"], "progress")
            self.assertEqual(completed, [])
            final = json.loads(next(iterator))
            self.assertEqual(final["type"], "result")
            self.assertIn("report_html", final["result"])
            response.close()
        self.assertEqual(len(self.client.get("/api/investigations").json), 1)

    def test_stream_failure_is_explicit_and_does_not_save(self):
        def events(*args, **kwargs):
            yield {"type": "progress", "message": "Waiting for the model…"}
            raise RuntimeError("OpenRouter rate limit reached. Try again later.")

        with patch("signalwatch_ai.web.investigation_events", side_effect=events):
            response = self.client.post(
                "/api/investigate",
                json=self.body,
                headers={"Accept": "application/x-ndjson"},
            )
            events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("rate limit", events[-1]["message"])
        self.assertEqual(self.client.get("/api/investigations").json, [])

    def test_agent_progress_follows_real_operations(self):
        calls = [
            {
                "id": "m",
                "function": {
                    "name": "read_measurements",
                    "arguments": '{"sensor":"speed","start":"2026-09-10T08:00:00Z","end":"2026-09-10T08:00:00Z"}',
                },
            },
            {
                "id": "d",
                "function": {
                    "name": "search_documents",
                    "arguments": '{"query":"temperature"}',
                },
            },
        ]
        responses = iter(
            [reply({"tool_calls": calls}), reply({"content": self.result["report"]})]
        )
        with patch("signalwatch_ai.agent.execute_tool", wraps=execute_tool) as execute:
            events = investigation_events(
                self.path, self.alert, "", lambda _: next(responses)
            )
            self.assertIn("Waiting", next(events)["message"])
            self.assertEqual(next(events)["type"], "metrics")
            self.assertEqual(next(events)["type"], "metrics")
            self.assertIn("Reading", next(events)["message"])
            self.assertEqual(execute.call_count, 0)
            self.assertEqual(next(events)["type"], "tool")
            self.assertIn("Searching", next(events)["message"])
            self.assertEqual(execute.call_count, 1)
            remaining = list(events)
            self.assertEqual(execute.call_count, 2)
            self.assertEqual(remaining[-1]["type"], "result")
            self.assertEqual(remaining[-2]["message"], "Checking report citations…")
