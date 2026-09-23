"""Safe Markdown rendering for chat replies and their cited snapshots."""

from html import escape

from .evidence import CITATION, citation_tokens, report_markdown
from .telemetry import SENSORS


def render_chat_message(answer, evidence, turn_id):
    parser, tokens = report_markdown(answer)
    cited = {}

    def anchor(reference):
        row = evidence.get(reference)
        if row is None:
            return escape(f"[ref:{reference}]")
        number = cited.setdefault(reference, len(cited) + 1)
        target = f"chat-evidence-{turn_id}-{number}"
        return f'<a class="chat-citation" href="#{target}">[{number}]</a>'

    for token in citation_tokens(tokens):
        if not CITATION.search(token.content):
            continue
        parts = CITATION.split(token.content)
        rendered = "".join(
            escape(part) if index % 2 == 0 else anchor(part)
            for index, part in enumerate(parts)
        )
        if token.type == "code_inline":
            rendered = f"<code>{rendered}</code>"
        token.type = "html_inline"
        token.content = rendered
    html = parser.renderer.render(tokens, parser.options, {})
    if cited:
        html += (
            '<section class="chat-evidence" aria-label="Sources used"><h4>Sources</h4>'
        )
        for reference, number in cited.items():
            row = evidence[reference]
            target = f"chat-evidence-{turn_id}-{number}"
            kind = row.get("source_type")
            if kind == "measurement":
                title = f"{row.get('dataset')} · {row.get('sensor')} · {row.get('timestamp')}"
                unit = SENSORS.get(row.get("sensor"), "")
                body = f"{row.get('value')} {unit}".strip()
            elif kind == "alert":
                title = (
                    f"{row.get('dataset')} · temperature alert · {row.get('timestamp')}"
                )
                body = f"{row.get('value')} °C, threshold {row.get('threshold')} °C, excess {row.get('excess')} °C"
            else:
                title = f"{row.get('title', row.get('document', 'Document'))} · {row.get('section', '')}"
                body = row.get("text", "")
            html += (
                f'<details class="chat-evidence-item" id="{target}">'
                f"<summary>[{number}] {escape(str(title))}</summary>"
                f"<p>{escape(str(body))}</p>"
            )
            if kind == "document":
                html += (
                    f'<small>{escape(str(row.get("document", "")))} · '
                    f'{escape(str(row.get("equipment", "")))} · revision '
                    f'{escape(str(row.get("revision", "unknown")))}</small>'
                )
            html += "</details>"
        html += "</section>"
    return html
