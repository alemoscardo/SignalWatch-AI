import unittest
from signalwatch_ai.presentation import render_report


class PresentationTests(unittest.TestCase):
    def test_markdown(self):
        html = render_report(
            "## Observations\n\n**Temperature**\n\n- High\n- Stable", []
        )
        self.assertIn("<h2>Observations</h2>", html)
        self.assertIn("<strong>Temperature</strong>", html)
        self.assertIn("<ul>", html)

    def test_untrusted_content(self):
        html = render_report(
            "<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![x](https://example.com/pixel)",
            [],
        )
        self.assertNotIn("<script>", html)
        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("<img", html)

    def test_version_kept_in_trace(self):
        version = "a" * 64
        trace = [
            {
                "tool": "search_documents",
                "result": [{"id": "motor-1", "version": version}],
            }
        ]
        self.assertNotIn(version, render_report("Source: " + version, trace))
        self.assertEqual(trace[0]["result"][0]["version"], version)


class CitationLinkTests(unittest.TestCase):
    def test_sources_are_linked_deduplicated_and_escaped(self):
        trace = [
            {
                "tool": "search_documents",
                "result": [
                    {
                        "id": "motor-1",
                        "title": "Motor",
                        "section": "Operating range",
                        "text": "<script>unsafe</script>",
                        "document": "motor.md",
                        "version": "b" * 64,
                    }
                ],
            },
            {
                "tool": "read_measurements",
                "result": [
                    {
                        "reference": "temperature@time",
                        "sensor": "temperature",
                        "timestamp": "2026-09-10T09:30:00+00:00",
                        "value": 92,
                    }
                ],
            },
        ]
        html = render_report(
            "[ref:motor-1] [ref:temperature@time] [ref:motor-1]", trace
        )
        self.assertEqual(html.count('href="#evidence-1"'), 2)
        self.assertEqual(html.count('id="evidence-1"'), 1)
        self.assertIn('href="#evidence-2"', html)
        self.assertIn("92", html)
        self.assertIn("Operating range", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("b" * 64, html)
        self.assertEqual(trace[0]["result"][0]["version"], "b" * 64)
        self.assertNotIn("[ref:", html)

    def test_unknown_reference_is_not_linked(self):
        html = render_report("[ref:invented]", [])
        self.assertNotIn("href=", html)
        self.assertIn("[ref:invented]", html)


class CitationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.trace = [
            {
                "tool": "search_documents",
                "result": [
                    {
                        "id": "motor-1",
                        "title": "Motor",
                        "section": "Range",
                        "text": "Synthetic",
                        "document": "motor.md",
                    }
                ],
            },
            {
                "tool": "read_measurements",
                "result": [
                    {
                        "reference": "temperature@time",
                        "sensor": "temperature",
                        "timestamp": "2026-09-10T09:30:00+00:00",
                        "value": 92,
                    }
                ],
            },
        ]

    def test_inline_code_citations_pass_validation_and_link_to_sources(self):
        from signalwatch_ai.agent import validate_evidence

        report = "`[ref:motor-1]` **[ref:temperature@time]**"
        validate_evidence(report, self.trace)
        html = render_report(report, self.trace)
        self.assertIn('href="#evidence-1"', html)
        self.assertIn('href="#evidence-2"', html)
        self.assertNotIn("[ref:", html)

    def test_fenced_code_and_link_labels_do_not_count_as_evidence(self):
        from signalwatch_ai.agent import validate_evidence

        for report in [
            "```text\n[ref:motor-1] [ref:temperature@time]\n```",
            "[[ref:motor-1]](https://example.com) [ref:temperature@time]",
        ]:
            with self.assertRaises(RuntimeError):
                validate_evidence(report, self.trace)
            self.assertNotIn("Motor · Range", render_report(report, self.trace))

    def test_citation_neighbours_remain_escaped(self):
        html = render_report("<script>bad</script> [ref:motor-1]", self.trace)
        self.assertNotIn("<script>", html)
        self.assertIn('href="#evidence-1"', html)
