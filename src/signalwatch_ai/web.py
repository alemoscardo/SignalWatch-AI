"""Local browser demo with optional OpenRouter investigation."""

import json
import argparse
import os
import psycopg
from pathlib import Path
from dotenv import load_dotenv

from flask import abort, Flask, jsonify, render_template, request, Response

from .knowledge import (
    MODES,
    document_sections,
    search_documents,
    status as knowledge_status,
)
from .database import connect, MAINTENANCE_LOCK
from .telemetry import (
    SCENARIOS,
    TEMPERATURE_LIMIT,
    detect_alerts,
    read_measurements,
    dataset_range,
)
from .agent import DEFAULT_OPENROUTER_MODEL, complete, investigate, investigation_events
from . import history
from .presentation import render_report


def configured_retrieval_mode():
    mode = os.getenv("SIGNALWATCH_RETRIEVAL_MODE", "semantic").strip().lower()
    if mode not in MODES:
        raise RuntimeError(
            "SIGNALWATCH_RETRIEVAL_MODE must be lexical, semantic or hybrid."
        )
    return mode


def create_app(database=None) -> Flask:
    database = database or os.getenv("DATABASE_URL")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16384
    # A dictionary temporarily overrides the process environment for this app.
    app.config["OPENROUTER_SESSION"] = None

    def provider_config():
        override = app.config["OPENROUTER_SESSION"]
        if isinstance(override, dict):
            return override
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key:
            return None
        model = os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
        return {"api_key": key, "model": model or DEFAULT_OPENROUTER_MODEL}

    def provider_status():
        config = provider_config()
        return {
            "provider": "OpenRouter",
            "configured": config is not None,
            "model": config["model"] if config else os.getenv(
                "OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL
            ).strip()
            or DEFAULT_OPENROUTER_MODEL,
        }

    def provider_completion():
        config = provider_config()
        if config is None:
            # Pass an explicit empty key so a missing provider fails clearly.
            return lambda messages: complete(
                messages, api_key="", model=DEFAULT_OPENROUTER_MODEL
            )
        return lambda messages: complete(
            messages, api_key=config["api_key"], model=config["model"]
        )

    def allowed_origin():
        return request.headers.get("Origin") in (
            None,
            request.host_url.rstrip("/"),
        )

    def validate_scenario(scenario):
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            abort(400, description="Invalid scenario.")
        return scenario

    @app.errorhandler(psycopg.Error)
    def database_error(error):
        return (
            jsonify(
                error="PostgreSQL unavailable or not initialized. Check the database service and run signalwatch-db init."
            ),
            503,
        )

    @app.errorhandler(RuntimeError)
    def setup_error(error):
        return jsonify(error=str(error)), 503

    @app.post("/api/provider/session")
    def configure_provider():
        if not allowed_origin():
            return jsonify(error="Origin not allowed."), 403
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"api_key", "model"}:
            return jsonify(error="Invalid provider configuration."), 400
        api_key = body.get("api_key")
        model = body.get("model", DEFAULT_OPENROUTER_MODEL)
        if not isinstance(api_key, str) or not api_key.strip():
            return jsonify(error="Enter an OpenRouter API key."), 400
        if not isinstance(model, str) or not model.strip():
            return jsonify(error="Enter an OpenRouter model identifier."), 400
        if len(api_key) > 4096 or len(model.strip()) > 200:
            return jsonify(error="The provider configuration is too long."), 400
        app.config["OPENROUTER_SESSION"] = {
            "api_key": api_key.strip(),
            "model": model.strip(),
        }
        response = jsonify(provider_status())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.delete("/api/provider/session")
    def forget_provider():
        if not allowed_origin():
            return jsonify(error="Origin not allowed."), 403
        app.config["OPENROUTER_SESSION"] = None
        response = jsonify(provider_status())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        scenario = "timeline"
        validate_scenario(scenario)
        temperature = read_measurements(database, "temperature", scenario=scenario)
        provider = provider_status()
        return render_template(
            "index.html",
            readings=temperature,
            speed=read_measurements(database, "speed", scenario=scenario),
            scenario=scenario,
            time_range=dataset_range(database, scenario),
            alerts=detect_alerts(temperature),
            threshold=TEMPERATURE_LIMIT,
            documents=document_sections(database),
            knowledge=knowledge_status(database),
            provider=provider,
        )

    @app.post("/api/investigate")
    def investigation():
        if not allowed_origin():
            return jsonify(error="Origin not allowed."), 403
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("context", ""), str):
            return jsonify(error="Invalid request."), 400
        scenario = body.get("scenario", "demo")
        validate_scenario(scenario)
        state = knowledge_status(database)
        if not state["ready"]:
            return jsonify(error=state["message"]), 503
        alerts = detect_alerts(
            read_measurements(database, "temperature", scenario=scenario)
        )
        alert = next(
            (item for item in alerts if item["id"] == body.get("alert_id")), None
        )
        if alert is None:
            return jsonify(error="Alert not found."), 404
        context = body.get("context", "")
        retrieval_mode = configured_retrieval_mode()
        completion = provider_completion()

        def finish(result):
            try:
                report_id = history.save(database, scenario, alert, context, result)
            except psycopg.Error:
                raise RuntimeError(
                    "The investigation could not be saved. Check local database access and available disk space."
                ) from None
            return {
                **result,
                "id": report_id,
                "report_html": render_report(result["report"], result.get("trace", [])),
            }

        if request.accept_mimetypes.best == "application/x-ndjson":

            def stream():
                try:
                    for event in investigation_events(
                        database,
                        alert,
                        context,
                        completion=completion,
                        scenario=scenario,
                        mode=retrieval_mode,
                    ):
                        if event["type"] == "result":
                            event["result"] = finish(event["result"])
                        yield json.dumps(event, ensure_ascii=False) + "\n"
                except (ValueError, RuntimeError, psycopg.Error) as error:
                    yield json.dumps(
                        {
                            "type": "error",
                            "message": (
                                "PostgreSQL unavailable."
                                if isinstance(error, psycopg.Error)
                                else str(error)
                            ),
                        }
                    ) + "\n"

            return Response(
                stream(),
                mimetype="application/x-ndjson",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        try:
            result = investigate(
                database,
                alert,
                context,
                completion=completion,
                scenario=scenario,
                mode=retrieval_mode,
            )
            return jsonify(finish(result))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except RuntimeError as error:
            return jsonify(error=str(error)), 502

    @app.get("/api/investigations")
    def previous_investigations():
        scenario = request.args.get("scenario")
        if scenario is not None and scenario not in SCENARIOS:
            abort(400)
        return jsonify(history.list_reports(database, scenario))

    @app.get("/api/investigations/<int:report_id>")
    def saved_investigation(report_id):
        result = history.load(database, report_id)
        if result is None:
            abort(404)
        result["report_html"] = render_report(result["report"], result.get("trace", []))
        return jsonify(result)

    @app.get("/api/measurements")
    def measurements():
        try:
            return jsonify(
                read_measurements(
                    database,
                    request.args.get("sensor", ""),
                    request.args.get("start"),
                    request.args.get("end"),
                    scenario=validate_scenario(request.args.get("scenario", "demo")),
                )
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/documents")
    def documents():
        try:
            return jsonify(
                search_documents(
                    request.args.get("q", ""),
                    database,
                    mode=configured_retrieval_mode(),
                )
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/knowledge")
    def knowledge():
        return jsonify(knowledge_status(database))

    return app


def main() -> None:
    load_dotenv(Path.cwd() / ".env", encoding="utf-8-sig")
    parser = argparse.ArgumentParser(description="Run the local SignalWatch demo")
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    with connect() as db:
        db.execute("SELECT pg_advisory_lock_shared(%s)", (MAINTENANCE_LOCK,))
        db.commit()
        create_app().run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
