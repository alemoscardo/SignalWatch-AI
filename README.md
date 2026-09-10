# SignalWatch AI

A small Python project for investigating synthetic telemetry alerts with an AI agent.

## Status

Initial project scaffold. Telemetry storage, detection, the agent and the user interface are not implemented yet. This repository is separate from the original C# SignalWatch project.

## Intended first demo

1. Load a short sequence of synthetic sensor readings.
2. Detect an out-of-range value with a Python function.
3. Request an investigation of that alert.
4. Let one agent request readings and search a small set of fictional technical documents through bounded, read-only functions.
5. Show a report separating observations, possible explanations, missing data and suggested checks, with references to the evidence used.

## Keep it understandable

- One Python application; no C# service integration.
- SQLite is the proposed storage option, using a local file.
- Ordinary Python functions for detection and data access.
- A direct model SDK is the proposed starting point. Provider and model remain to be chosen.
- No LangGraph, vector database or message broker initially.
- Choose the interface together before implementing it.
- Add Docker packaging after the local demo works.

All data and technical documents must be synthetic or suitable public material. The agent must not modify equipment, thresholds or alert status. No employer or customer information belongs in this repository.

## Development

Python 3.11 or later. The scaffold has no runtime dependencies or paid-service setup.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

There is no application command yet. See [the design brief](docs/design-brief.md) for the next decisions.
