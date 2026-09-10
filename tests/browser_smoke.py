"""Optional real-browser checks with local data and simulated API responses."""

from contextlib import closing
import json
import os
import sqlite3
from threading import Thread
import unittest
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from helpers import demo_database
from signalwatch_ai.agent import execute_tool
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
        self.page.goto(self.url + "/?scenario=missing")

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
        self.pending.pop().fulfill(
            json={
                "report_html": render_report(report, trace),
                "trace": trace,
                "model": "offline-test:free",
                "calls": 2,
                "tokens": 20,
                "seconds": 0.1,
            }
        )

    def test_loading_citations_search_and_alert_changes(self):
        page = self.page
        alerts = page.locator("[data-alert]")
        expect(alerts).to_have_count(2)
        page.locator(".additional > summary").click()
        page.locator("#context").fill("Review previous readings")
        page.locator("#investigate").click()
        expect(page.locator("#report")).to_have_attribute("aria-busy", "true")
        expect(page.get_by_text("Preparing your report")).to_be_visible()
        expect(alerts.last).to_be_disabled()
        expect(page.locator("#context")).to_be_disabled()
        self.assertEqual(len(self.pending), 1)
        self.complete_report()
        expect(page.locator("#report strong")).to_have_text("Observed")
        expect(page.locator("#report")).to_have_attribute("aria-busy", "false")
        expect(page.locator("#investigate")).to_be_enabled()
        page.locator('#report a[href="#evidence-2"]').click()
        expect(page.locator("#evidence-2")).to_have_attribute("open", "")
        expect(page.locator("#evidence-2 summary")).to_be_focused()
        alerts.first.click()
        page.locator('[data-sensor="speed"]').click()
        expect(page.locator("#report strong")).to_have_text("Observed")
        alerts.last.click()
        expect(page.locator("#report")).to_be_empty()
        expect(page.locator("#trace")).to_be_empty()
        expect(page.locator("#trace-panel")).to_be_hidden()
        expect(page.locator("#ai-status")).to_contain_text("OpenRouter · free models")
        expect(page.locator("#context")).to_have_value("Review previous readings")
        page.locator(".sources > summary").click()
        self.assertGreater(page.locator("#results details").count(), 0)
        page.locator("#query").fill("cooling")
        page.locator("#search button").click()
        expect(page.locator("#search-status")).to_contain_text("sections found")
        self.assertGreater(page.locator("#results details[open]").count(), 0)
        page.locator("#query").fill("zzzzzz")
        page.locator("#search button").click()
        expect(page.locator("#search-status")).to_contain_text("No results")
        expect(page.locator("#results")).to_be_empty()
        self.assertEqual(self.errors, [])

    def test_failure_recovers_controls_and_idle_button_respects_availability(self):
        page = self.page
        page.locator("#investigate").click()
        expect(page.locator("#report")).to_have_attribute("aria-busy", "true")
        self.assertEqual(len(self.pending), 1)
        self.pending.pop().fulfill(
            status=502, json={"error": "Invalid model response format."}
        )
        expect(page.locator("#ai-status")).to_have_text(
            "Invalid model response format."
        )
        expect(page.locator("#report")).to_be_empty()
        expect(page.locator("#report")).to_have_attribute("aria-busy", "false")
        expect(page.locator("#investigate")).to_be_enabled()
        expect(page.locator("[data-alert]").last).to_be_enabled()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            page.reload()
            expect(page.locator("#investigate")).to_be_disabled()
            expect(page.locator("#ai-status")).to_contain_text("AI not connected")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "UPDATE measurements SET value = 64 WHERE sensor = 'temperature'"
            )
        page.goto(self.url)
        expect(page.locator("[data-alert]")).to_have_count(0)
        expect(page.locator("#investigate")).to_be_disabled()
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
