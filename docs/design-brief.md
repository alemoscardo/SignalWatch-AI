# Design brief

## Purpose

An understandable local demo that investigates synthetic motor temperature alerts with supporting telemetry and documents. The Python project is separate from the original C# SignalWatch. Product text and model instructions are English; design discussions can be Italian.

## Implemented design

- One Flask application with ordinary Python functions, SQLite and HTML/CSS/JavaScript with a locally bundled Plotly.js basic chart. No frontend build or agent framework.
- One 24-hour synthetic history combines five episodes, with six temperature alert starts and one missing-data interval. It spans 10 September 2026 at 08:00 UTC through 11 September at 08:00 UTC. Legacy short datasets are retained for tests and earlier reports.
- Deterministic alerts on entry above 80 °C. Equality is normal; missing minutes break continuity. The browser graph includes post-alert measurements.
- Three fictional Markdown documents, split into sections and searched by literal words. Results carry document versions and citation identifiers. There is no semantic retrieval.
- The graph is the main screen. Pan and zoom explore the history; selecting an alert reveals details, optional context and the investigation action. There is no scenario or alert dropdown. One progress indicator accompanies generation. Completed reports and evidence snapshots are saved locally and can be reopened, including older datasets. Speed and missing-data alarms are not implemented.
- An OpenRouter tool loop restricted to free model identifiers and zero provider price limits. Credentials stay on the server. No paid fallback or direct OpenAI/Claude integration.

## Tool and report contracts

`read_measurements(sensor, start, end)` accepts temperature or speed and timezone-aware inclusive intervals. `search_documents(query)` accepts a non-empty search string. Tools are read-only, use predefined queries and return ready-to-copy citations. They cannot execute arbitrary SQL, shell commands or equipment controls.

The model receives a server-selected alert and unverified user context. It chooses the investigation interval and when to finish; there is no fixed lookback or tool-call count limit. Each network request times out after 90 seconds. Provider errors stop the investigation without automatic retries.

The prompt requests Observations, Hypotheses, Missing data and Suggested checks. Python checks retrieval and citation existence, not whether every claim is supported. Both source types must be retrieved and cited. Invalid reports receive one guided correction opportunity; another invalid report is rejected. This does not limit the tool investigation loop.

Validation and display share citation parsing and the evidence index. References in ordinary text and inline code become numbered links to evidence snapshots. Measurement links also select the sensor and highlight an exact matching graph sample. The graph supports click and arrow-key inspection. Fenced code and existing link labels are not treated as citations. Model HTML and images are disabled. Document hashes remain in the technical trace; source cards display the actual content and filename.

## Validation and remaining work

Offline tests validate storage, detection, tools, provider response handling, citation repair and rendering. Browser tests use simulated model/API responses to check live progress, loading, alert changes, chart navigation and reopening saved reports. These tests do not establish real model quality.

Planned work includes repeatable live-model evaluations and optional direct provider integrations. Evaluate semantic support, numeric claims, missing-data handling and uncertainty before claiming reliable model explanations. Hypotheses are not verified physical root causes.

## Boundaries

Keep dependencies and layers minimal. Use only synthetic or suitable public data, keep the repository private, and do not change the original SignalWatch. Microservices, vector infrastructure, multi-agent orchestration, equipment control and cloud deployment are outside the current scope.
