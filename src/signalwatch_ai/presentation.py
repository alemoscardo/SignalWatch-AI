"""Render model Markdown without allowing model-provided HTML or images."""

from html import escape
from .evidence import CITATION, citation_tokens, evidence_index, report_markdown
from .telemetry import SENSORS


def render_report(report: str, trace: list) -> str:
    evidence = evidence_index(trace)
    # Abbreviate hashes in prose without changing versioned citation IDs.
    parts = CITATION.split(report)
    for row in evidence.values():
        version = row.get("version", "")
        if len(version) == 64:
            for index in range(0, len(parts), 2):
                parts[index] = (
                    parts[index]
                    .replace(version, "consulted version")
                    .replace(version[:12], "consulted version")
                )
    report = "".join(
        part if index % 2 == 0 else f"[ref:{part}]" for index, part in enumerate(parts)
    )
    cited = {}

    def citation(reference):
        if reference not in evidence:
            return escape(f"[ref:{reference}]")
        number = cited.setdefault(reference, len(cited) + 1)
        row = evidence[reference]
        attributes = ""
        if "reference" in row:
            attributes = f' data-sensor="{escape(row["sensor"])}" data-timestamp="{escape(row["timestamp"])}" data-value="{escape(str(row["value"]))}"'
        return f'<a href="#evidence-{number}"{attributes}>[{number}]</a>'

    parser, tokens = report_markdown(report)
    for token in citation_tokens(tokens):
        if not CITATION.search(token.content):
            continue
        parts = CITATION.split(token.content)
        content = "".join(
            escape(part) if index % 2 == 0 else citation(part)
            for index, part in enumerate(parts)
        )
        if token.type == "code_inline":
            content = f"<code>{content}</code>"
        token.type = "html_inline"
        token.content = content
    rendered = parser.renderer.render(tokens, parser.options, {})

    if cited:
        rendered += '<section class="report-sources" aria-label="Cited sources"><h3>Cited sources</h3>'
        for reference, number in cited.items():
            row = evidence[reference]
            if "reference" in row:
                sensor = row["sensor"].capitalize()
                unit = SENSORS[row["sensor"]]
                title = f"{sensor} · {row['timestamp'][11:16]} UTC"
                content = f"{row['value']} {unit} · {row['timestamp']}"
                body = f"<p>{escape(content)}</p>"
            else:
                title = f"{row['title']} · {row['section']}"
                body = f"<p>{escape(row['text'])}</p>"
                body += f"<small>{escape(row['document'])} · {escape(str(row.get('equipment', 'historical')))} · revision {escape(str(row.get('revision', 'unknown')))}</small>"
            rendered += (
                f'<details id="evidence-{number}" class="evidence-source">'
                f'<summary tabindex="-1">[{number}] {escape(title)}</summary>{body}</details>'
            )
        rendered += "</section>"
    return rendered
