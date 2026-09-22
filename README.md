# SignalWatch AI

A local synthetic telemetry investigation app with Python, PostgreSQL/pgvector and a browser interface. A local encoder searches technical guidance; a free OpenRouter model investigates with read-only tools. The original C# SignalWatch repository is separate.

## Setup on Windows

Use Python 3.12 and Docker Desktop with Linux containers. The tested dependency versions are in `requirements.lock`; the encoder runs on CPU. The initial package/model download requires internet access.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env
```

Copy the example only if `.env` does not exist. Choose a local database password, put it in `SIGNALWATCH_DB_PASSWORD` and the password portion of `DATABASE_URL`, and add your existing OpenRouter key. Keep `.env` private. Credentials stay on the server. Existing environment variables take precedence.

```powershell
docker compose up -d --wait
.\.venv\Scripts\signalwatch-db.exe init
```

For existing SQLite data, migrate before seeding. See the next section. For a fresh demo:

```powershell
.\.venv\Scripts\signalwatch-db.exe seed
.\.venv\Scripts\signalwatch-db.exe encoder-setup
.\.venv\Scripts\signalwatch-db.exe prepare
.\.venv\Scripts\signalwatch.exe
```

Open [the local app](http://127.0.0.1:5055). `--port 5056` chooses another port. The server binds to loopback with debugging disabled. PostgreSQL is exposed only on `127.0.0.1:55432` and persists in the Compose volume. Do not delete that volume to restart the app.

`encoder-setup` downloads the pinned pretrained model once. It refuses to overwrite an existing model directory. `prepare` reads the catalog, validates documents, splits sections, computes embeddings and publishes a corpus generation transactionally. Stop the app before preparing or migrating. If sources change, new investigations are blocked until preparation succeeds. Previously saved reports retain their evidence snapshots.

## Migrating the previous SQLite demo

Stop the previous app before migrating so no new legacy reports are written after the snapshot. The migration reads originals without changing them and makes consistent SQLite backups, including committed WAL contents, in `data/local/migration-backups/`.

```powershell
.\.venv\Scripts\signalwatch-db.exe migrate PATH_TO_OLD_DATA/demo.sqlite3 --dataset demo
.\.venv\Scripts\signalwatch-db.exe migrate PATH_TO_OLD_DATA/demo-timeline.sqlite3 --dataset timeline
.\.venv\Scripts\signalwatch-db.exe migrate PATH_TO_OLD_DATA/demo-investigations.sqlite3
```

Also import any `demo-missing`, `demo-spike`, `demo-steady-speed` and `demo-sustained` files with their matching `--dataset`. Then run `seed` to create only datasets that have no readings. Import verifies exact values, UTC timestamps, gaps, alert results and report payloads before committing. Identical imports are recognized. Different readings in an existing dataset or conflicting report IDs fail without overwriting records. Keep original files as recovery copies. PostgreSQL is the only active database after migration; there is no SQLite fallback or dual write.

Before accepting new PostgreSQL reports, verify the imported history. Returning to the old app later requires preserving/exporting any new PostgreSQL reports; the old SQLite snapshot will not contain them.

## Using the demo

The graph presents a continuous 24-hour history with five synthetic episodes and six temperature alerts. Pan, zoom, and select an amber alert marker. Selection never makes a model call. Add optional context and choose Investigate. The model chooses its own measurement intervals and how many tool calls it needs.

Citations open retrieved source snapshots. Measurement citations also highlight the matching sample. Reports support safe Markdown; model HTML and images are disabled. Previous investigations reopen without a model call and keep their original evidence even after documents change. Older dataset citations open their snapshot without being placed on an unrelated graph.

The knowledge-base status reports readiness, document count and generation. Fifteen fictional Markdown documents contain 26 passages, including other-equipment, archived, future, conflicting and untrusted guidance. The catalog assigns equipment and half-open validity intervals. The model cannot override these filters: M-01 investigations use general or M-01 guidance valid at the selected alert time.

## Agent and retrieval behaviour

The two tools are `read_measurements(sensor, start, end)` and `search_documents(query)`. Python validates arguments and executes predefined PostgreSQL queries through read-only connections. No arbitrary SQL, shell or equipment controls are exposed. Application code separately saves reports.

The local `all-MiniLM-L6-v2` encoder produces 384-dimensional vectors. pgvector computes exact cosine similarity over eligible passages. Semantic retrieval is the app default, selected using development cases. A word-overlap baseline and combined ranking remain available in the evaluation command. Up to five deduplicated passages are returned per query. This is not an investigation call-count or time-window limit. A provisional similarity cutoff of 0.35 filters candidates; it is not a probability of correctness and does not eliminate every irrelevant result.

Both evidence tools must execute successfully. Every available source category must be cited. If a successful tool returns no evidence, the report must explicitly state `Insufficient evidence`; missing evidence is allowed, fabricated citations are not. A tool/database error is not a successful empty result. One guided citation-repair opportunity is allowed. These checks establish reference existence and retrieval, not semantic support of every claim. The `references_valid` result status means both source categories were retrieved and cited, not a verified physical diagnosis.

Thresholds remain deterministic Python: temperature strictly above 80 degrees Celsius, one alert per continuous excursion. Missing minutes break continuity. There are no configured speed or missing-data alarms. Reports must distinguish observations, hypotheses, missing data and suggested checks. Correlation does not establish a physical cause.

OpenRouter requests accept only `openrouter/free` or IDs ending in `:free`, with provider price limits of zero and no paid fallback. A request has a 90-second network timeout; provider errors stop the investigation. There is no fixed limit on the complete investigation loop. Token usage is unknown when the provider omits it. Trace entries record actual tool arguments, results and duration.

## Evaluation

Retrieval evaluation runs the actual local encoder and PostgreSQL search without generation API calls. Forty labelled synthetic queries are split into 30 development and 10 held-out cases. The latter are reported without tuning to them. Both expected-passage coverage and false positives matter; first-five success alone is not a reliability guarantee.

```powershell
.\.venv\Scripts\signalwatch-db.exe evaluate retrieval --split development
.\.venv\Scripts\signalwatch-db.exe evaluate retrieval --split held_out
```

For real-model evaluation, select a specific tool-capable `:free` model in `.env`. The automatic free router is rejected for comparable evaluations. Twelve scenarios cover telemetry patterns, missing facts, conflicting guidance and hostile input.

```powershell
.\.venv\Scripts\signalwatch-db.exe evaluate reports --mode semantic --live
```

Use `--attempts 3` for repeated trials when provider availability permits. This controls evaluation repetitions, not agent tool calls. Runs, failures and snapshots are stored in PostgreSQL; exports go to `reports/local/`. Interrupted runs remain visible. A hard process termination can leave a `running` record, which must not be counted as a completed attempt.

A reference-valid report has no automatic semantic-quality score. Review numerical consistency, citation support, missing data, conflicting sources and causal restraint using the rubric in `docs/evaluation-review.json`. Fill each reason and verdict after reading the actual report and source snapshots.

```powershell
.\.venv\Scripts\signalwatch-db.exe review RUN_ID CASE_ID semantic PATH_TO_COMPLETED_REVIEW.json
.\.venv\Scripts\signalwatch-db.exe export RUN_ID
```

The exported comparison reports raw counts, per-case outcomes, timing and pending reviews. Simulated-response tests check software behaviour only. Results and limitations are recorded in [`docs/validation.md`](docs/validation.md). The checked-in `docs/evaluation-review.json` is an evidence-based assistant review for case `r06`; it is an example of the required five-criterion shape, not independent human validation.

## Offline verification

Tests require PostgreSQL and the prepared local encoder. Set `SIGNALWATCH_TEST_DATABASE_URL` to a local connection string whose database name ends in `_test`; its role must be allowed to create databases. Tests create and remove uniquely named disposable databases. They never read OpenRouter credentials and do not call a generation API.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check src/signalwatch_ai/static/app.js
.\.venv\Scripts\python.exe -m black --check src tests
```

Browser tests use Playwright with intercepted model responses. With Edge installed:

```powershell
$env:SIGNALWATCH_TEST_BROWSER = "msedge"
.\.venv\Scripts\python.exe tests/browser_smoke.py
```

The suite covers PostgreSQL isolation, migration rollback and snapshots, applicability boundaries, failed preparation, encoder limits, invalid inputs, insufficient evidence, citation rendering, progress and history. Browser coverage includes graph navigation, saved reports, document search and errors.

## Backup and restore

Create a PostgreSQL custom-format backup inside the container, then copy it without PowerShell binary redirection:

```powershell
docker compose exec -T postgres pg_dump -U signalwatch -d signalwatch -Fc -f /tmp/signalwatch.dump
docker compose cp postgres:/tmp/signalwatch.dump data/local/signalwatch.dump
```

Verify a restore into a new database before relying on the backup:

```powershell
docker compose exec -T postgres createdb -U signalwatch signalwatch_restore_check
docker compose exec -T postgres pg_restore -U signalwatch -d signalwatch_restore_check --exit-on-error /tmp/signalwatch.dump
```

Use a new name if that verification database already exists. Compare table counts and report snapshots. A restore backup includes embeddings and evidence; retain the corresponding source files and encoder files to satisfy readiness checks. `docker compose restart postgres` preserves the named volume. Do not run `down -v` against data you want to keep.

## Code map

- `database.py` and `schema.sql`: connection and versioned schema.
- `telemetry.py`: synthetic data, measurements and thresholds.
- `migration.py`: explicit SQLite import and verification.
- `encoder.py`: model download and local encoding.
- `knowledge.py`: catalog validation, corpus publication and retrieval.
- `evidence.py` and `presentation.py`: citations and safe rendering.
- `agent.py`: OpenRouter transport, tool loop and reference checks.
- `history.py`: stored investigation snapshots.
- `evaluation.py` and `commands.py`: evaluation, review/export and setup commands.
- `web.py`, templates and static files: browser application.

No framework-based orchestration, ORM, additional agent, vector server or paid service is used. The supported document format is curated English Markdown, not arbitrary PDFs/OCR. Keep the repository private and use synthetic or suitable public data only.

Plotly.js basic 3.5.1 remains bundled locally with its MIT license. There is no frontend build step or runtime CDN dependency. See the design brief and implementation plan for the scope and remaining quality limitations.
