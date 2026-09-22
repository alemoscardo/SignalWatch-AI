from helpers import reply, demo_database
import json
import unittest
from unittest.mock import patch
from signalwatch_ai.agent import investigate, execute_tool


def response(content=None, calls=None):
    return reply(
        {"role": "assistant", "content": content, "tool_calls": calls},
        "tool_calls" if calls else "stop",
    )


CALLS = [
    {"id": "m", "function": {"name": "read_measurements", "arguments": "{}"}},
    {"id": "d", "function": {"name": "search_documents", "arguments": "{}"}},
]
OUTPUTS = [
    [{"reference": "temperature@time", "citation": "[ref:temperature@time]"}],
    [{"id": "doc-1", "citation": "[ref:doc-1]"}],
]
VALID = "Observation [ref:temperature@time]. Hypothesis [ref:doc-1]."


class RepairTests(unittest.TestCase):
    def run_sequence(self, replies):
        seen = []
        iterator = iter(replies)

        def completion(messages):
            seen.append(list(messages))
            return next(iterator)

        with patch("signalwatch_ai.agent.execute_tool", side_effect=OUTPUTS):
            result = investigate(None, {}, "", completion)
        return result, seen

    def test_format_repaired_without_retrieving_again(self):
        result, seen = self.run_sequence(
            [response(calls=CALLS), response("Missing citations"), response(VALID)]
        )
        self.assertEqual(result["calls"], 3)
        feedback = json.loads(seen[-1][-1]["content"])
        self.assertEqual(feedback["measurement_citations"], ["[ref:temperature@time]"])
        self.assertEqual(feedback["document_citations"], ["[ref:doc-1]"])
        self.assertEqual(len(result["trace"]), 2)

    def test_initial_tool_skip_can_recover(self):
        result, seen = self.run_sequence(
            [response("No tools"), response(calls=CALLS), response(VALID)]
        )
        self.assertEqual(result["report"], VALID)
        self.assertEqual(
            json.loads(seen[1][-1]["content"])["measurement_citations"], []
        )

    def test_invalid_repair_still_rejected(self):
        for text in ["No citations", VALID + " [ref:fake]"]:
            with self.assertRaisesRegex(RuntimeError, "did not correct"):
                self.run_sequence(
                    [response(calls=CALLS), response("Missing"), response(text)]
                )

    def test_document_tool_supplies_ready_citation(self):
        rows = execute_tool(
            demo_database(self), "search_documents", '{"query":"temperature"}'
        )
        self.assertTrue(rows)
        self.assertEqual(rows[0]["citation"], f"[ref:{rows[0]['id']}]")
