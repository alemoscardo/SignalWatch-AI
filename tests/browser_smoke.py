"""Optional real-browser checks with local data and simulated API responses."""

from contextlib import closing
import json
import os
import sqlite3
from threading import Event, Thread
import unittest
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from helpers import demo_database
from signalwatch_ai.agent import execute_tool
from signalwatch_ai import history
from signalwatch_ai.telemetry import detect_alerts, read_measurements
from signalwatch_ai.presentation import render_report
from signalwatch_ai.web import create_app


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.path = demo_database(self)
        self.enterContext(
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "offline-test"})
        )
        self.enterContext(
            patch(
                "signalwatch_ai.agent.urlopen",
                side_effect=AssertionError(
                    "Model network calls forbidden in browser tests"
                ),
            )
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
        self.pending = []
        self.page.route("**/api/investigate", lambda route: self.pending.append(route))
        self.url = f"http://127.0.0.1:{server.server_port}"
        self.page.goto(self.url)
        self.page.wait_for_function(
            "document.querySelector('#chart').data?.length === 3"
        )
        self.timeline = self.path.with_name(
            f"{self.path.stem}-timeline{self.path.suffix}"
        )
        self.alerts = detect_alerts(read_measurements(self.timeline, "temperature"))

    def complete_report(self):
        measurements = execute_tool(
            self.path,
            "read_measurements",
            json.dumps(
                {
                    "sensor": "temperature",
                    "start": "2026-09-10T08:00:00Z",
                    "end": "2026-09-10T08:00:00Z",
                }
            ),
        )
        documents = execute_tool(
            self.path, "search_documents", '{"query":"temperature"}'
        )
        trace = [
            {"tool": "read_measurements", "result": measurements},
            {"tool": "search_documents", "result": documents},
        ]
        report = f"**Observed** `{measurements[0]['citation']}`. Possible explanation {documents[0]['citation']}."
        result = {
            "report": report,
            "trace": trace,
            "model": "offline-test:free",
            "calls": 2,
            "tokens": 20,
            "seconds": 0.1,
        }
        path = self.timeline
        alert = detect_alerts(read_measurements(path, "temperature"))[0]
        history.save(
            self.path.with_name(f"{self.path.stem}-investigations.sqlite3"),
            "timeline",
            alert,
            "Review previous readings",
            result,
        )
        self.pending.pop().fulfill(
            content_type="application/x-ndjson",
            body=json.dumps(
                {
                    "type": "result",
                    "result": {**result, "report_html": render_report(report, trace)},
                }
            )
            + "\n",
        )

    def choose_alert(self, index):
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

    def test_chart_first_and_alert_selection(self):
        page = self.page
        expect(page.locator("#scenario")).to_have_count(0)
        expect(page.locator("#alert-select")).to_have_count(0)
        expect(page.locator(".investigation")).to_be_hidden()
        self.assertGreater(len(self.alerts), 4)
        self.choose_alert(1)
        expect(page.locator(".investigation")).to_be_visible()
        expect(page.locator("#selection")).to_contain_text(
            self.alerts[1]["timestamp"][11:16]
        )
        self.assertEqual(self.pending, [])
        page.locator("#close-investigation").click()
        expect(page.locator(".investigation")).to_be_hidden()
        page.locator("#chart-alerts button").first.focus()
        page.keyboard.press("Enter")
        expect(page.locator(".investigation")).to_be_visible()
        expect(page.locator("#selection")).to_contain_text(
            self.alerts[0]["timestamp"][11:16]
        )
        self.choose_alert(len(self.alerts) - 1)
        expect(page.locator("#selection")).to_contain_text("2026-09-11 01:32 UTC")
        self.assertEqual(self.errors, [])

    def test_loading_citations_and_history(self):
        page = self.page
        self.choose_alert(0)
        page.locator(".additional > summary").click()
        page.locator("#context").fill("Review previous readings")
        page.locator("#investigate").click()
        expect(page.locator(".loading-spinner")).to_have_count(1)
        expect(page.locator("#close-investigation")).to_be_disabled()
        self.choose_alert(1)
        expect(page.locator("#selection")).to_contain_text(
            self.alerts[0]["timestamp"][11:16]
        )
        self.assertEqual(len(self.pending), 1)
        self.complete_report()
        expect(page.locator("#report strong")).to_have_text("Observed")
        expect(page.locator("#investigate")).to_be_enabled()
        page.locator('#report a[href="#evidence-2"]').click()
        expect(page.locator("#evidence-2 summary")).to_be_focused()
        page.locator('button[data-sensor="speed"]').click()
        page.locator('#report a[href="#evidence-1"]').click()
        expect(page.locator('button[data-sensor="temperature"]')).to_have_attribute(
            "aria-pressed", "true"
        )
        expect(page.locator("#chart-selection")).to_contain_text("08:00 UTC")
        page.locator("#chart").press("ArrowRight")
        expect(page.locator("#chart-selection")).to_contain_text("08:01 UTC")
        self.choose_alert(1)
        expect(page.locator("#report")).to_be_empty()
        expect(page.locator("#trace-panel")).to_be_hidden()
        page.reload()
        expect(page.locator(".investigation")).to_be_hidden()
        page.locator(".history > summary").click()
        page.locator("#history-list button").click()
        expect(page.locator("#report strong")).to_have_text("Observed")
        expect(page.locator("#context")).to_have_value("Review previous readings")
        expect(page.locator("#selection")).to_contain_text("2026-09-10 09:32 UTC")
        expect(page.locator("#history-list button")).to_contain_text(
            "2026-09-10 09:32 UTC"
        )
        page.locator("#close-investigation").click()
        expect(page.locator(".investigation")).to_be_hidden()
        expect(page.locator("#report")).to_be_empty()
        self.assertEqual(self.pending, [])
        self.assertEqual(self.errors, [])

    def test_plotly_gaps_zoom_and_mobile(self):
        page = self.page
        self.assertEqual(page.evaluate("Plotly.version"), "3.5.1")
        self.assertEqual(
            page.evaluate(
                "document.querySelector('#chart').data[0].y.filter(value => value === null).length"
            ),
            1,
        )
        self.assertEqual(
            page.evaluate("document.querySelector('#chart').layout.dragmode"), "pan"
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
        self.choose_alert(0)
        expect(page.locator("#investigate")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_live_progress_stream_and_error(self):
        self.choose_alert(0)
        release = Event()
        self.addCleanup(release.set)

        def events(*args):
            yield {"type": "progress", "message": "Searching documents…"}
            if not release.wait(10):
                raise RuntimeError("Test timed out")
            raise RuntimeError("Offline provider failure")

        self.page.unroute("**/api/investigate")
        with patch("signalwatch_ai.web.investigation_events", side_effect=events):
            self.page.locator("#investigate").click()
            expect(self.page.locator("#progress-message")).to_have_text(
                "Searching documents…"
            )
            release.set()
            expect(self.page.locator("#ai-status")).to_have_text(
                "Offline provider failure"
            )
            expect(self.page.locator("#investigate")).to_be_enabled()
        self.assertEqual(self.errors, [])

    def test_no_credentials_empty_dataset_and_document_search(self):
        page = self.page
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            page.reload()
            page.wait_for_function(
                "document.querySelector('#chart').data?.length === 3"
            )
            self.choose_alert(0)
            expect(page.locator("#investigate")).to_be_disabled()
        page.locator(".sources > summary").click()
        page.locator("#query").fill("cooling")
        page.locator("#search button").click()
        expect(page.locator("#search-status")).to_contain_text("sections found")
        with closing(sqlite3.connect(self.timeline)) as connection, connection:
            connection.execute(
                "UPDATE measurements SET value = 64 WHERE sensor = 'temperature'"
            )
        page.reload()
        page.wait_for_function("document.querySelector('#chart').data?.length === 3")
        expect(page.locator(".investigation")).to_be_hidden()
        self.assertEqual(
            page.evaluate("document.querySelector('#chart').data[1].x.length"), 0
        )
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
