"""Local browser demo with optional OpenRouter investigation."""

import json
import argparse
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

from flask import abort, Flask, jsonify, render_template, request, Response

from .evidence import document_sections, search_documents
from .telemetry import (
    SCENARIOS,
    TEMPERATURE_LIMIT,
    detect_alerts,
    read_measurements,
    seed_demo,
    dataset_range,
)
from .agent import investigate, investigation_events
from . import history
from .presentation import render_report


def create_app(database: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16384
    database = database or Path("data/local/demo.sqlite3")
    seed_demo(database)
    history_path = database.with_name(f"{database.stem}-investigations.sqlite3")
    history.initialize(history_path)

    def scenario_database(scenario):
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            abort(400, description="Invalid scenario.")
        path = (
            database
            if scenario == "demo"
            else database.with_name(f"{database.stem}-{scenario}{database.suffix}")
        )
        seed_demo(path, scenario)
        return path

    @app.get("/")
    def index():
        scenario = "timeline"
        path = scenario_database(scenario)
        temperature = read_measurements(path, "temperature")
        return render_template(
            "index.html",
            readings=temperature,
            speed=read_measurements(path, "speed"),
            scenario=scenario,
            time_range=dataset_range(path),
            alerts=detect_alerts(temperature),
            threshold=TEMPERATURE_LIMIT,
            documents=document_sections(),
            ai_ready=bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
        )

    @app.post("/api/investigate")
    def investigation():
        if request.headers.get("Origin") not in (None, request.host_url.rstrip("/")):
            return jsonify(error="Origin not allowed."), 403
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("context", ""), str):
            return jsonify(error="Invalid request."), 400
        path = scenario_database(body.get("scenario", "demo"))
        alerts = detect_alerts(read_measurements(path, "temperature"))
        alert = next(
            (item for item in alerts if item["id"] == body.get("alert_id")), None
        )
        if alert is None:
            return jsonify(error="Alert not found."), 404
        scenario = body.get("scenario", "demo")
        context = body.get("context", "")

        def finish(result):
            try:
                report_id = history.save(history_path, scenario, alert, context, result)
            except sqlite3.Error:
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
                    for event in investigation_events(path, alert, context):
                        if event["type"] == "result":
                            event["result"] = finish(event["result"])
                        yield json.dumps(event, ensure_ascii=False) + "\n"
                except (ValueError, RuntimeError) as error:
                    yield json.dumps(
                        {
                            "type": "error",
                            "message": str(error),
                        }
                    ) + "\n"

            return Response(
                stream(),
                mimetype="application/x-ndjson",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        try:
            result = investigate(path, alert, context)
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
        return jsonify(history.list_reports(history_path, scenario))

    @app.get("/api/investigations/<int:report_id>")
    def saved_investigation(report_id):
        result = history.load(history_path, report_id)
        if result is None:
            abort(404)
        result["report_html"] = render_report(result["report"], result.get("trace", []))
        return jsonify(result)

    @app.get("/api/measurements")
    def measurements():
        try:
            return jsonify(
                read_measurements(
                    scenario_database(request.args.get("scenario", "demo")),
                    request.args.get("sensor", ""),
                    request.args.get("start"),
                    request.args.get("end"),
                )
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/documents")
    def documents():
        return jsonify(search_documents(request.args.get("q", "")))

    return app


def main() -> None:
    load_dotenv(Path.cwd() / ".env", encoding="utf-8-sig")
    parser = argparse.ArgumentParser(description="Run the local SignalWatch demo")
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
