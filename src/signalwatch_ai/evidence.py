"""Small, literal word search over versioned synthetic Markdown sections."""

import hashlib
from pathlib import Path
import re

from markdown_it import MarkdownIt

DOCUMENTS = Path(__file__).parent / "documents"


def document_sections() -> list[dict]:
    sections = []
    for path in sorted(DOCUMENTS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        version = hashlib.sha256(text.encode()).hexdigest()
        title = text.splitlines()[0].removeprefix("# ")
        for index, section in enumerate(text.split("\n## ")[1:], 1):
            heading, _, body = section.partition("\n")
            sections.append(
                {
                    "id": f"{path.stem}-{index}",
                    "document": path.name,
                    "title": title,
                    "section": heading,
                    "text": body.strip(),
                    "version": version,
                }
            )
    return sections


def search_documents(query: str) -> list[dict]:
    words = set(re.findall(r"\w+", query.casefold()))
    if not words:
        return []
    matches = []
    for section in document_sections():
        content = " ".join(section[key] for key in ("title", "section", "text"))
        score = len(words & set(re.findall(r"\w+", content.casefold())))
        if score:
            matches.append((score, section))
    return [section for _, section in sorted(matches, key=lambda item: -item[0])]


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
