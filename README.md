# SignalWatch AI

Local synthetic telemetry investigation with Python, SQLite and a browser interface. The original C# SignalWatch is separate.

## Run locally

Python 3.11 or later. Run from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

Copy the example only if you do not already have `.env`. Paste your OpenRouter key after `OPENROUTER_API_KEY=`, then start the app:

```powershell
.\.venv\Scripts\python.exe -m signalwatch_ai.web
```

Open [the local app](http://127.0.0.1:5055). Use `--port 5056` if needed. The server binds to loopback with debugging disabled. The `.env` file is loaded from the working directory; existing environment variables take precedence. Restart after changing configuration. Keys and local databases are ignored by Git. Never put keys in browser code or commit them.

## Using the demo

Select a scenario and press **Load**, choose an alert, optionally add context, then press **Investigate**. The loading notice remains visible while the model retrieves evidence. Selecting another alert clears the previous report and trace.

Reports support Markdown headings, emphasis, lists and tables. Numbered citations open the measurement or document section retrieved for that investigation. Inline code citations are supported; fenced code and existing link labels do not count as citations. Repeated references share a source card. Model HTML and images are disabled. Full document hashes and tool calls remain available in the technical trace. Reports and traces are not saved across reloads.

The document catalog and search use the same renderer. Search matches literal words in three fictional Markdown documents; it is not semantic retrieval.

## Data and detection

Temperature and speed are sampled every minute from 08:00 to 11:00 UTC on 10 September 2026. SQLite is seeded on first use and existing measurements are preserved. Additional scenarios use separate sibling files under `data/local/`.

| Scenario | Synthetic behavior |
| --- | --- |
| Peak with rising motor speed | Temperature and speed rise together. |
| Sustained high temperature | Temperature stays at 92 °C from 09:30 through 11:00; speed is constant. |
| Missing samples | Both sensors omit 09:36–09:50; the graph breaks across the gap. |
| Isolated spike | One 95 °C sample at 09:45, surrounded by 64 °C samples. |
| High temperature, constant speed | Original temperature profile with speed fixed at 1200 rpm. |

Python detects entry above 80 °C, producing one alert per continuous excursion. Equality is normal. Missing minutes break continuity; recovery across a gap is not inferred. The graph includes measurements after the selected alert. Synthetic patterns do not establish physical causes.

## Agent behavior and limits

OpenRouter integration uses the Python standard library and two read-only tools: `read_measurements(sensor, start, end)` and `search_documents(query)`. Measurement queries validate sensors and inclusive timezone-aware intervals and use predefined SQL. The model cannot run arbitrary SQL, shell commands or equipment controls.

Only `openrouter/free` or model IDs ending in `:free` are accepted, with provider price limits set to zero and no paid fallback. Availability and rate limits depend on OpenRouter. The free router may choose different models across requests; a specific tool-capable `:free` model allows more comparable evaluations.

The model chooses when to finish and which intervals to inspect. There is no fixed call-count or lookback cap. Each HTTP request has a 90-second timeout; network/provider errors stop the investigation without retries. Repeated tool requests can keep it running until completion or an error.

Both tools must return evidence and the report must cite both source types. Citations are checked against the retrieved evidence. A rejected report gets one guided correction opportunity, including available references; the model may retrieve missing evidence before resubmitting. A second invalid report is rejected. This repair rule is separate from the unrestricted investigation loop.

Reference validation does not verify semantic support, numerical claims or physical root causes. Offline tests use simulated responses and do not measure real model quality. Live-model evaluation, persistent reports and direct OpenAI/Claude integrations remain planned. Product text and model instructions are English.

## Verify offline

```powershell
python -m unittest discover -s tests -v
node --check src/signalwatch_ai/static/app.js
```

Tests cover thresholds, missing samples, storage isolation, HTTP routes, tool argument validation, malformed provider responses, evidence repair and safe citation rendering. They make no model API calls and do not load `.env`.

Optional browser regression tests use Playwright and a temporary local server with intercepted investigation responses:

```powershell
python -m pip install playwright
python -m playwright install chromium
python tests/browser_smoke.py
```

To use installed Edge instead of downloading Chromium, set `$env:SIGNALWATCH_TEST_BROWSER = "msedge"` before running the browser tests. Browser tests cover loading, source links, document search, failed requests and clearing stale reports on alert changes.

Python uses Black formatting, JavaScript and CSS use Prettier, and the Jinja template uses two-space indentation. These are development tools; the app has no frontend build step.

## Code map

- `telemetry.py`: synthetic data, SQLite reads and deterministic thresholds.
- `evidence.py`: document search, evidence identifiers and shared citation parsing.
- `agent.py`: OpenRouter transport, response validation, tools and investigation loop.
- `presentation.py`: safe report rendering and cited source snapshots.
- `web.py`: HTTP routes and startup.
- `templates/` and `static/`: page, styling and browser interactions.
- `documents/`: fictional technical sources.

See [the design brief](docs/design-brief.md) for implemented decisions and planned work. Keep the repository private and use only synthetic or suitable public data.
