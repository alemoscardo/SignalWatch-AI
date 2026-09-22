# Design brief

## Implemented design

One local Flask application uses PostgreSQL with pgvector as its only active database. Python functions handle telemetry, predefined read-only queries, document preparation and the OpenRouter tool loop. There is no ORM, agent framework or additional agent service.

The existing synthetic timeline and threshold rules are preserved. Temperature strictly above 80 degrees Celsius starts an excursion; missing minutes break continuity. SQLite is used only by the explicit legacy migration command. Nine existing investigation snapshots and six datasets were imported and verified locally.

Fifteen English synthetic Markdown documents produce 26 passages. A catalog assigns equipment, revision and validity dates. A pinned local all-MiniLM-L6-v2 encoder generates 384-dimensional embeddings on CPU. PostgreSQL computes exact cosine similarity after equipment/date filtering. The app uses semantic retrieval; lexical and combined alternatives are available for evaluation. Five results per query do not limit the investigation's time windows or tool-call count.

Corpus preparation validates documents, rejects incompatible input, and publishes an entire generation transactionally. A source/model mismatch blocks new investigations. Saved reports retain their original evidence snapshots. PostgreSQL availability is required for graph and history reads.

The browser keeps the existing graph, citations, streaming progress and saved history. Source cards add equipment and revision. Safe Markdown rendering preserves versioned citation identifiers. No source text can grant the model access to arbitrary SQL, shell or equipment controls.

## Evidence contracts

The model must successfully attempt both evidence tools and cite each available source category. A successful empty search permits an explicitly labelled insufficient-evidence report. Errors are distinct from no evidence. One guided citation correction remains available. The status `supported` means retrieved references passed structural checks; it does not certify semantic support or physical causation.

Thresholds and tool validation are deterministic Python. Document text and additional user context are untrusted evidence. Reports distinguish observations, hypotheses, missing data and suggested checks. OpenRouter accepts any model that supports the required tool calls. The browser can hold a key temporarily in the local app process; it does not persist that key. Encoding and retrieval are local; report generation uses the network.

## Evaluation and limits

The repository contains 40 labelled retrieval cases and 12 real-model investigation cases. Commands store runs, errors and snapshots in PostgreSQL and export JSON/Markdown. Automated real-model evaluation reports completion, failures, tool traces, retrieved evidence and structural citation checks; it does not assign semantic-quality scores. Optional human or assistant reviews can be recorded with five explicit criteria. Offline tests use simulated generation responses and do not measure real-model quality.

See [validation results](validation.md) for actual retrieval counts, provider failures and observed model errors. The initial held-out set shares some concepts with development cases and is small; it is a regression check, not proof of generalization. Real-model adversarial coverage remains incomplete because the provider rate-limited those attempts. No reliability claim is made from structural citation success.

## Boundaries

Use only synthetic or suitable public data. Keep the repository private and the original C# repository unchanged. The supported input is curated English Markdown. PDF/OCR ingestion, multi-user deployment, cloud services, equipment control and multi-agent orchestration remain outside scope.

The approved implementation direction and its remaining evaluation limits are recorded in this design brief. Its operational features and automated real-model evaluation are implemented; semantic quality remains outside automatic acceptance unless an optional review is performed, as documented in validation.md.
