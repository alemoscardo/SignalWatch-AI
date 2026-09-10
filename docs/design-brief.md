# Design brief

## Purpose

An understandable local demo that investigates synthetic motor temperature alerts with supporting telemetry and documents. The Python project is separate from the original C# SignalWatch. Product text and model instructions are English; design discussions can be Italian.

## Implemented design

- One Flask application with ordinary Python functions, SQLite and vanilla HTML/CSS/JavaScript. No frontend build or agent framework.
- Five repeatable synthetic scenarios with temperature and speed sampled every minute from 08:00 to 11:00 UTC on 10 September 2026. Each scenario has its own SQLite file.
- Deterministic alerts on entry above 80 °C. Equality is normal; missing minutes break continuity. The browser graph includes post-alert measurements.
- Three fictional Markdown documents, split into sections and searched by literal words. Results carry document versions and citation identifiers. There is no semantic retrieval.
- Alert selection, optional additional context, a visible generation state and a Markdown report. Changing alerts clears the previous report and trace. Reports are not persisted.
- An OpenRouter tool loop restricted to free model identifiers and zero provider price limits. Credentials stay on the server. No paid fallback or direct OpenAI/Claude integration.

## Tool and report contracts

`read_measurements(sensor, start, end)` accepts temperature or speed and timezone-aware inclusive intervals. `search_documents(query)` accepts a non-empty search string. Tools are read-only, use predefined queries and return ready-to-copy citations. They cannot execute arbitrary SQL, shell commands or equipment controls.

The model receives a server-selected alert and unverified user context. It chooses the investigation interval and when to finish; there is no fixed lookback or tool-call count limit. Each network request times out after 90 seconds. Provider errors stop the investigation without automatic retries.

The prompt requests Observations, Hypotheses, Missing data and Suggested checks. Python checks retrieval and citation existence, not whether every claim is supported. Both source types must be retrieved and cited. Invalid reports receive one guided correction opportunity; another invalid report is rejected. This does not limit the tool investigation loop.

Validation and display share citation parsing and the evidence index. References in ordinary text and inline code become numbered links to evidence snapshots. Fenced code and existing link labels are not treated as citations. Model HTML and images are disabled. Document hashes remain in the technical trace; source cards display the actual content and filename.

## Validation and remaining work

Offline tests validate storage, detection, tools, provider response handling, citation repair and rendering. Browser tests use simulated API responses to check loading, alert changes and document navigation. These tests do not establish real model quality.

Planned work includes repeatable live-model evaluations, persistent reports and optional direct provider integrations. Evaluate semantic support, numeric claims, missing-data handling and uncertainty before claiming reliable model explanations. Hypotheses are not verified physical root causes.

## Boundaries

Keep dependencies and layers minimal. Use only synthetic or suitable public data, keep the repository private, and do not change the original SignalWatch. Microservices, vector infrastructure, multi-agent orchestration, equipment control and cloud deployment are outside the current scope.
