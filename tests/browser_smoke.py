"""Optional real-browser checks with local data and simulated agent events."""

import json
import os
from threading import Event, Thread
import unittest
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from helpers import demo_database
from signalwatch_ai import chat_store, history
from signalwatch_ai.telemetry import detect_alerts, read_measurements
from signalwatch_ai.web import create_app


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.path = demo_database(self)
        self.enterContext(
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "offline-test"})
        )
        server = make_server("127.0.0.1", 0, create_app(self.path), threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        runtime = self.enterContext(sync_playwright())
        browser = runtime.chromium.launch(
            channel=os.getenv("SIGNALWATCH_TEST_BROWSER") or None, headless=True
        )
        self.addCleanup(browser.close)
        self.page = browser.new_page(viewport={"width": 1280, "height": 900})
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.url = f"http://127.0.0.1:{server.server_port}"
        self.page.goto(self.url)
        self.page.wait_for_function(
            "document.querySelector('#chart').data?.length === 3"
        )
        self.alerts = detect_alerts(
            read_measurements(self.path, "temperature", scenario="timeline")
        )

    def choose_chart_alert(self, index):
        page = self.page
        page.locator("#chart").scroll_into_view_if_needed()
        coords = page.evaluate(
            """index => {
              const graph = document.querySelector('#chart');
              const bounds = graph.getBoundingClientRect();
              const layout = graph._fullLayout;
              return {x: bounds.x + layout.xaxis._offset + layout.xaxis.d2p(graph.data[1].x[index]),
                      y: bounds.y + layout.yaxis._offset + layout.yaxis.d2p(graph.data[1].y[index])};
            }""",
            index,
        )
        page.mouse.move(coords["x"], coords["y"])
        expect(page.locator("#chart .hovertext")).to_be_visible()
        page.mouse.click(coords["x"], coords["y"])

    def test_dataset_alert_selection_and_chart(self):
        page = self.page
        expect(page.locator("#thread-list .thread-choice")).to_have_count(0)
        expect(page.locator("#alert-list .alert-choice")).to_have_count(
            len(self.alerts)
        )
        expect(page.locator("#active-context")).to_contain_text("No alert selected")
        page.locator("#alert-list .alert-choice").nth(1).click()
        expect(page.locator("#active-context")).to_contain_text(
            self.alerts[1]["timestamp"][11:16]
        )
        expect(page.locator("#alert-list .active")).to_have_count(1)
        page.locator("#clear-context").click()
        expect(page.locator("#active-context")).to_contain_text("No alert selected")

        page.locator("#dataset-select").select_option("spike")
        expect(page.locator("#dataset-title")).to_contain_text("Isolated spike")
        expect(page.locator("#alert-list .alert-choice")).to_have_count(1)
        self.choose_chart_alert(0)
        expect(page.locator("#active-context")).to_contain_text("spike")
        expect(page.locator("#context-status")).to_contain_text(
            "context applies to your next message"
        )
        self.assertEqual(self.errors, [])

    def test_live_tool_trace_saved_chat_and_legacy_archive(self):
        page = self.page
        alert = self.alerts[0]
        history.save(
            self.path,
            "timeline",
            alert,
            "old report context",
            {
                "report": "Old investigation result.",
                "trace": [],
                "model": "old:model",
                "calls": 1,
                "tokens": 10,
                "seconds": 0.1,
            },
        )
        page.reload()
        page.wait_for_function("document.querySelector('#chart').data?.length === 3")
        expect(page.locator("#history-list button")).to_have_count(1)
        page.locator(".history > summary").click()
        page.locator("#history-list button").click()
        expect(page.locator("#legacy-dialog")).to_be_visible()
        expect(page.locator("#legacy-report")).to_contain_text(
            "Old investigation result"
        )
        page.locator("#legacy-close").click()
        expect(page.locator("#thread-list .thread-choice")).to_have_count(0)

        page.locator("#alert-list .alert-choice").first.click()
        page.locator("#message").fill("When did this alert begin?")
        release = Event()
        self.addCleanup(release.set)

        def events(database, thread_id, turn_id, user_message, context, **kwargs):
            yield {"type": "request_started", "request": 1}
            yield {
                "type": "tool_started",
                "tool": "list_alerts",
                "arguments": {"dataset": context["dataset"]},
                "call_id": "call-1",
            }
            if not release.wait(10):
                raise RuntimeError("Browser test timed out")
            saved_alert = context["alert"]
            tool_result = {
                **saved_alert,
                "trace_detail": "sample evidence " * 400,
            }
            record = {
                "tool": "list_alerts",
                "arguments": {"dataset": context["dataset"]},
                "result": [tool_result],
                "seconds": 0.01,
                "tool_call_id": "call-1",
            }
            chat_store.append_trace(database, turn_id, record)
            answer = f"The alert began at [ref:{saved_alert['reference']}]."
            metrics = {
                "calls": 1,
                "tokens": 23,
                "models": ["offline-test"],
                "seconds": 0.1,
            }
            chat_store.finish_turn(database, turn_id, answer, metrics)
            yield {"type": "tool_finished", **record}
            yield {"type": "text_delta", "text": answer, "provisional": True}
            yield {
                "type": "done",
                "answer": answer,
                "trace": [record],
                "evidence": {saved_alert["reference"]: saved_alert},
                "metrics": metrics,
                "compactions": [],
            }

        with patch("signalwatch_ai.web.chat_turn_events", side_effect=events):
            page.locator("#chat-form button[type=submit]").click()
            expect(page.locator(".thinking-indicator")).to_contain_text(
                "Checking alerts"
            )
            self.assertFalse(
                page.locator(".tool-calls").evaluate("element => element.open")
            )
            expect(page.locator(".tool-card")).to_be_hidden()
            expect(page.locator(".tool-calls > summary")).to_contain_text("Tool Calls")
            page.locator(".tool-calls > summary").click()
            expect(page.locator(".tool-card")).to_be_visible()
            expect(page.locator(".tool-card__state")).to_have_text("Running…")
            release.set()
            expect(page.locator(".assistant-message")).to_contain_text(
                "The alert began"
            )
            expect(page.locator(".assistant-message .chat-citation")).to_have_count(1)
            expect(page.locator("#thread-list .thread-choice")).to_have_count(1)
            expect(page.locator(".tool-card__output")).to_contain_text(
                "sample evidence"
            )
        page.reload()
        expect(page.locator(".assistant-message")).to_contain_text("The alert began")
        expect(page.locator(".tool-card")).to_be_hidden()
        page.locator(".tool-calls > summary").click()
        steps = page.locator(".tool-calls__steps")
        scroll = steps.evaluate(
            "element => ({overflowY: getComputedStyle(element).overflowY, maxHeight: getComputedStyle(element).maxHeight})"
        )
        self.assertEqual(scroll["overflowY"], "auto")
        self.assertNotEqual(scroll["maxHeight"], "none")
        page.wait_for_function(
            "element => element.scrollHeight > element.clientHeight",
            arg=steps.element_handle(),
            timeout=3000,
        )
        steps.hover(timeout=5000)
        outer_scroll_before = page.locator("#chat-messages").evaluate(
            "element => element.scrollTop"
        )
        page.mouse.wheel(0, 240)
        page.wait_for_function(
            "document.querySelector('.tool-calls__steps').scrollTop > 0",
            timeout=3000,
        )
        outer_scroll_after = page.locator("#chat-messages").evaluate(
            "element => element.scrollTop"
        )
        self.assertEqual(outer_scroll_after, outer_scroll_before)
        expect(page.locator(".tool-card summary")).to_contain_text("list_alerts")
        expect(page.locator("#active-context")).to_contain_text("Continuous history")
        self.assertEqual(self.errors, [])

    def test_partial_answer_with_error_stays_formatted_with_clickable_warning(self):
        page = self.page
        page.locator("#message").fill("Summarize the evidence.")
        answer = (
            "### Corrected summary\n"
            "The temperature reached **80.5°C** [ref:unknown]."
        )
        warning = "The response still contains an invalid or missing citation."

        def events(database, thread_id, turn_id, user_message, context, **kwargs):
            chat_store.fail_turn(database, turn_id, answer, warning)
            yield {"type": "request_started", "request": 1}
            yield {"type": "text_delta", "text": answer, "provisional": True}
            yield {"type": "error", "message": warning, "partial": answer}

        with patch("signalwatch_ai.web.chat_turn_events", side_effect=events):
            page.locator("#chat-form button[type=submit]").click()
            expect(page.locator(".assistant-message h3")).to_have_text(
                "Corrected summary"
            )
            expect(page.locator(".assistant-message strong")).to_contain_text("80.5°C")
            expect(page.locator(".response-warning summary")).to_have_text(
                "Citation warning"
            )
            expect(page.locator(".chat-notice--error")).to_have_count(0)
            page.locator(".response-warning summary").click()
            expect(page.locator(".response-warning p")).to_contain_text(warning)

        page.reload()
        expect(page.locator(".assistant-message h3")).to_have_text("Corrected summary")
        expect(page.locator(".response-warning summary")).to_have_text(
            "Citation warning"
        )
        self.assertEqual(self.errors, [])

    def test_provider_setup_does_not_send_or_create_a_turn(self):
        page = self.page
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            page.reload()
            page.wait_for_function(
                "document.querySelector('#chart').data?.length === 3"
            )
            page.locator("#message").fill("Please inspect this alert")
            page.locator("#chat-form button[type=submit]").click()
            expect(page.locator("#provider-dialog")).to_be_visible()
            page.locator("#provider-model").fill("openai/gpt-4o")
            page.locator("#provider-key").fill("temporary-test-key")
            page.locator("#provider-submit").click()
            expect(page.locator("#provider-dialog")).to_be_hidden()
            expect(page.locator("#ai-status")).to_contain_text("openai/gpt-4o")
            expect(page.locator("#thread-list .thread-choice")).to_have_count(0)
            expect(page.locator("#message")).to_have_value("Please inspect this alert")
        self.assertEqual(self.errors, [])

    def test_plotly_gaps_zoom_and_mobile_layout(self):
        page = self.page
        self.assertEqual(page.evaluate("Plotly.version"), "3.5.1")
        self.assertEqual(
            page.evaluate(
                "document.querySelector('#chart').data[0].y.filter(value => value === null).length"
            ),
            1,
        )
        page.locator('#chart [data-title="Zoom"]').click()
        page.evaluate(
            "Plotly.relayout('chart', {'xaxis.range': ['2026-09-10 09:00', '2026-09-10 10:00'], 'xaxis.autorange': false})"
        )
        page.locator("#chart").press("ArrowRight")
        self.assertFalse(
            page.evaluate("document.querySelector('#chart').layout.xaxis.autorange")
        )
        page.locator('#chart [data-title="Reset axes"]').click()
        page.wait_for_function(
            "document.querySelector('#chart').layout.xaxis.autorange"
        )
        page.locator('button[data-sensor="speed"]').click()
        self.assertEqual(
            page.evaluate("document.querySelector('#chart').layout.shapes.length"), 0
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
