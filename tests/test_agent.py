import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from signalwatch_ai.agent import complete, execute_tool, investigate, normalize_response
from helpers import demo_database, reply
from signalwatch_ai.telemetry import read_measurements, detect_alerts
from signalwatch_ai.web import create_app


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.path = demo_database(self)
        self.alert = detect_alerts(read_measurements(self.path, "temperature"))[0]

    def test_real_tool_execution_between_simulated_model_responses(self):
        messages_seen = []
        doc_id = execute_tool(self.path, "search_documents", '{"query":"cooling"}')[0][
            "id"
        ]
        responses = iter(
            [
                reply(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "measure",
                                "type": "function",
                                "function": {
                                    "name": "read_measurements",
                                    "arguments": '{"sensor":"temperature","start":"2026-09-10T08:00:00Z","end":"2026-09-10T08:01:00Z"}',
                                },
                            },
                            {
                                "id": "call1",
                                "type": "function",
                                "function": {
                                    "name": "search_documents",
                                    "arguments": '{"query":"cooling"}',
                                },
                            },
                        ],
                    },
                    "tool_calls",
                ),
                reply(
                    {
                        "role": "assistant",
                        "content": f"Observations: [ref:temperature@2026-09-10T08:00:00+00:00] [ref:{doc_id}]",
                    }
                ),
            ]
        )

        def fake(messages):
            messages_seen.append(list(messages))
            return next(responses)

        result = investigate(self.path, self.alert, "Review two hours", fake)
        self.assertEqual(result["calls"], 2)
        self.assertEqual(result["tokens"], 20)
        self.assertTrue(result["trace"][1]["result"][0]["version"])
        self.assertEqual(messages_seen[1][-1]["role"], "tool")
        self.assertEqual(messages_seen[1][-1]["tool_call_id"], "call1")

    def test_tools_reject_arbitrary_operations(self):
        for name, args in [
            ("shell", "{}"),
            ("read_measurements", '{"sensor":"speed"}'),
            ("search_documents", '{"query": 2}'),
        ]:
            with self.assertRaises(ValueError):
                execute_tool(self.path, name, args)

    def test_key_and_paid_model_rejected_before_network(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            with self.assertRaises(ValueError):
                complete([])
        with patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "test", "OPENROUTER_MODEL": "paid-model"}
        ):
            with self.assertRaises(ValueError):
                complete([])

    def test_api_error_does_not_expose_credentials(self):
        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_API_KEY": "secret", "OPENROUTER_MODEL": "openrouter/free"},
            ),
            patch(
                "signalwatch_ai.agent.urlopen",
                side_effect=HTTPError("url", 429, "secret", {}, None),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "OpenRouter rate limit"):
                complete([])

    def test_truncated_report_is_not_success(self):
        with self.assertRaises(RuntimeError):
            investigate(
                self.path,
                self.alert,
                "",
                lambda _: reply({"content": "incomplete"}, "length"),
            )

    def test_route_uses_server_alert_and_returns_report(self):
        client = create_app(self.path).test_client()
        with patch(
            "signalwatch_ai.web.investigate", return_value={"report": "simulated"}
        ) as run:
            response = client.post(
                "/api/investigate",
                json={
                    "alert_id": self.alert["id"],
                    "context": "two hours",
                    "threshold": 900,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(run.call_args.args[1]["threshold"], 80)
        self.assertEqual(
            client.post("/api/investigate", json={"alert_id": "missing"}).status_code,
            404,
        )
        self.assertEqual(
            client.post(
                "/api/investigate", json=[], headers={"Origin": "https://other.test"}
            ).status_code,
            403,
        )


class ResponseTests(unittest.TestCase):
    def test_malformed_messages_fail_before_tool_execution(self):
        invalid = [
            None,
            [],
            "text",
            {},
            {"choices": [None]},
            reply(None),
            reply("text"),
            reply({"content": []}),
            reply({"tool_calls": "bad"}),
            reply({"tool_calls": [None]}),
            reply(
                {
                    "tool_calls": [
                        {"id": [], "function": {"name": "x", "arguments": "{}"}}
                    ]
                }
            ),
        ]
        for result in invalid:
            with (
                self.subTest(result=result),
                patch("signalwatch_ai.agent.execute_tool") as execute,
            ):
                with self.assertRaisesRegex(RuntimeError, "Invalid model response"):
                    investigate(None, {}, "", lambda _: result)
                execute.assert_not_called()

    def test_bad_metadata_does_not_break_valid_messages(self):
        for usage in [
            None,
            "bad",
            [],
            {"total_tokens": "10"},
            {"total_tokens": -1},
            {"total_tokens": True},
        ]:
            result = reply({"content": "Report"})
            result.update(model=None, usage=usage)
            message, model, tokens = normalize_response(result)
            self.assertEqual(message, {"role": "assistant", "content": "Report"})
            self.assertEqual((model, tokens), ("unknown", None))

    def test_duplicate_call_ids_are_rejected(self):
        call = {
            "id": "same",
            "function": {"name": "search_documents", "arguments": "{}"},
        }
        with self.assertRaises(RuntimeError):
            normalize_response(reply({"tool_calls": [call, call]}))
