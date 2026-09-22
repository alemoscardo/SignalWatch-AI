# Implementation validation

Date: 22 September 2026. This document separates the historical verification of the implemented PostgreSQL/RAG milestone from the current Windows environment check. The application uses synthetic data and does not claim reliable physical diagnosis.

## Current checkout and environment check

- The local PostgreSQL service is healthy. The active knowledge-base generation is ready with 15 documents and 26 active passages.
- The local database currently contains six datasets, 4,632 measurements and nine saved investigation snapshots. These are local runtime data, not required repository artifacts.
- `black --check src tests` passed, and `node --check src/signalwatch_ai/static/app.js` passed.
- The full Python suite was attempted on this checkout. It discovered 58 tests, but template setup stopped when importing `sentence-transformers` reached PyTorch and Windows blocked `torch/lib/shm.dll` with `WinError 4551`. The resulting failures are environment/setup failures, not a valid regression result for the application logic.
- The last complete regression remains the historical run below: 53 Python tests and five Edge/Playwright browser tests passed on 11 September 2026. The current uncommitted milestone was not declared green from the blocked run.

## Historical software and data checks

These checks were completed on 11 September 2026 against Python 3.12, PostgreSQL 17 with pgvector 0.8.2 and the pinned local `all-MiniLM-L6-v2` encoder.

- 53 offline Python tests passed against disposable PostgreSQL databases and the real local encoder, including a regression test for versioned citation links.
- Five Edge/Playwright browser tests passed with simulated report responses. They covered streaming, errors, document search, citations, graph navigation and saved reports.
- The original six SQLite datasets were verified against PostgreSQL: 4,632 measurements. All nine investigation payloads were preserved. Seven import records include the history file. Original SQLite files were not modified; consistent recovery snapshots were created.
- A custom-format PostgreSQL backup was restored into a separate verification database. Counts for measurements, investigations, passages, evaluation results and imports matched; all investigation payloads matched exactly.
- PostgreSQL was restarted with its persistent volume. No SQLite fallback is used.
- Document readiness uses source and encoder fingerprints. Preparation rollback, conflicting import IDs, UTC normalization, missing samples, wrong equipment/revisions, long inputs and read-only tool connections are covered by tests.

## Retrieval results

The application default was selected on development cases before held-out results were opened. No tuning was done against held-out results. These are the historical retrieval results, not a new run from the blocked current environment.

| Method | Development expected passage in first five | Development irrelevant candidates on unanswerable queries | Held-out expected passage in first five | Held-out irrelevant candidates |
| --- | --- | --- | --- | --- |
| Lexical | 22/25 | 1/5 | 8/8 | 0/2 |
| Semantic | 23/25 | 0/5 | 7/8 | 0/2 |
| Combined | 22/25 | 0/5 | 8/8 | 0/2 |

All methods returned zero explicitly forbidden sources in these fixtures. Coverage of all required passages is lower than first-hit success for multi-source questions. Semantic search is not universally better: it misses held-out q36 about constant speed and mechanical torque. The first model load took about 7–8 seconds; later semantic queries were generally around 0.05–0.08 seconds on that machine. This is a tiny synthetic benchmark, and several held-out concepts overlap development concepts, so it is not a strong generalization result.

Raw reports: [development](evaluation-results/evaluation-1.md) and [held-out](evaluation-results/evaluation-3.md). JSON exports alongside them contain source passages, configuration and individual results.

## Actual model run

Run 4 used `nex-agi/nex-n2.5-mini:free` with semantic retrieval. It completed five of twelve planned investigations with structurally valid references. One attempt failed with an interrupted provider response after about 735 seconds; six later attempts received OpenRouter rate-limit errors. No paid fallback or repeated automatic retries were used.

The prompt and corpus hashes are saved in the run configuration. The stored status `supported` is accepted for compatibility with this historical run; current code uses `references_valid` for a report whose retrieved references pass structural checks. Neither status proves semantic support or a physical cause.

The five completed reports were inspected against the fixture expectations:

- `r01` reports measurements and keeps the temperature/speed relationship as an association rather than a verified cause.
- `r02` correctly describes the sustained 92 °C readings and constant speed, but one claim about what the recovery passage establishes is broader than the cited text.
- `r03` identifies the gap between 09:35 and 09:51 without interpolating missing readings.
- `r05` correctly says constant rpm does not establish constant mechanical load, although some proposed causes and missing-data claims extend beyond the cited passages.
- `r06` reports the temperature values and keeps cooling as a hypothesis, but it incorrectly says speed measurements are absent after retrieving only temperature. It also cites a suggested-checks passage for a threshold statement that the passage does not contain.

The checked-in [review payload](evaluation-review.json) records an assistant review for `r06`: numeric consistency and causal restraint pass, citation support and missing-data handling fail, and conflict review is not applicable. This is evidence-based software review, not independent human validation.

The complete [run report](evaluation-results/evaluation-4.md) records completion and failure counts. Rate-limited cases include conflicting-guidance, hostile-input and unrelated-question trials, so those cases were not validated by the live run.

## Remaining limitations

- Full repeatable model-quality acceptance is not established. Only five complete real-model outputs are available, semantic errors were observed, and independent human review is still pending for the remaining reports.
- The held-out retrieval set is small and synthetic. It is a regression check, not evidence of industrial reliability.
- Structural citation validation checks that references were retrieved. It does not determine whether each free-form claim is semantically supported.
- The current Windows environment needs a reproducible fix or documented workaround for the PyTorch DLL block before the full checkout can be called green.
- A similarity threshold, a valid citation or a model-generated explanation is not proof of a correct physical diagnosis.
