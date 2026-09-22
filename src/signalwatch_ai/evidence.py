"""Shared evidence indexing and citation parsing."""

import re
from markdown_it import MarkdownIt

# Validation and presentation use the same evidence and Markdown boundaries.
CITATION = re.compile(r"\[ref:([^\]\n]+)\]")


def evidence_index(trace):
    evidence = {}
    for call in trace:
        key = {"read_measurements": "reference", "search_documents": "id"}.get(
            call.get("tool")
        )
        rows = call.get("result")
        if key and isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get(key):
                    evidence[row[key]] = row
    return evidence


def evidence_references(trace):
    evidence = evidence_index(trace)
    measurements = {key for key, row in evidence.items() if "reference" in row}
    return measurements, set(evidence) - measurements


def report_markdown(report):
    parser = MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")
    return parser, parser.parse(report)


def citation_tokens(tokens):
    """Ignore fenced code and link labels; inline code citations are supported."""
    for block in tokens:
        link_depth = 0
        for token in block.children or []:
            if token.type == "link_open":
                link_depth += 1
            elif token.type == "link_close":
                link_depth -= 1
            elif not link_depth and token.type in ("text", "code_inline"):
                yield token
