"""Persistent chat, read-only tools and adaptive context compaction."""

import json
from io import BytesIO
import unittest
import uuid
from unittest.mock import patch

from helpers import demo_database
from signalwatch_ai import chat_agent, chat_store
from signalwatch_ai.database import connect, initialize
from signalwatch_ai.telemetry import detect_alerts, read_measurements


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.database = demo_database(self)

    def test_dataset_alert_references_are_stable_and_dataset_scoped(self):
        alerts = chat_store.list_alerts(self.database)
        timeline = next(row for row in alerts if row["dataset"] == "timeline")
        demo = next(row for row in alerts if row["dataset"] == "demo")
        self.assertEqual(timeline["timestamp"], demo["timestamp"])
        self.assertNotEqual(timeline["reference"], demo["reference"])
        self.assertEqual(timeline["reference"], f"a:timeline@{timeline['timestamp']}")
        self.assertEqual(
            chat_store.dataset_telemetry(self.database, "timeline")["alerts"][0][
                "reference"
            ],
            timeline["reference"],
        )

    def test_alert_context_and_saved_evidence_stay_with_their_thread(self):
        alert = chat_store.list_alerts(self.database, "timeline")[0]
        first = chat_store.create_thread(self.database)
        second = chat_store.create_thread(self.database)
        chat_store.set_context(
            self.database,
            first["id"],
            {"dataset": "timeline", "alert": alert},
        )

        evidence = chat_agent.execute_chat_tool(
            self.database,
            first["id"],
            "open_saved_evidence",
            json.dumps({"reference": alert["reference"]}),
        )
        self.assertEqual(evidence, [alert])
        with self.assertRaisesRegex(ValueError, "not retrieved"):
            chat_agent.execute_chat_tool(
                self.database,
                second["id"],
                "open_saved_evidence",
                json.dumps({"reference": alert["reference"]}),
            )

    def test_agent_streams_a_read_only_tool_and_persists_the_turn(self):
        alert = chat_store.list_alerts(self.database, "timeline")[0]
        thread = chat_store.create_thread(self.database)
        chat_store.set_context(
            self.database,
            thread["id"],
            {"dataset": "timeline", "alert": alert},
        )
        turn = chat_store.begin_turn(
            self.database,
            thread["id"],
            uuid.uuid4(),
            "When did this alert begin?",
        )
        answer = f"The alert began at [ref:{alert['reference']}]."
        calls = 0

        def fake_stream(messages, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield {
                    "type": "completion",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-alerts",
                                "type": "function",
                                "function": {
                                    "name": "list_alerts",
                                    "arguments": '{"dataset":"timeline"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                    "usage": {"total_tokens": 21},
                    "model": "test/provider-model",
                }
            else:
                yield {"type": "text_delta", "text": answer}
                yield {
                    "type": "completion",
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                    "usage": {"total_tokens": 12},
                    "model": "test/provider-model",
                }

        with patch.object(chat_agent, "model_context_limit", return_value=32768):
            events = list(
                chat_agent.chat_turn_events(
                    self.database,
                    thread["id"],
                    turn["id"],
                    "When did this alert begin?",
                    turn["context_snapshot"],
                    api_key="offline-test",
                    model="test/provider-model",
                    stream_call=fake_stream,
                )
            )

        self.assertEqual([event["type"] for event in events].count("tool_started"), 1)
        self.assertEqual([event["type"] for event in events].count("tool_finished"), 1)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["answer"], answer)
        loaded = chat_store.load_thread(self.database, thread["id"])
        saved = loaded["turns"][0]
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["assistant_message"], answer)
        self.assertEqual(
            saved["context_snapshot"]["alert"]["reference"], alert["reference"]
        )
        self.assertEqual(saved["trace"][0]["tool"], "list_alerts")
        self.assertEqual(saved["metrics"]["calls"], 2)
        next_turn = chat_store.begin_turn(
            self.database,
            thread["id"],
            uuid.uuid4(),
            "Compare this with the prior alert.",
        )
        messages = chat_agent._textual_messages(
            self.database,
            thread["id"],
            next_turn["id"],
            "Compare this with the prior alert.",
            None,
        )
        previous_user = json.loads(messages[1]["content"])
        self.assertEqual(
            previous_user["selected_alert"]["alert"]["reference"],
            alert["reference"],
        )

    def test_invalid_citation_after_repair_keeps_answer_and_warning(self):
        thread = chat_store.create_thread(self.database)
        turn = chat_store.begin_turn(
            self.database,
            thread["id"],
            uuid.uuid4(),
            "Summarize this telemetry.",
        )
        answer = "### Corrected summary\nThe temperature was **80.5°C** [ref:unknown]."

        def invalid_stream(*args, **kwargs):
            yield {"type": "text_delta", "text": answer}
            yield {
                "type": "completion",
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
                "usage": {"total_tokens": 12},
                "model": "test/provider-model",
            }

        with patch.object(chat_agent, "model_context_limit", return_value=32768):
            events = list(
                chat_agent.chat_turn_events(
                    self.database,
                    thread["id"],
                    turn["id"],
                    "Summarize this telemetry.",
                    None,
                    api_key="offline-test",
                    model="test/provider-model",
                    stream_call=invalid_stream,
                )
            )

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(
            events[-1]["message"],
            "The response still contains an invalid or missing citation.",
        )
        self.assertEqual(events[-1]["partial"], answer)
        saved = chat_store.load_thread(self.database, thread["id"])["turns"][0]
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["partial_message"], answer)
        self.assertEqual(saved["error"], events[-1]["message"])

    def test_tool_allowlist_rejects_non_read_only_operations(self):
        thread = chat_store.create_thread(self.database)
        with self.assertRaisesRegex(ValueError, "Unknown read-only tool"):
            chat_agent.execute_chat_tool(
                self.database,
                thread["id"],
                "execute_sql",
                '{"query":"DELETE FROM measurements"}',
            )
        self.assertEqual(
            read_measurements(
                self.database,
                "temperature",
                "2026-09-10T09:32:00Z",
                "2026-09-10T09:32:00Z",
                scenario="timeline",
            )[0]["value"],
            detect_alerts(
                read_measurements(self.database, "temperature", scenario="timeline")
            )[0]["value"],
        )

    def test_openrouter_sse_reassembles_streamed_tool_calls(self):
        chunks = [
            {
                "model": "provider/model",
                "choices": [
                    {
                        "delta": {
                            "content": "Checking alerts. ",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-",
                                    "function": {
                                        "name": "list_",
                                        "arguments": '{"dataset":',
                                    },
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "1",
                                    "function": {
                                        "name": "alerts",
                                        "arguments": '"timeline"}',
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {"choices": [], "usage": {"total_tokens": 15}},
        ]
        body = (
            b"".join(
                b"data: " + json.dumps(chunk).encode("utf-8") + b"\n\n"
                for chunk in chunks
            )
            + b"data: [DONE]\n\n"
        )
        request_seen = []

        def fake_urlopen(request, timeout):
            request_seen.append((request, timeout))
            return BytesIO(body)

        with patch.object(chat_agent, "urlopen", side_effect=fake_urlopen):
            events = list(
                chat_agent.openrouter_stream(
                    [{"role": "user", "content": "List alerts"}],
                    api_key="offline-test",
                    model="test/model",
                    tools=[],
                )
            )

        self.assertEqual(events[0], {"type": "text_delta", "text": "Checking alerts. "})
        completion = events[-1]
        self.assertEqual(completion["type"], "completion")
        call = completion["message"]["tool_calls"][0]
        self.assertEqual(call["id"], "call-1")
        self.assertEqual(call["function"]["name"], "list_alerts")
        self.assertEqual(
            json.loads(call["function"]["arguments"]), {"dataset": "timeline"}
        )
        self.assertEqual(completion["usage"]["total_tokens"], 15)
        request, timeout = request_seen[0]
        self.assertEqual(timeout, 120)
        self.assertEqual(request.get_header("Authorization"), "Bearer offline-test")

    def test_closed_stream_marks_turn_interrupted(self):
        thread = chat_store.create_thread(self.database)
        turn = chat_store.begin_turn(
            self.database,
            thread["id"],
            uuid.uuid4(),
            "Inspect the latest readings.",
        )

        def unexpected_stream(*args, **kwargs):
            raise AssertionError("The stream should close before a provider call.")

        with patch.object(chat_agent, "model_context_limit", return_value=8192):
            events = chat_agent.chat_turn_events(
                self.database,
                thread["id"],
                turn["id"],
                "Inspect the latest readings.",
                None,
                api_key="offline-test",
                model="test/provider-model",
                stream_call=unexpected_stream,
            )
            self.assertEqual(next(events)["type"], "request_started")
            events.close()

        saved = chat_store.load_thread(self.database, thread["id"])["turns"][0]
        self.assertEqual(saved["status"], "interrupted")
        self.assertEqual(saved["error"], "Connection closed during generation.")

    def test_agent_stops_at_the_per_turn_request_limit(self):
        thread = chat_store.create_thread(self.database)
        turn = chat_store.begin_turn(
            self.database,
            thread["id"],
            uuid.uuid4(),
            "List all the datasets.",
        )
        provider_calls = 0

        def repeated_tool_call(messages, **kwargs):
            nonlocal provider_calls
            provider_calls += 1
            yield {
                "type": "completion",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{provider_calls}",
                            "type": "function",
                            "function": {
                                "name": "list_datasets",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
                "usage": {"total_tokens": 1},
                "model": "test/provider-model",
            }

        with patch.object(chat_agent, "model_context_limit", return_value=32768):
            events = list(
                chat_agent.chat_turn_events(
                    self.database,
                    thread["id"],
                    turn["id"],
                    "List all the datasets.",
                    None,
                    api_key="offline-test",
                    model="test/provider-model",
                    stream_call=repeated_tool_call,
                )
            )

        self.assertEqual(provider_calls, chat_agent.MAX_AGENT_REQUESTS)
        self.assertEqual(
            sum(event["type"] == "request_started" for event in events),
            chat_agent.MAX_AGENT_REQUESTS,
        )
        self.assertEqual(events[-1]["type"], "error")
        saved = chat_store.load_thread(self.database, thread["id"])["turns"][0]
        self.assertEqual(saved["status"], "error")
        self.assertIn("request limit", saved["error"])

    def test_compaction_keeps_recent_turns_and_saves_a_summary_in_thread(self):
        thread = chat_store.create_thread(self.database)
        completed_ids = []
        for index in range(7):
            turn = chat_store.begin_turn(
                self.database,
                thread["id"],
                uuid.uuid4(),
                f"Question {index} " + ("context " * 90),
            )
            completed_ids.append(turn["id"])
            chat_store.finish_turn(
                self.database,
                turn["id"],
                f"Answer {index} " + ("observation " * 90),
                {"calls": 1},
            )
        current = chat_store.begin_turn(
            self.database,
            thread["id"],
            uuid.uuid4(),
            "Compare the latest alert.",
        )
        with (
            patch.object(chat_agent, "model_context_limit", return_value=1800),
            patch.object(
                chat_agent,
                "_summarize",
                return_value="The user is comparing telemetry observations; no new facts were verified.",
            ),
        ):
            messages, compaction = chat_agent._maybe_compact(
                self.database,
                thread["id"],
                "test/provider-model",
                "offline-test",
                chat_agent._textual_messages(
                    self.database,
                    thread["id"],
                    current["id"],
                    "Compare the latest alert.",
                    None,
                ),
                current["id"],
                "Compare the latest alert.",
                None,
            )

        self.assertIsNotNone(compaction)
        self.assertEqual(compaction["through_turn_id"], completed_ids[2])
        self.assertTrue(
            any("Saved conversation summary" in item["content"] for item in messages)
        )
        saved = chat_store.load_thread(self.database, thread["id"])["compactions"]
        self.assertEqual(len(saved), 1)
        self.assertGreater(
            saved[0]["context_tokens_before"], saved[0]["context_tokens_after"]
        )

    def test_initialize_upgrades_schema_version_one_and_adds_chat_tables(self):
        with connect(self.database) as db:
            db.execute("DROP TABLE chat_compactions,chat_turns,chat_threads")
            db.execute("UPDATE schema_version SET version=1")

        initialize(self.database)

        with connect(self.database, readonly=True) as db:
            version = db.execute("SELECT version FROM schema_version").fetchone()
            thread_table = db.execute(
                "SELECT to_regclass('chat_threads') AS name"
            ).fetchone()["name"]
        self.assertEqual(version["version"], 2)
        self.assertEqual(thread_table, "chat_threads")


if __name__ == "__main__":
    unittest.main()
